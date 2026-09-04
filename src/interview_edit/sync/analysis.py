from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from interview_edit.errors import PreflightError


@dataclass(frozen=True)
class WindowEstimate:
    center_us: int
    offset_us: int
    confidence: float
    peak_margin: float


@dataclass(frozen=True)
class SyncEstimate:
    offset_us: int
    drift_us_per_hour: int
    drift_ppm: int
    confidence: float
    windows: tuple[WindowEstimate, ...]


def energy_envelope(path: Path, *, envelope_hz: int, sample_rate: int) -> NDArray[np.float64]:
    try:
        handle = wave.open(str(path), "rb")
    except (OSError, wave.Error) as exc:
        raise PreflightError(
            "sync_audio_unreadable",
            "A normalized WAV proxy could not be read for synchronization.",
            details={"path": str(path), "reason": str(exc)},
        ) from exc
    with handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        input_rate = handle.getframerate()
        if width != 2 or channels < 1:
            raise PreflightError(
                "sync_audio_format_unsupported",
                "Synchronization requires 16-bit PCM WAV audio proxies.",
                details={"path": str(path), "channels": channels, "sampleWidth": width},
            )
        if input_rate % envelope_hz != 0 or input_rate % sample_rate != 0:
            raise PreflightError(
                "sync_audio_rate_unsupported",
                "Audio proxy rate must be divisible by sync sample and envelope rates.",
                details={
                    "path": str(path),
                    "audioRate": input_rate,
                    "sampleRate": sample_rate,
                    "envelopeHz": envelope_hz,
                },
            )
        input_hop = input_rate // envelope_hz
        decimation = input_rate // sample_rate
        block_frames = input_hop * 4096
        values: list[NDArray[np.float64]] = []
        pending = np.empty((0, channels), dtype=np.int16)
        while True:
            raw = handle.readframes(block_frames)
            if not raw:
                break
            samples = np.frombuffer(raw, dtype="<i2")
            samples = samples[: (samples.size // channels) * channels].reshape(-1, channels)
            if pending.size:
                samples = np.concatenate((pending, samples), axis=0)
            complete = (samples.shape[0] // input_hop) * input_hop
            pending = samples[complete:]
            if complete == 0:
                continue
            mono = samples[:complete].astype(np.float64).mean(axis=1)
            reduced = mono.reshape(-1, input_hop)[:, ::decimation]
            rms = np.sqrt(np.mean(np.square(reduced), axis=1))
            values.append(np.log1p(rms))
    if not values:
        return np.empty(0, dtype=np.float64)
    return np.concatenate(values)


def _fft_correlate(
    reference: NDArray[np.float64], target: NDArray[np.float64], max_lag: int
) -> tuple[int, float, float]:
    if reference.size != target.size or reference.size < 4:
        return 0, 0.0, 0.0
    reference = reference - np.mean(reference)
    target = target - np.mean(target)
    reference_norm = float(np.linalg.norm(reference))
    target_norm = float(np.linalg.norm(target))
    if reference_norm < 1e-9 or target_norm < 1e-9:
        return 0, 0.0, 0.0
    output_size = reference.size + target.size - 1
    fft_size = 1 << max(1, (output_size - 1).bit_length())
    correlation = np.fft.irfft(
        np.fft.rfft(target, fft_size) * np.fft.rfft(reference[::-1], fft_size),
        fft_size,
    )[:output_size]
    lags = np.arange(-(reference.size - 1), target.size)
    allowed = np.abs(lags) <= max_lag
    normalized = correlation[allowed] / (reference_norm * target_norm)
    allowed_lags = lags[allowed]
    if normalized.size == 0:
        return 0, 0.0, 0.0
    peak_index = int(np.argmax(normalized))
    peak = float(np.clip(normalized[peak_index], 0.0, 1.0))
    masked = normalized.copy()
    exclusion = max(2, min(10, max_lag // 20))
    masked[max(0, peak_index - exclusion) : peak_index + exclusion + 1] = -1.0
    second = max(0.0, float(np.max(masked))) if masked.size else 0.0
    margin = float(np.clip(peak - second, 0.0, 1.0))
    confidence = float(np.sqrt(peak * margin))
    return int(allowed_lags[peak_index]), confidence, margin


def window_centers_us(
    duration_us: int, *, window_count: int, window_duration_us: int
) -> tuple[int, ...]:
    if duration_us <= 0:
        return ()
    effective_window = min(window_duration_us, max(1, duration_us // 2))
    if window_count == 1:
        return (duration_us // 2,)
    first = effective_window // 2
    last = duration_us - effective_window // 2
    return tuple(int(round(value)) for value in np.linspace(first, last, window_count))


def estimate_sync(
    reference: NDArray[np.float64],
    target: NDArray[np.float64],
    *,
    envelope_hz: int,
    window_count: int,
    window_duration_us: int,
    max_offset_us: int,
) -> SyncEstimate:
    common_size = min(reference.size, target.size)
    if common_size < max(4, envelope_hz * 2):
        raise PreflightError(
            "sync_audio_too_short",
            "At least two seconds of common audio are required for synchronization.",
            details={"commonDurationUs": common_size * 1_000_000 // envelope_hz},
        )
    duration_us = common_size * 1_000_000 // envelope_hz
    requested_window_bins = max(4, window_duration_us * envelope_hz // 1_000_000)
    window_bins = min(requested_window_bins, max(4, common_size // 2))
    max_lag_bins = min(max_offset_us * envelope_hz // 1_000_000, window_bins // 2)
    centers = window_centers_us(
        duration_us,
        window_count=window_count,
        window_duration_us=window_bins * 1_000_000 // envelope_hz,
    )
    windows: list[WindowEstimate] = []
    half = window_bins // 2
    for center_us in centers:
        center = center_us * envelope_hz // 1_000_000
        start = max(0, min(common_size - window_bins, center - half))
        end = start + window_bins
        lag, confidence, margin = _fft_correlate(
            reference[start:end], target[start:end], max_lag_bins
        )
        windows.append(
            WindowEstimate(
                center_us=center_us,
                offset_us=int(round(lag * 1_000_000 / envelope_hz)),
                confidence=confidence,
                peak_margin=margin,
            )
        )
    confidences = np.array([window.confidence for window in windows], dtype=np.float64)
    strongest = float(np.max(confidences))
    trusted = confidences >= max(0.1, strongest * 0.5)
    if not bool(np.any(trusted)):
        trusted = np.ones_like(confidences, dtype=np.bool_)
    offsets = np.array([window.offset_us for window in windows], dtype=np.float64)[trusted]
    times = np.array([window.center_us for window in windows], dtype=np.float64)[trusted]
    if offsets.size >= 2 and float(np.ptp(times)) > 0:
        slope, intercept = np.polyfit(times, offsets, 1)
    else:
        slope = 0.0
        intercept = float(np.median(offsets))
    confidence = float(np.median(confidences))
    return SyncEstimate(
        offset_us=int(round(intercept)),
        drift_us_per_hour=int(round(slope * 3_600_000_000)),
        drift_ppm=int(round(slope * 1_000_000)),
        confidence=float(np.clip(confidence, 0.0, 1.0)),
        windows=tuple(windows),
    )
