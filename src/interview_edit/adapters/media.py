from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from interview_edit.adapters.process import ProcessRunner
from interview_edit.errors import DependencyError, PreflightError, ProcessingError
from interview_edit.models.media import AudioStream, VideoStream


@dataclass(frozen=True)
class ProbeMetadata:
    duration_us: int
    start_time_us: int | None
    stream_time_base: str | None
    video_stream: VideoStream | None
    audio_streams: list[AudioStream]
    capture_time: str | None


def _microseconds(value: object) -> int | None:
    if value is None or value in {"", "N/A"}:
        return None
    try:
        decimal = Decimal(str(value)) * Decimal(1_000_000)
    except (InvalidOperation, ValueError):
        return None
    return int(decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _optional_int(value: object) -> int | None:
    if value is None or value in {"", "N/A"}:
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def _rotation(stream: dict[str, Any]) -> int | None:
    for item in stream.get("side_data_list", []):
        if isinstance(item, dict) and item.get("rotation") is not None:
            return _optional_int(item["rotation"])
    tags = stream.get("tags")
    if isinstance(tags, dict):
        return _optional_int(tags.get("rotate"))
    return None


def _tags(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse_probe_payload(payload: str) -> ProbeMetadata:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PreflightError(
            "media_probe_invalid_json",
            "FFprobe returned invalid JSON.",
            details={"reason": str(exc)},
        ) from exc
    if not isinstance(document, dict):
        raise PreflightError("media_probe_invalid_json", "FFprobe JSON must be an object.")

    raw_streams = document.get("streams", [])
    if not isinstance(raw_streams, list):
        raw_streams = []
    video: VideoStream | None = None
    audio: list[AudioStream] = []
    capture_time: str | None = None
    for raw in raw_streams:
        if not isinstance(raw, dict):
            continue
        tags = _tags(raw.get("tags"))
        if capture_time is None and isinstance(tags.get("creation_time"), str):
            capture_time = tags["creation_time"]
        if raw.get("codec_type") == "video" and video is None:
            video = VideoStream(
                index=_optional_int(raw.get("index")) or 0,
                codec_name=raw.get("codec_name"),
                width=_optional_int(raw.get("width")),
                height=_optional_int(raw.get("height")),
                pixel_format=raw.get("pix_fmt"),
                color_range=raw.get("color_range"),
                color_space=raw.get("color_space"),
                color_transfer=raw.get("color_transfer"),
                color_primaries=raw.get("color_primaries"),
                field_order=raw.get("field_order"),
                time_base=raw.get("time_base"),
                average_frame_rate=raw.get("avg_frame_rate"),
                real_frame_rate=raw.get("r_frame_rate"),
                start_time_us=_microseconds(raw.get("start_time")),
                duration_us=_microseconds(raw.get("duration")),
                rotation=_rotation(raw),
            )
        elif raw.get("codec_type") == "audio":
            audio.append(
                AudioStream(
                    index=_optional_int(raw.get("index")) or 0,
                    codec_name=raw.get("codec_name"),
                    sample_rate=_optional_int(raw.get("sample_rate")),
                    channels=_optional_int(raw.get("channels")),
                    channel_layout=raw.get("channel_layout"),
                    time_base=raw.get("time_base"),
                    start_time_us=_microseconds(raw.get("start_time")),
                    duration_us=_microseconds(raw.get("duration")),
                )
            )

    if video is None and not audio:
        raise PreflightError("media_stream_missing", "No video or audio stream was found.")
    raw_format = document.get("format")
    media_format = raw_format if isinstance(raw_format, dict) else {}
    format_tags = _tags(media_format.get("tags"))
    if capture_time is None and isinstance(format_tags.get("creation_time"), str):
        capture_time = format_tags["creation_time"]
    durations = [
        candidate
        for candidate in [
            _microseconds(media_format.get("duration")),
            video.duration_us if video is not None else None,
            *(item.duration_us for item in audio),
        ]
        if candidate is not None
    ]
    duration_us = max(durations, default=0)
    start_time_us = _microseconds(media_format.get("start_time"))
    if start_time_us is None:
        starts = [
            value
            for value in [
                video.start_time_us if video is not None else None,
                *(item.start_time_us for item in audio),
            ]
            if value is not None
        ]
        start_time_us = min(starts, default=None)
    stream_time_base = video.time_base if video is not None else audio[0].time_base
    return ProbeMetadata(
        duration_us=duration_us,
        start_time_us=start_time_us,
        stream_time_base=stream_time_base,
        video_stream=video,
        audio_streams=audio,
        capture_time=capture_time,
    )


def tool_version(executable: str, runner: ProcessRunner) -> str:
    result = runner.run([executable, "-version"], timeout_seconds=15)
    if result.return_code == 127:
        raise DependencyError(
            f"{executable}_missing", f"Required executable is unavailable: {executable}."
        )
    if result.return_code != 0:
        raise DependencyError(
            f"{executable}_unusable",
            f"Could not run {executable}.",
            details={"returnCode": result.return_code, "stderr": result.stderr[-2000:]},
        )
    first_line = result.stdout.splitlines()[0].strip() if result.stdout.splitlines() else ""
    if not first_line:
        raise DependencyError(f"{executable}_unusable", f"{executable} returned no version.")
    return first_line


def probe_media(path: Path, runner: ProcessRunner) -> ProbeMetadata:
    result = runner.run(
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
        timeout_seconds=120,
    )
    if result.return_code == 127:
        raise DependencyError("ffprobe_missing", "Required executable is unavailable: ffprobe.")
    if result.return_code != 0:
        raise PreflightError(
            "media_probe_failed",
            f"FFprobe could not read source media: {path}",
            details={
                "path": str(path),
                "returnCode": result.return_code,
                "stderr": result.stderr[-2000:],
            },
        )
    try:
        return parse_probe_payload(result.stdout)
    except PreflightError as exc:
        raise PreflightError(
            "media_probe_failed",
            f"FFprobe metadata is unusable for source media: {path}",
            details={"path": str(path), "reason": exc.message},
        ) from exc


def run_ffmpeg(args: list[str], runner: ProcessRunner, *, source: Path) -> None:
    result = runner.run(["ffmpeg", *args], timeout_seconds=6 * 60 * 60)
    if result.return_code == 127:
        raise DependencyError("ffmpeg_missing", "Required executable is unavailable: ffmpeg.")
    if result.return_code != 0:
        raise ProcessingError(
            "proxy_build_failed",
            f"FFmpeg failed while processing: {source}",
            details={
                "path": str(source),
                "returnCode": result.return_code,
                "stderr": result.stderr[-4000:],
            },
        )
