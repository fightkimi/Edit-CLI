"""Input-bound native export jobs; completion means media checks, not GUI acceptance."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Literal
from uuid import uuid4

from interview_edit.adapters.filesystem import sha256_file
from interview_edit.adapters.jianying_app import inspect_jianying
from interview_edit.adapters.native_capabilities import legacy_supported
from interview_edit.adapters.process import ProcessRunner, SubprocessRunner
from interview_edit.adapters.verified_copy import copy_verified
from interview_edit.config.models import ProjectConfig
from interview_edit.cutlist.service import load_cutlist
from interview_edit.errors import (
    DependencyError,
    InterviewEditError,
    PathSafetyError,
    PreflightError,
    UsageError,
)
from interview_edit.export.jianying import verify_draft
from interview_edit.export.jianying_output import check_output
from interview_edit.models.native_export import NativeExportJob
from interview_edit.project.layout import (
    artifact_path,
    atomic_write_text,
    canonical,
    validate_artifact_path,
)


def installed_snapshot(package_id: str, installed: Path) -> tuple[str, str]:
    entry = installed / "draft_content.json"
    if entry.is_symlink() or not entry.is_file() or entry.stat().st_size > 32 * 1024 * 1024:
        raise PreflightError(
            "jianying_installed_invalid", "Select a readable legacy installed draft."
        )
    try:
        value = json.loads(entry.read_text(encoding="utf-8"))
        if value["id"] != package_id or not isinstance(value.get("name"), str) or not value["name"]:
            raise ValueError("identity")
        name = value["name"]
        content = {
            key: value[key] for key in ("tracks", "materials", "duration", "canvas_config", "fps")
        }
    except (ValueError, KeyError, TypeError) as exc:
        raise PreflightError(
            "jianying_installed_invalid", "Installed draft identity or content differs."
        ) from exc
    import hashlib

    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return name, digest


def save_job(root: Path, job: NativeExportJob) -> None:
    atomic_write_text(root / "job.json", job.model_dump_json(indent=2))


def load_job(config: ProjectConfig, job_id: str) -> tuple[Path, NativeExportJob]:
    if not re.fullmatch(r"native_[a-f0-9]{32}", job_id):
        raise UsageError("jianying_job_id_invalid", "Use a native export job ID.")
    root = artifact_path(config.artifact_root, "native-exports", job_id)
    control = validate_artifact_path(root / "job.json", config.artifact_root)
    try:
        if control.stat().st_size > 1024 * 1024:
            raise ValueError("size")
        job = NativeExportJob.model_validate_json(control.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PreflightError("jianying_job_invalid", "Export job is missing or invalid.") from exc
    if job.job_id != job_id or job.project_id != config.project_id:
        raise PreflightError("jianying_job_invalid", "Export job belongs to another project.")
    receipt = validate_artifact_path(root / "result/receipt.json", config.artifact_root)
    if receipt.is_file():
        try:
            if receipt.stat().st_size > 1024 * 1024:
                raise ValueError("size")
            completed = NativeExportJob.model_validate_json(receipt.read_text(encoding="utf-8"))
            fields = {"state", "output_sha256", "output_check_sha256", "error_code"}
            if completed.state != "succeeded" or completed.model_dump(
                exclude=fields
            ) != job.model_dump(exclude=fields):
                raise ValueError("receipt")
            job = completed
        except (ValueError, OSError) as exc:
            raise PreflightError(
                "jianying_job_invalid", "Completed receipt differs from its request."
            ) from exc
    if job.state == "succeeded":
        video = validate_artifact_path(root / "result/video.mp4", config.artifact_root)
        check = validate_artifact_path(root / "result/output-check.json", config.artifact_root)
        if (
            not receipt.is_file()
            or not video.is_file()
            or not check.is_file()
            or sha256_file(video) != job.output_sha256
            or sha256_file(check) != job.output_check_sha256
        ):
            raise PreflightError(
                "jianying_job_output_changed", "Completed export evidence changed."
            )
    package = Path(job.package_path)
    manifest = verify_draft(package)
    if (
        manifest.export_id != job.export_id
        or sha256_file(package / "export-manifest.json") != job.package_sha256
    ):
        raise PreflightError(
            "jianying_job_input_changed", "Original package changed after job creation."
        )
    return root, job


@contextmanager
def operation(root: Path) -> Iterator[None]:
    lock = root / ".operation.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise PreflightError("jianying_job_busy", "Another process owns this export job.") from exc
    os.close(fd)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def create_job(
    config: ProjectConfig,
    package: Path,
    *,
    backend: Literal["manual", "windows-legacy"] = "manual",
    installed: Path | None = None,
    expected_duration_us: int | None = None,
    dry_run: bool = False,
) -> tuple[Path, NativeExportJob]:
    if backend not in {"manual", "windows-legacy"}:
        raise UsageError("jianying_backend_invalid", "Select a supported export backend.")
    package = canonical(package)
    manifest = verify_draft(package)
    if manifest.project_id != config.project_id:
        raise PreflightError("jianying_project_mismatch", "Package belongs to another project.")
    installed_hash = None
    if backend == "windows-legacy":
        client = inspect_jianying()
        if not legacy_supported(client):
            raise DependencyError(
                "jianying_automation_unsupported",
                "This driver requires Windows Jianying 5.x or 6.x.",
            )
        if installed is None:
            raise UsageError(
                "jianying_installed_required", "Select the installed draft before automation."
            )
        installed = canonical(installed)
        if not client.get("draftRoot") or installed.parent != canonical(Path(client["draftRoot"])):
            raise PreflightError(
                "jianying_library_mismatch", "Select a draft in the detected active library."
            )
        _, installed_hash = installed_snapshot(manifest.export_id, installed)
        timeline = load_cutlist(package / str(manifest.input_snapshot)).timeline
        if timeline.height not in {480, 720, 1080} or Fraction(timeline.frame_rate) not in {
            24,
            25,
            30,
            50,
            60,
        }:
            raise UsageError(
                "jianying_export_preset_unsupported",
                "Legacy presets support 480/720/1080p and integer 24/25/30/50/60fps.",
            )
    duration = manifest.duration_us if expected_duration_us is None else expected_duration_us
    if type(duration) is not int or duration <= 0:
        raise UsageError(
            "jianying_duration_invalid", "Expected duration must be positive microseconds."
        )
    job = NativeExportJob(
        job_id=f"native_{uuid4().hex}",
        project_id=config.project_id,
        export_id=manifest.export_id,
        package_path=str(package),
        package_sha256=sha256_file(package / "export-manifest.json"),
        installed_draft=str(installed) if installed else None,
        installed_sha256=installed_hash,
        backend=backend,
        expected_duration_us=duration,
        created_at=datetime.now(UTC).isoformat(),
    )
    root = artifact_path(config.artifact_root, "native-exports", job.job_id)
    if not dry_run:
        root.mkdir(parents=True, exist_ok=False)
        save_job(root, job)
    return root, job


def finish_job(
    config: ProjectConfig, job_id: str, video: Path, *, runner: ProcessRunner | None = None
) -> tuple[Path, NativeExportJob]:
    root, _ = load_job(config, job_id)
    with operation(root):
        _, job = load_job(config, job_id)
        return _finish_locked(config, root, job, video, runner=runner)


def _finish_locked(
    config: ProjectConfig,
    root: Path,
    job: NativeExportJob,
    video: Path,
    *,
    runner: ProcessRunner | None = None,
) -> tuple[Path, NativeExportJob]:
    result = validate_artifact_path(root / "result", config.artifact_root)
    output = validate_artifact_path(result / "video.mp4", config.artifact_root)
    if job.state == "succeeded":
        if not output.is_file() or sha256_file(output) != job.output_sha256:
            raise PreflightError("jianying_job_output_changed", "Completed export was modified.")
        return root, job
    if result.exists():
        raise PathSafetyError(
            "jianying_output_exists", "Existing output is preserved; create a new job."
        )
    stage = Path(tempfile.mkdtemp(prefix=".publish-", dir=root))
    try:
        _check_installed(job)
        rate = load_cutlist(Path(job.package_path) / "input-cutlist.yaml").timeline.frame_rate
        checked = check_output(
            Path(job.package_path),
            video,
            expected_duration_us=job.expected_duration_us,
            expected_frame_rate=rate,
            runner=runner,
        )
        copy_verified(canonical(video), stage / "video.mp4", checked.sha256)
        load_job(config, job.job_id)
        check_output(
            Path(job.package_path),
            stage / "video.mp4",
            expected_duration_us=job.expected_duration_us,
            expected_frame_rate=rate,
            runner=runner,
        )
        _check_installed(job)
        checked.video_path = str(output)
        atomic_write_text(stage / "output-check.json", checked.model_dump_json(indent=2))
        completed = job.model_copy(
            update={
                "state": "succeeded",
                "output_sha256": checked.sha256,
                "output_check_sha256": sha256_file(stage / "output-check.json"),
                "error_code": None,
            }
        )
        atomic_write_text(stage / "receipt.json", completed.model_dump_json(indent=2))
        os.rename(stage, result)
        # The directory transaction is the completion record; status recovers if this convenience
        # update is interrupted after the result has been atomically published.
        save_job(root, completed)
        return root, completed
    except InterviewEditError as exc:
        job.state = "failed"
        job.error_code = exc.code
        save_job(root, job)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _check_installed(job: NativeExportJob) -> None:
    if job.backend == "windows-legacy":
        assert job.installed_draft is not None
        if installed_snapshot(job.export_id, Path(job.installed_draft))[1] != job.installed_sha256:
            raise PreflightError(
                "jianying_job_input_changed", "Installed timeline changed; create a new job."
            )


def run_legacy_job(
    config: ProjectConfig,
    job_id: str,
    *,
    approved: bool = False,
    timeout_seconds: int = 1200,
    runner: ProcessRunner | None = None,
) -> tuple[Path, NativeExportJob]:
    if not approved:
        raise UsageError(
            "jianying_export_approval_required",
            "Native rendering requires explicit --approve for this job.",
        )
    if not 30 <= timeout_seconds <= 3600:
        raise UsageError(
            "jianying_export_timeout_invalid", "Export timeout must be 30–3600 seconds."
        )
    root, job = load_job(config, job_id)
    client = inspect_jianying()
    if job.backend != "windows-legacy" or not legacy_supported(client):
        raise DependencyError(
            "jianying_automation_unsupported",
            "Automatic execution requires the legacy Windows backend.",
        )
    assert job.installed_draft is not None
    installed = Path(job.installed_draft)
    if not client.get("draftRoot") or installed.parent != canonical(Path(client["draftRoot"])):
        raise PreflightError(
            "jianying_library_mismatch", "Detected library changed; create a new job."
        )
    name, digest = installed_snapshot(job.export_id, installed)
    if digest != job.installed_sha256:
        raise PreflightError(
            "jianying_job_input_changed", "Installed timeline changed; create a new approved job."
        )
    # Name-based legacy controllers must not select an ambiguous project.
    for sibling in installed.parent.iterdir():
        if sibling != installed and sibling.is_dir():
            meta = sibling / "draft_meta_info.json"
            if meta.is_file():
                try:
                    value = json.loads(meta.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    raise PreflightError(
                        "jianying_automation_ambiguous",
                        "Could not rule out another draft with the same name.",
                    ) from None
                if value.get("draft_name") == name:
                    raise PreflightError(
                        "jianying_automation_ambiguous",
                        "Multiple drafts share this name; choose unique names.",
                    )
    with operation(root):
        _, job = load_job(config, job_id)
        incoming = validate_artifact_path(root / "incoming.mp4", config.artifact_root)
        if incoming.exists() or job.state == "succeeded":
            raise PathSafetyError(
                "jianying_output_exists",
                "Existing native output is preserved; finish it or create a new job.",
            )
        job.state = "running"
        save_job(root, job)
        timeline = load_cutlist(Path(job.package_path) / "input-cutlist.yaml").timeline
        result = (runner or SubprocessRunner()).run(
            [
                sys.executable,
                "-m",
                "interview_edit.adapters.jianying_legacy_worker",
                "--name",
                name,
                "--output",
                str(incoming),
                "--height",
                str(timeline.height),
                "--fps",
                str(int(Fraction(timeline.frame_rate))),
                "--timeout",
                str(timeout_seconds),
            ],
            timeout_seconds=timeout_seconds + 15,
        )
        try:
            unchanged = installed_snapshot(job.export_id, installed)[1] == digest
        except InterviewEditError:
            unchanged = False
        if result.return_code != 0 or not unchanged:
            job.state = "failed"
            job.error_code = {
                4: "jianying_driver_dependency_missing",
                5: "jianying_driver_requires_home",
                6: "jianying_driver_output_path_blocked",
            }.get(result.return_code, "jianying_driver_failed")
            save_job(root, job)
            raise PreflightError(
                job.error_code,
                "Native driver failed, timed out or input changed; partial output is retained.",
            )
        return _finish_locked(config, root, job, incoming)
