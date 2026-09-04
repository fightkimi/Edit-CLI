from __future__ import annotations

import json
import math
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from interview_edit.adapters.media import ProbeMetadata, parse_probe_payload
from interview_edit.adapters.process import ProcessRunner
from interview_edit.adapters.render import seconds
from interview_edit.errors import DependencyError, PreflightError, ProcessingError
from interview_edit.models.qc import LoudnessMeasurement, QCCommand, QCTimeRange

_BLACK_PATTERN = re.compile(
    r"black_start:(?P<start>-?[0-9.]+)\s+black_end:(?P<end>-?[0-9.]+)\s+"
    r"black_duration:(?P<duration>[0-9.]+)"
)
_SILENCE_START = re.compile(r"silence_start:\s*(?P<value>-?[0-9.]+)")
_SILENCE_END = re.compile(
    r"silence_end:\s*(?P<end>-?[0-9.]+)\s*\|\s*silence_duration:\s*(?P<duration>[0-9.]+)"
)


def _microseconds(value: str) -> int:
    try:
        result = Decimal(value) * Decimal(1_000_000)
    except InvalidOperation as exc:
        raise PreflightError(
            "qc_detector_output_invalid",
            "FFmpeg returned an invalid detector timestamp.",
            details={"value": value},
        ) from exc
    return max(0, int(result.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))


def parse_black_intervals(stderr: str) -> list[QCTimeRange]:
    intervals: list[QCTimeRange] = []
    for match in _BLACK_PATTERN.finditer(stderr):
        start = _microseconds(match.group("start"))
        end = _microseconds(match.group("end"))
        if end > start:
            intervals.append(QCTimeRange(start_us=start, end_us=end, duration_us=end - start))
    return intervals


def parse_silence_intervals(stderr: str) -> list[QCTimeRange]:
    intervals: list[QCTimeRange] = []
    pending_start: int | None = None
    for line in stderr.splitlines():
        start_match = _SILENCE_START.search(line)
        if start_match is not None:
            pending_start = _microseconds(start_match.group("value"))
        end_match = _SILENCE_END.search(line)
        if end_match is not None:
            end = _microseconds(end_match.group("end"))
            duration = _microseconds(end_match.group("duration"))
            start = pending_start if pending_start is not None else max(0, end - duration)
            if end > start:
                intervals.append(QCTimeRange(start_us=start, end_us=end, duration_us=end - start))
            pending_start = None
    return intervals


def _finite(value: object) -> float | None:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def parse_loudness_measurement(stderr: str) -> LoudnessMeasurement:
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start < 0 or end <= start:
        raise PreflightError(
            "qc_loudness_output_missing",
            "FFmpeg did not return a loudness measurement object.",
        )
    try:
        payload = json.loads(stderr[start : end + 1])
    except json.JSONDecodeError as exc:
        raise PreflightError(
            "qc_loudness_output_invalid",
            "FFmpeg returned invalid loudness measurement JSON.",
        ) from exc
    if not isinstance(payload, dict):
        raise PreflightError(
            "qc_loudness_output_invalid",
            "FFmpeg loudness measurement must be a JSON object.",
        )
    return LoudnessMeasurement(
        integrated_lufs=_finite(payload.get("input_i")),
        true_peak_dbtp=_finite(payload.get("input_tp")),
        loudness_range_lu=_finite(payload.get("input_lra")),
    )


def _run(
    args: list[str],
    runner: ProcessRunner,
    *,
    purpose: str,
    timeout_seconds: float = 6 * 60 * 60,
) -> tuple[QCCommand, str, str]:
    result = runner.run(args, timeout_seconds=timeout_seconds)
    command = QCCommand(purpose=purpose, args=list(result.args), return_code=result.return_code)
    if result.return_code == 127:
        raise DependencyError(
            f"{args[0]}_missing",
            f"Required executable is unavailable: {args[0]}.",
        )
    if result.return_code != 0:
        raise ProcessingError(
            "qc_command_failed",
            f"QC command failed: {purpose}.",
            details={
                "args": list(result.args),
                "returnCode": result.return_code,
                "stderr": result.stderr[-4000:],
            },
        )
    return command, result.stdout, result.stderr


def probe_qc_media(path: Path, runner: ProcessRunner) -> tuple[ProbeMetadata, QCCommand]:
    command, stdout, _ = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        runner,
        purpose="probe render output",
        timeout_seconds=120,
    )
    return parse_probe_payload(stdout), command


def scan_black(
    path: Path,
    runner: ProcessRunner,
    *,
    min_duration_seconds: float,
    pixel_threshold: float,
    picture_ratio: float,
) -> tuple[list[QCTimeRange], QCCommand]:
    command, _, stderr = _run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-i",
            str(path),
            "-vf",
            (
                f"blackdetect=d={min_duration_seconds:.6f}:"
                f"pix_th={pixel_threshold:.6f}:pic_th={picture_ratio:.6f}"
            ),
            "-an",
            "-f",
            "null",
            "-",
        ],
        runner,
        purpose="detect black intervals",
    )
    return parse_black_intervals(stderr), command


def scan_silence(
    path: Path,
    runner: ProcessRunner,
    *,
    min_duration_seconds: float,
    noise_db: float,
) -> tuple[list[QCTimeRange], QCCommand]:
    command, _, stderr = _run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            f"silencedetect=noise={noise_db:g}dB:d={min_duration_seconds:.6f}",
            "-vn",
            "-f",
            "null",
            "-",
        ],
        runner,
        purpose="detect silent intervals",
    )
    return parse_silence_intervals(stderr), command


def measure_loudness(
    path: Path,
    runner: ProcessRunner,
    *,
    integrated_lufs: float,
    true_peak_dbtp: float,
    loudness_range_lu: float,
) -> tuple[LoudnessMeasurement, QCCommand]:
    command, _, stderr = _run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            (
                f"loudnorm=I={integrated_lufs}:TP={true_peak_dbtp}:"
                f"LRA={loudness_range_lu}:print_format=json"
            ),
            "-vn",
            "-f",
            "null",
            "-",
        ],
        runner,
        purpose="measure output loudness",
    )
    return parse_loudness_measurement(stderr), command


def extract_frame(
    source: Path,
    output: Path,
    runner: ProcessRunner,
    *,
    timeline_time_us: int,
) -> QCCommand:
    command, _, _ = _run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            seconds(timeline_time_us),
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale=960:-2:force_original_aspect_ratio=decrease",
            "-q:v",
            "3",
            "-y",
            str(output),
        ],
        runner,
        purpose=f"extract QC frame at {timeline_time_us} us",
        timeout_seconds=120,
    )
    if not output.is_file() or output.stat().st_size == 0:
        raise ProcessingError(
            "qc_evidence_missing",
            "FFmpeg did not create the requested QC evidence frame.",
            details={"path": str(output), "timelineTimeUs": timeline_time_us},
        )
    return command
