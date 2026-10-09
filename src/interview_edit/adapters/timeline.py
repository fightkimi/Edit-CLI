from __future__ import annotations

import json
import math
import wave
from decimal import Decimal
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from interview_edit.adapters.process import ProcessRunner
from interview_edit.adapters.render import seconds
from interview_edit.errors import DependencyError, ProcessingError
from interview_edit.models.review import TimelineWord


def presentation_times(media: Path, start_us: int, end_us: int, runner: ProcessRunner) -> list[int]:
    result = runner.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-read_intervals",
            f"{seconds(max(0, start_us - 2_000_000))}%{seconds(end_us)}",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "json",
            str(media),
        ],
        timeout_seconds=120,
    )
    if result.return_code == 127:
        raise DependencyError("ffprobe_missing", "Timeline review requires FFprobe.")
    if result.return_code or result.stderr.strip():
        raise ProcessingError(
            "review_frame_probe_failed", "Video presentation times could not be read."
        )
    try:
        payload = json.loads(result.stdout)
        times = sorted(
            {
                int(Decimal(str(frame["best_effort_timestamp_time"])) * 1_000_000)
                for frame in payload["frames"]
                if "best_effort_timestamp_time" in frame
            }
        )
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise ProcessingError(
            "review_frame_probe_invalid", "Video presentation times are invalid."
        ) from exc
    if not times:
        raise ProcessingError("review_video_empty", "No video frames are available in this window.")
    return times


def audio_window(
    media: Path, output: Path, start_us: int, duration_us: int, runner: ProcessRunner
) -> np.ndarray:
    seek_us = max(0, start_us - 2_000_000)
    trim_start = start_us - seek_us
    # AAC concat can contain overlapping/gapped packet timestamps. Recover the playback clock
    # before trimming; raw decoded sample count alone is not a timeline coordinate.
    filters = (
        "aresample=48000:async=1:first_pts=0,"
        f"atrim=start={seconds(trim_start)}:end={seconds(trim_start + duration_us)},"
        "asetpts=PTS-STARTPTS"
    )
    result = runner.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-ss",
            seconds(seek_us),
            "-i",
            str(media),
            "-t",
            seconds(duration_us),
            "-map",
            "0:a:0",
            "-af",
            filters,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(output),
        ],
        timeout_seconds=120,
    )
    if result.return_code == 127:
        raise DependencyError("ffmpeg_missing", "Timeline review requires FFmpeg.")
    if result.return_code or result.stderr.strip():
        raise ProcessingError("review_audio_decode_failed", "Review audio could not be decoded.")
    with wave.open(str(output), "rb") as handle:
        if handle.getsampwidth() != 2 or handle.getnchannels() != 1 or not handle.getnframes():
            raise ProcessingError(
                "review_audio_empty", "Decoded audio window is empty or unsupported."
            )
        expected_samples = duration_us * 48_000 // 1_000_000
        if abs(handle.getnframes() - expected_samples) > 1:
            raise ProcessingError(
                "review_audio_truncated", "Audio does not cover the requested window."
            )
        return (
            np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(np.float64)
            / 32768
        )


def audio_levels(samples: np.ndarray) -> tuple[float | None, float | None]:
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples * samples)))
    return (20 * math.log10(peak) if peak else None, 20 * math.log10(rms) if rms else None)


def draw_timeline(
    frame_paths: list[Path],
    times: list[int],
    samples: np.ndarray | None,
    words: list[TimelineWord],
    start_us: int,
    end_us: int,
    focus_us: int,
    output: Path,
    font_path: Path | None,
) -> None:
    font = ImageFont.truetype(str(font_path), 18) if font_path else ImageFont.load_default(size=18)
    cell = 230
    margin = 30
    width = cell * len(frame_paths) + 2 * margin
    image = Image.new("RGB", (width, 620), "#151820")
    draw = ImageDraw.Draw(image)
    draw.text(
        (margin, 12),
        f"Timeline review: {seconds(start_us)} - {seconds(end_us)} s",
        font=font,
        fill="white",
    )
    for i, (path, time) in enumerate(zip(frame_paths, times, strict=True)):
        with Image.open(path) as original:
            frame = original.convert("RGB")
            frame.thumbnail((cell - 8, 145))
            image.paste(
                frame,
                (margin + i * cell + (cell - frame.width) // 2, 48 + (145 - frame.height) // 2),
            )
        draw.text((margin + i * cell, 202), seconds(time), font=font, fill="#b3bac7")
    left = margin + cell // 2
    right = width - margin - cell // 2

    def x(time: int) -> int:
        return left + (max(start_us, min(end_us, time)) - start_us) * (right - left) // (
            end_us - start_us
        )

    for i, time in enumerate(times):
        draw.line((margin + i * cell + cell // 2, 230, x(time), 244), fill="#6d7788")
    middle = 338
    height = 92
    draw.rectangle((left, 244, right, 432), fill="#242a36")
    draw.line((left, middle, right, middle), fill="#6d7788")
    if samples is not None:
        # Absolute full-scale amplitude; separate windows remain comparable (no peak normalization).
        for position, chunk in enumerate(np.array_split(samples, right - left + 1)):
            if not chunk.size:
                continue
            peak = min(1.0, float(np.max(np.abs(chunk))))
            draw.line(
                (
                    left + position,
                    middle - int(peak * height),
                    left + position,
                    middle + int(peak * height),
                ),
                fill="#62d8bb",
            )
        draw.text(
            (left, 443),
            "PCM envelope: absolute amplitude (-1..1); listening required",
            font=font,
            fill="#b3bac7",
        )
    else:
        draw.text((left, 315), "No audio stream (not a decode failure)", font=font, fill="#ffc777")
    draw.line((x(focus_us), 238, x(focus_us), 580), fill="#ffb454", width=2)
    last = [-9999] * 3
    for word in words:
        begin, end = x(word.start_us), x(word.end_us)
        lane = next((i for i, v in enumerate(last) if begin >= v + 8), None)
        if lane is None:
            continue
        y = 480 + lane * 34
        draw.line((begin, y, end, y), fill="#8caaff", width=3)
        label = word.text.replace("\n", " ")
        draw.text((begin, y + 4), label, font=font, fill="white")
        last[lane] = begin + int(draw.textlength(label, font=font))
    draw.text(
        (margin, 592),
        "Words are source-mapped evidence; full text/timing in report.json",
        font=font,
        fill="#b3bac7",
    )
    image.save(output)
