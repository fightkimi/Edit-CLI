from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest


def require_media_tools() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        pytest.skip("FFmpeg and FFprobe are required for this integration test")
    return ffmpeg, ffprobe


def make_video(
    path: Path,
    *,
    color: str = "blue",
    frequency: int = 440,
    duration_seconds: float = 0.8,
) -> None:
    ffmpeg, _ = require_media_tools()
    path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x180:r=25:d={duration_seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate=48000:duration={duration_seconds}",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-y",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if completed.returncode != 0:
        pytest.skip(f"local FFmpeg cannot create H.264 fixture: {completed.stderr}")


def make_noise_wav(
    path: Path,
    *,
    duration_seconds: int,
    sample_rate: int = 16_000,
    seed: int = 20260903,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    generator = np.random.default_rng(seed)
    samples = generator.integers(
        -12_000, 12_001, size=duration_seconds * sample_rate, dtype=np.int16
    )
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.astype("<i2", copy=False).tobytes())


def make_video_from_audio(path: Path, audio_path: Path, *, delay_ms: int) -> None:
    ffmpeg, _ = require_media_tools()
    path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=25:d=8",
            "-i",
            str(audio_path),
            "-filter_complex",
            f"[1:a]adelay={delay_ms}:all=1,apad,atrim=duration=8[a]",
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-t",
            "8",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-y",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if completed.returncode != 0:
        pytest.skip(f"local FFmpeg cannot create synchronized fixture: {completed.stderr}")
