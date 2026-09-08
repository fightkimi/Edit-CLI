"""Read-only media checks on a user-selected native export, independent of the draft writer."""

from __future__ import annotations

import math
from fractions import Fraction
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from interview_edit.adapters.filesystem import sha256_file
from interview_edit.adapters.media import probe_media
from interview_edit.adapters.process import ProcessRunner, SubprocessRunner
from interview_edit.cutlist.service import load_cutlist
from interview_edit.errors import DependencyError, PreflightError, UsageError
from interview_edit.export.jianying import verify_draft


class OutputCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1"] = "1"
    export_id: str
    video_path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duration_us: int = Field(gt=0, strict=True)
    expected_duration_us: int = Field(gt=0, strict=True)
    tolerance_us: int = Field(gt=0, strict=True)
    width: int
    height: int
    audio_streams: int
    decode_checked: bool
    output_check: Literal["passed"] = "passed"
    native_validation: Literal["not_run"] = "not_run"


def check_output(
    package: Path,
    video: Path,
    *,
    expected_duration_us: int | None = None,
    runner: ProcessRunner | None = None,
) -> OutputCheck:
    manifest = verify_draft(package)
    snapshot = load_cutlist(package / str(manifest.input_snapshot))
    expected = manifest.duration_us if expected_duration_us is None else expected_duration_us
    if expected <= 0:
        raise UsageError(
            "jianying_duration_invalid", "Expected duration must be positive microseconds."
        )
    video = video.expanduser().resolve()
    if not video.is_file():
        raise PreflightError("jianying_output_missing", "The selected output file does not exist.")
    before = sha256_file(video)
    active = runner or SubprocessRunner()
    metadata = probe_media(video, active)
    stream = metadata.video_stream
    if stream is None or (stream.width, stream.height) != (
        snapshot.timeline.width,
        snapshot.timeline.height,
    ):
        raise PreflightError(
            "jianying_output_dimensions", "Output video dimensions differ from the draft canvas."
        )
    tolerance = math.ceil(Fraction(1_000_000, 1) / Fraction(snapshot.timeline.frame_rate))
    if abs(metadata.duration_us - expected) > tolerance:
        raise PreflightError(
            "jianying_output_duration",
            "Output duration differs from the expected edit.",
            details={
                "actualUs": metadata.duration_us,
                "expectedUs": expected,
                "toleranceUs": tolerance,
            },
        )
    if any(r.get("sourceId") for r in manifest.source_map) and not metadata.audio_streams:
        # Only demand audio when the original native package actually contains an audio track.
        import json

        filename = "draft_content.json" if manifest.platform == "windows" else "draft_info.json"
        draft = json.loads((package / filename).read_text(encoding="utf-8"))
        if any(t["type"] == "audio" for t in draft["tracks"]):
            raise PreflightError(
                "jianying_output_audio_missing", "Output is missing the expected audio track."
            )
    decoded = active.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(video),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-f",
            "null",
            "-",
        ],
        timeout_seconds=6 * 60 * 60,
    )
    if decoded.return_code == 127:
        raise DependencyError("ffmpeg_missing", "FFmpeg is required to check the complete output.")
    if decoded.return_code != 0 or decoded.stderr.strip():
        raise PreflightError(
            "jianying_output_decode_failed",
            "The complete output could not be decoded without errors.",
        )
    if sha256_file(video) != before:
        raise PreflightError(
            "jianying_output_changed",
            "Output changed during verification; wait for export to finish.",
        )
    return OutputCheck(
        export_id=manifest.export_id,
        video_path=str(video),
        sha256=before,
        duration_us=metadata.duration_us,
        expected_duration_us=expected,
        tolerance_us=tolerance,
        width=snapshot.timeline.width,
        height=snapshot.timeline.height,
        audio_streams=len(metadata.audio_streams),
        decode_checked=True,
    )
