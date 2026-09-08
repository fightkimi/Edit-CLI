from __future__ import annotations

from pathlib import Path

from interview_edit.adapters.process import ProcessRunner
from interview_edit.config.models import RenderProfile
from interview_edit.errors import DependencyError, ProcessingError
from interview_edit.models.render import RenderCommand


def seconds(microseconds: int) -> str:
    sign = "-" if microseconds < 0 else ""
    absolute = abs(microseconds)
    return f"{sign}{absolute // 1_000_000}.{absolute % 1_000_000:06d}"


def run_render_command(
    args: list[str],
    runner: ProcessRunner,
    *,
    purpose: str,
    timeout_seconds: float = 6 * 60 * 60,
) -> tuple[RenderCommand, str, str]:
    complete = ["ffmpeg", *args]
    result = runner.run(complete, timeout_seconds=timeout_seconds)
    record = RenderCommand(purpose=purpose, args=list(result.args), return_code=result.return_code)
    if result.return_code == 127:
        raise DependencyError("ffmpeg_missing", "Required executable is unavailable: ffmpeg.")
    if result.return_code != 0:
        raise ProcessingError(
            "render_ffmpeg_failed",
            f"FFmpeg failed during {purpose}.",
            details={
                "purpose": purpose,
                "returnCode": result.return_code,
                "stderr": result.stderr[-4000:],
                "args": list(result.args),
            },
        )
    return record, result.stdout, result.stderr


def select_video_encoder(
    profile: RenderProfile, runner: ProcessRunner
) -> tuple[str, RenderCommand | None]:
    if profile.video_codec != "auto":
        return profile.video_codec, None
    args = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=64x64:r=1:d=1",
        "-frames:v",
        "1",
        "-an",
        "-c:v",
        "h264_videotoolbox",
        "-f",
        "null",
        "-",
    ]
    result = runner.run(args, timeout_seconds=30)
    record = RenderCommand(
        purpose="probe VideoToolbox encoder",
        args=list(result.args),
        return_code=result.return_code,
    )
    return ("h264_videotoolbox" if result.return_code == 0 else "libx264"), record


def video_codec_args(profile: RenderProfile, encoder: str) -> list[str]:
    if encoder == "libx264":
        crf = profile.crf if profile.crf is not None else 20
        return ["-c:v", encoder, "-preset", "medium", "-crf", str(crf)]
    if encoder == "h264_videotoolbox":
        quality = max(1, min(100, 82 - (profile.crf if profile.crf is not None else 18)))
        return ["-c:v", encoder, "-q:v", str(quality)]
    result = ["-c:v", encoder]
    if profile.crf is not None:
        result.extend(["-crf", str(profile.crf)])
    return result


def concat_entry(path: Path) -> str:
    escaped = path.as_posix().replace("'", "'\\''")
    return f"file '{escaped}'"
