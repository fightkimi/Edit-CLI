from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from interview_edit.adapters.process import ProcessRunner, SubprocessRunner
from interview_edit.config.models import (
    ModelSource,
    ProjectConfig,
    TranscriptionBackend,
)
from interview_edit.errors import PathSafetyError
from interview_edit.exit_codes import ExitCode
from interview_edit.project.layout import canonical, validate_artifact_boundary

CheckStatus = Literal["pass", "warning", "fail"]


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: CheckStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    exit_code: ExitCode | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def ok(self) -> bool:
        return not any(check.status == "fail" for check in self.checks)

    @property
    def status(self) -> str:
        if not self.ok:
            return "failed"
        if any(check.status == "warning" for check in self.checks):
            return "degraded"
        return "ready"

    @property
    def exit_code(self) -> ExitCode:
        failures = [check.exit_code for check in self.checks if check.status == "fail"]
        if ExitCode.PATH_ERROR in failures:
            return ExitCode.PATH_ERROR
        if ExitCode.DEPENDENCY_MISSING in failures:
            return ExitCode.DEPENDENCY_MISSING
        if failures:
            return failures[0] or ExitCode.PREFLIGHT_FAILED
        return ExitCode.SUCCESS

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "checks": [check.as_dict() for check in self.checks]}


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _module_import_probe(name: str, runner: ProcessRunner) -> tuple[bool, str]:
    result = runner.run(
        [sys.executable, "-c", f"import {name}"],
        timeout_seconds=60,
    )
    output = (result.stderr or result.stdout).strip().splitlines()
    return result.return_code == 0, output[-1] if output else ""


def _version_line(executable: str, runner: ProcessRunner) -> tuple[bool, str]:
    result = runner.run([executable, "-version"], timeout_seconds=10)
    first_line = (result.stdout or result.stderr).splitlines()
    return result.return_code == 0, first_line[0] if first_line else "no version output"


def _video_toolbox_probe(ffmpeg: str, runner: ProcessRunner) -> DoctorCheck:
    with tempfile.TemporaryDirectory(prefix="interview-edit-doctor-") as directory:
        output = Path(directory) / "probe.mp4"
        result = runner.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=64x64:r=25:d=0.12",
                "-frames:v",
                "1",
                "-c:v",
                "h264_videotoolbox",
                "-allow_sw",
                "1",
                str(output),
            ],
            timeout_seconds=15,
        )
    if result.return_code == 0:
        return DoctorCheck(
            "video_toolbox",
            "pass",
            "VideoToolbox completed a real H.264 encoding probe.",
        )
    detail = (result.stderr or result.stdout).strip().splitlines()
    return DoctorCheck(
        "video_toolbox",
        "warning",
        "VideoToolbox is listed but failed a real probe; libx264 will be used.",
        {"lastLine": detail[-1] if detail else "unknown failure"},
    )


def _transcription_checks(
    config: ProjectConfig | None,
    runner: ProcessRunner,
    project_root: Path | None,
) -> list[DoctorCheck]:
    mlx_available = _module_available("mlx_whisper")
    faster_available = _module_available("faster_whisper")
    requested = config.transcription.backend if config else TranscriptionBackend.AUTO

    candidates: list[tuple[str, str]] = []
    if requested == TranscriptionBackend.MLX_WHISPER:
        if mlx_available:
            candidates.append(("mlx-whisper", "mlx_whisper"))
    elif requested == TranscriptionBackend.FASTER_WHISPER:
        if faster_available:
            candidates.append(("faster-whisper", "faster_whisper"))
    else:
        if platform.system() == "Darwin" and platform.machine() == "arm64" and mlx_available:
            candidates.append(("mlx-whisper", "mlx_whisper"))
        if faster_available:
            candidates.append(("faster-whisper", "faster_whisper"))

    if not candidates:
        return [
            DoctorCheck(
                "transcription_backend",
                "fail",
                f"Requested transcription backend '{requested.value}' is not installed.",
                {
                    "mlxWhisperInstalled": mlx_available,
                    "fasterWhisperInstalled": faster_available,
                },
                ExitCode.DEPENDENCY_MISSING,
            )
        ]

    checks: list[DoctorCheck] = []
    selected: str | None = None
    failures: dict[str, str] = {}
    for candidate, module_name in candidates:
        import_ok, import_error = _module_import_probe(module_name, runner)
        if import_ok:
            selected = candidate
            break
        failures[candidate] = import_error

    if selected is None:
        return [
            DoctorCheck(
                "transcription_backend",
                "fail",
                "Installed local transcription backends are unusable in this environment.",
                {"requested": requested.value, "failures": failures},
                ExitCode.DEPENDENCY_MISSING,
            )
        ]

    if failures:
        checks.append(
            DoctorCheck(
                "transcription_fallback",
                "warning",
                f"Preferred backend was unusable; selected fallback: {selected}.",
                {"failures": failures, "selected": selected},
            )
        )
    checks.append(
        DoctorCheck(
            "transcription_backend",
            "pass",
            f"Local transcription backend is available: {selected}.",
            {"selected": selected},
        )
    )
    if config is not None:
        transcription = config.transcription
        if transcription.model_source == ModelSource.LOCAL:
            model_path = Path(transcription.model).expanduser()
            if not model_path.is_absolute():
                model_base = project_root or config.artifact_root.parent
                model_path = canonical(model_base / model_path)
            if model_path.exists():
                checks.append(
                    DoctorCheck(
                        "transcription_model",
                        "pass",
                        f"Configured local transcription model exists: {model_path}",
                    )
                )
            else:
                checks.append(
                    DoctorCheck(
                        "transcription_model",
                        "fail",
                        f"Configured local transcription model is missing: {model_path}",
                        {"path": str(model_path)},
                        ExitCode.DEPENDENCY_MISSING,
                    )
                )
        else:
            checks.append(
                DoctorCheck(
                    "transcription_model",
                    "warning",
                    "Registry model availability is not assumed; first download requires approval.",
                    {
                        "model": transcription.model,
                        "downloadPolicy": transcription.download_policy,
                    },
                )
            )
    return checks


def _skill_candidates(project_root: Path | None) -> list[Path]:
    candidates: list[Path] = []
    explicit = os.environ.get("INTERVIEW_EDIT_SKILL_PATH")
    if explicit:
        candidates.append(canonical(Path(explicit)))
    for base in [Path.cwd(), *(Path.cwd().parents)]:
        candidates.append(base / ".agents" / "skills" / "interview-edit" / "SKILL.md")
    source = Path(__file__).resolve()
    for base in source.parents:
        candidates.append(base / ".agents" / "skills" / "interview-edit" / "SKILL.md")
    if project_root is not None:
        candidates.append(
            canonical(project_root) / ".agents" / "skills" / "interview-edit" / "SKILL.md"
        )
    return candidates


def _skill_check(project_root: Path | None) -> DoctorCheck:
    for candidate in _skill_candidates(project_root):
        if candidate.is_file():
            return DoctorCheck(
                "codex_skill",
                "pass",
                f"Project Skill found: {candidate}",
                {"path": str(candidate)},
            )
    return DoctorCheck(
        "codex_skill",
        "warning",
        "Project Skill was not found from the current installation context.",
    )


def _project_checks(config: ProjectConfig) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    try:
        validate_artifact_boundary(config.artifact_root, config.media_roots)
    except PathSafetyError as error:
        checks.append(
            DoctorCheck(
                "path_boundaries",
                "fail",
                error.message,
                error.details,
                ExitCode.PATH_ERROR,
            )
        )
    else:
        checks.append(
            DoctorCheck(
                "path_boundaries",
                "pass",
                "Artifact and media roots do not overlap.",
            )
        )

    for media_root in config.media_roots:
        if not media_root.is_dir() or not os.access(media_root, os.R_OK):
            checks.append(
                DoctorCheck(
                    "media_root",
                    "fail",
                    f"Media root is unavailable or unreadable: {media_root}",
                    {"path": str(media_root)},
                    ExitCode.PATH_ERROR,
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    "media_root",
                    "pass",
                    f"Media root is readable: {media_root}",
                    {"path": str(media_root)},
                )
            )

    artifact_root = config.artifact_root
    writable_target = artifact_root if artifact_root.exists() else artifact_root.parent
    if writable_target.exists() and os.access(writable_target, os.W_OK):
        usage = shutil.disk_usage(writable_target)
        checks.append(
            DoctorCheck(
                "artifact_root",
                "pass",
                f"Artifact root is writable: {artifact_root}",
                {"path": str(artifact_root), "freeBytes": usage.free},
            )
        )
    else:
        checks.append(
            DoctorCheck(
                "artifact_root",
                "fail",
                f"Artifact root is not writable: {artifact_root}",
                {"path": str(artifact_root)},
                ExitCode.PATH_ERROR,
            )
        )
    if not config.fonts:
        checks.append(
            DoctorCheck(
                "fonts",
                "warning",
                "No project fonts are configured; subtitle glyph coverage is not verified.",
            )
        )
    else:
        for font in config.fonts:
            readable = font.is_file() and os.access(font, os.R_OK)
            checks.append(
                DoctorCheck(
                    "font",
                    "pass" if readable else "fail",
                    (
                        f"Font is readable: {font}"
                        if readable
                        else f"Configured font is missing or unreadable: {font}"
                    ),
                    {"path": str(font)},
                    None if readable else ExitCode.PATH_ERROR,
                )
            )
    return checks


def run_doctor(
    config: ProjectConfig | None = None,
    *,
    project_root: Path | None = None,
    runner: ProcessRunner | None = None,
    which: Callable[[str], str | None] = shutil.which,
    probe_hardware: bool = True,
) -> DoctorReport:
    process_runner = runner or SubprocessRunner()
    checks: list[DoctorCheck] = []

    python_ok = sys.version_info >= (3, 11)
    checks.append(
        DoctorCheck(
            "python",
            "pass" if python_ok else "fail",
            f"Python {platform.python_version()} ({platform.machine()}).",
            {"executable": sys.executable},
            None if python_ok else ExitCode.DEPENDENCY_MISSING,
        )
    )
    pillow_ok, pillow_error = _module_import_probe("PIL", process_runner)
    checks.append(
        DoctorCheck(
            "text_rasterizer",
            "pass" if pillow_ok else "fail",
            (
                "Pillow is available for local title and subtitle rasterization."
                if pillow_ok
                else "Pillow is unavailable; titles and subtitles cannot be rendered."
            ),
            {"error": pillow_error} if pillow_error else {},
            None if pillow_ok else ExitCode.DEPENDENCY_MISSING,
        )
    )

    ffmpeg = which("ffmpeg")
    ffprobe = which("ffprobe")
    if ffmpeg is None:
        checks.append(
            DoctorCheck(
                "ffmpeg",
                "fail",
                "FFmpeg was not found on PATH.",
                exit_code=ExitCode.DEPENDENCY_MISSING,
            )
        )
    else:
        ok, version = _version_line(ffmpeg, process_runner)
        checks.append(
            DoctorCheck(
                "ffmpeg",
                "pass" if ok else "fail",
                version,
                {"path": ffmpeg},
                None if ok else ExitCode.DEPENDENCY_MISSING,
            )
        )
        encoders = process_runner.run([ffmpeg, "-hide_banner", "-encoders"], timeout_seconds=15)
        output = f"{encoders.stdout}\n{encoders.stderr}"
        missing = [codec for codec in ("libx264", "aac") if codec not in output]
        checks.append(
            DoctorCheck(
                "required_encoders",
                "fail" if missing else "pass",
                (
                    f"Missing required FFmpeg encoders: {', '.join(missing)}"
                    if missing
                    else "Portable H.264 and AAC encoders are available."
                ),
                {"missing": missing},
                ExitCode.DEPENDENCY_MISSING if missing else None,
            )
        )
        filters = process_runner.run([ffmpeg, "-hide_banner", "-filters"], timeout_seconds=15)
        filter_output = f"{filters.stdout}\n{filters.stderr}"
        missing_filters = [
            name
            for name in (
                "overlay",
                "fade",
                "loudnorm",
                "concat",
                "blackdetect",
                "silencedetect",
                "select",
            )
            if name not in filter_output
        ]
        checks.append(
            DoctorCheck(
                "render_filters",
                "fail" if missing_filters else "pass",
                (
                    f"Missing required FFmpeg filters: {', '.join(missing_filters)}"
                    if missing_filters
                    else "Required render and QC filters are available."
                ),
                {"missing": missing_filters},
                ExitCode.DEPENDENCY_MISSING if missing_filters else None,
            )
        )
        if probe_hardware and "h264_videotoolbox" in output:
            checks.append(_video_toolbox_probe(ffmpeg, process_runner))

    if ffprobe is None:
        checks.append(
            DoctorCheck(
                "ffprobe",
                "fail",
                "FFprobe was not found on PATH.",
                exit_code=ExitCode.DEPENDENCY_MISSING,
            )
        )
    else:
        ok, version = _version_line(ffprobe, process_runner)
        checks.append(
            DoctorCheck(
                "ffprobe",
                "pass" if ok else "fail",
                version,
                {"path": ffprobe},
                None if ok else ExitCode.DEPENDENCY_MISSING,
            )
        )

    checks.extend(_transcription_checks(config, process_runner, project_root))
    if config is not None:
        checks.extend(_project_checks(config))
    checks.append(_skill_check(project_root))
    return DoctorReport(tuple(checks))
