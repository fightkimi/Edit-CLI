from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from interview_edit.adapters.filesystem import sha256_file
from interview_edit.config.loader import serialize_project_config
from interview_edit.config.models import ProjectConfig
from interview_edit.errors import PathSafetyError, PreflightError, UsageError
from interview_edit.models.qc import QCFindingSeverity, QCPolicy, QCReport
from interview_edit.models.render import RenderRunManifest
from interview_edit.models.version import (
    FrozenFile,
    FrozenFileRole,
    VersionManifest,
    VersionSummary,
    VersionVerification,
    VersionVerificationIssue,
)
from interview_edit.project.layout import atomic_write_text, canonical, is_within
from interview_edit.qc.service import canonical_config_sha256, load_render_run

_VERSION_ID = re.compile(r"^v[0-9]{4}$")


@dataclass(frozen=True)
class FreezeRequest:
    config: ProjectConfig
    project_root: Path
    run_id: str
    approved: bool
    note: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class FreezeResult:
    manifest: VersionManifest
    version_path: Path
    dry_run: bool


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _versions_root(config: ProjectConfig) -> Path:
    return config.artifact_root / "versions"


def _version_path(config: ProjectConfig, version_id: str) -> Path:
    if _VERSION_ID.fullmatch(version_id) is None:
        raise UsageError(
            "version_id_invalid",
            "Version ID must use the vNNNN format.",
            details={"versionId": version_id},
        )
    return _versions_root(config) / version_id


def _next_version_id(config: ProjectConfig) -> str:
    root = _versions_root(config)
    if not root.is_dir():
        return "v0001"
    values = [
        int(path.name[1:])
        for path in root.iterdir()
        if path.is_dir() and _VERSION_ID.fullmatch(path.name) is not None
    ]
    return f"v{max(values, default=0) + 1:04d}"


def load_version(config: ProjectConfig, version_id: str) -> tuple[VersionManifest, Path]:
    root = _version_path(config, version_id)
    if root.is_symlink() or not is_within(canonical(root), _versions_root(config)):
        raise PathSafetyError(
            "version_path_invalid",
            "Frozen version path is a symlink or escapes the version root.",
            details={"path": str(root)},
        )
    manifest_path = root / "version.json"
    try:
        manifest = VersionManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PreflightError(
            "version_missing",
            f"Frozen version does not exist: {version_id}",
            details={"path": str(root)},
        ) from exc
    except (OSError, UnicodeError, ValidationError) as exc:
        raise PreflightError(
            "version_manifest_invalid",
            f"Frozen version manifest is invalid: {version_id}",
            details={"path": str(manifest_path), "reason": str(exc)},
        ) from exc
    if manifest.version_id != version_id or manifest.project_id != config.project_id:
        raise PreflightError(
            "version_project_mismatch",
            "Frozen version does not belong to this project.",
            details={"versionId": version_id},
        )
    return manifest, root


def _load_release_reports(config: ProjectConfig, run_id: str) -> list[tuple[QCReport, Path]]:
    reports: list[tuple[QCReport, Path]] = []
    for path in (config.artifact_root / "qc").glob("qc_*/report.json"):
        try:
            report = QCReport.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError):
            continue
        if (
            report.project_id == config.project_id
            and report.run_id == run_id
            and report.policy is QCPolicy.RELEASE
            and report.state == "passed"
            and report.completed_at is not None
        ):
            reports.append((report, path))
    return sorted(
        reports,
        key=lambda value: (value[0].completed_at or "", value[0].report_id),
        reverse=True,
    )


def _validate_release_report(
    config: ProjectConfig,
    manifest: RenderRunManifest,
    run_path: Path,
    report: QCReport,
    report_path: Path,
) -> None:
    checksum_path = report_path.with_name("report.sha256")
    try:
        expected_report_hash = checksum_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise PreflightError(
            "release_qc_checksum_missing",
            "Release QC report checksum is missing or unreadable.",
            details={"path": str(checksum_path)},
        ) from exc
    actual_report_hash = sha256_file(report_path)
    if expected_report_hash != actual_report_hash:
        raise PreflightError(
            "release_qc_modified",
            "Release QC report no longer matches its detached checksum.",
            details={"path": str(report_path)},
        )
    if any(
        finding.severity in {QCFindingSeverity.ERROR, QCFindingSeverity.BLOCKING}
        for finding in report.findings
    ):
        raise PreflightError(
            "release_qc_invalid",
            "Passing release QC contains an error or blocking finding.",
            details={"path": str(report_path)},
        )
    output = manifest.output
    if output is None:
        raise PreflightError("successful_master_required", "Master render has no output evidence.")
    mismatched = (
        report.render_manifest_sha256 != sha256_file(run_path)
        or report.config_sha256 != manifest.config_sha256
        or report.cutlist_sha256 != manifest.cutlist_sha256
        or report.output_sha256 != output.sha256
        or report.output_size != output.size
        or report.profile != manifest.profile
    )
    if mismatched:
        raise PreflightError(
            "release_qc_stale",
            "Release QC does not match the current render evidence.",
            details={"path": str(report_path)},
        )
    report_root = report_path.parent
    for item in report.evidence:
        evidence_path = canonical(Path(item.path))
        if (
            not is_within(evidence_path, report_root)
            or not evidence_path.is_file()
            or evidence_path.stat().st_size != item.size
            or sha256_file(evidence_path) != item.sha256
        ):
            raise PreflightError(
                "release_qc_evidence_invalid",
                "Release QC evidence is missing, moved, or modified.",
                details={"path": str(evidence_path)},
            )


def _release_report(
    config: ProjectConfig, manifest: RenderRunManifest, run_path: Path
) -> tuple[QCReport, Path]:
    reports = _load_release_reports(config, manifest.run_id)
    if not reports:
        raise PreflightError(
            "release_qc_required",
            "A current passing release QC report is required before freeze.",
            details={"runId": manifest.run_id},
        )
    report, path = reports[0]
    _validate_release_report(config, manifest, run_path, report, path)
    return report, path


def _validate_freeze_inputs(
    request: FreezeRequest,
) -> tuple[RenderRunManifest, Path, QCReport, Path, Path, Path]:
    manifest, run_path = load_render_run(request.config, request.run_id)
    if manifest.state != "succeeded" or manifest.output is None or manifest.completed_at is None:
        raise PreflightError(
            "successful_master_required",
            "Freeze requires a completed successful master render.",
            details={"runId": request.run_id},
        )
    if manifest.profile != "master":
        raise PreflightError(
            "successful_master_required",
            "Freeze requires a render produced with the master profile.",
            details={"runId": request.run_id, "profile": manifest.profile},
        )
    if canonical_config_sha256(request.config) != manifest.config_sha256:
        raise PreflightError(
            "master_config_stale",
            "Project configuration changed after the master render.",
        )
    cutlist_path = canonical(Path(manifest.cutlist_path))
    if not cutlist_path.is_file() or sha256_file(cutlist_path) != manifest.cutlist_sha256:
        raise PreflightError(
            "master_cutlist_stale",
            "Cut-list is missing or changed after the master render.",
            details={"path": str(cutlist_path)},
        )
    output_path = canonical(Path(manifest.output.path))
    if (
        not is_within(output_path, request.config.artifact_root / "renders")
        or not output_path.is_file()
        or output_path.stat().st_size != manifest.output.size
        or sha256_file(output_path) != manifest.output.sha256
    ):
        raise PreflightError(
            "master_output_invalid",
            "Master output is missing, outside the render root, or modified.",
            details={"path": str(output_path)},
        )
    report, report_path = _release_report(request.config, manifest, run_path)
    return manifest, run_path, report, report_path, cutlist_path, output_path


def _copy_frozen_file(
    source: Path, staging: Path, relative: Path, role: FrozenFileRole
) -> FrozenFile:
    target = staging / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return FrozenFile(
        role=role,
        relative_path=relative.as_posix(),
        size=target.stat().st_size,
        sha256=sha256_file(target),
    )


def _write_frozen_text(
    content: str, staging: Path, relative: Path, role: FrozenFileRole
) -> FrozenFile:
    target = staging / relative
    atomic_write_text(target, content)
    return FrozenFile(
        role=role,
        relative_path=relative.as_posix(),
        size=target.stat().st_size,
        sha256=sha256_file(target),
    )


def freeze_version(request: FreezeRequest) -> FreezeResult:
    if not request.approved and not request.dry_run:
        raise UsageError(
            "freeze_approval_required",
            "Freeze requires a separate explicit --approve flag.",
        )
    manifest, run_path, report, report_path, cutlist_path, output_path = _validate_freeze_inputs(
        request
    )
    version_id = _next_version_id(request.config)
    final = _version_path(request.config, version_id)
    note = request.note.strip() if request.note and request.note.strip() else None
    planned = VersionManifest(
        version_id=version_id,
        project_id=request.config.project_id,
        note=note,
        source_run_id=manifest.run_id,
        source_report_id=report.report_id,
        source_render_manifest_sha256=sha256_file(run_path),
        source_qc_report_sha256=sha256_file(report_path),
        output_sha256=manifest.output.sha256 if manifest.output is not None else "0" * 64,
        files=[],
        created_at=_utc_now(),
    )
    if request.dry_run:
        return FreezeResult(manifest=planned, version_path=final, dry_run=True)

    staging = _versions_root(request.config) / f".{version_id}.{uuid.uuid4().hex}.tmp"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        release_qc_root = Path("evidence/release-qc")
        files = [
            _copy_frozen_file(output_path, staging, Path("output") / output_path.name, "output"),
            _copy_frozen_file(run_path, staging, Path("evidence/render-run.json"), "render_run"),
            _copy_frozen_file(
                report_path,
                staging,
                release_qc_root / "report.json",
                "release_qc",
            ),
            _copy_frozen_file(
                report_path.with_name("report.sha256"),
                staging,
                release_qc_root / "report.sha256",
                "qc_checksum",
            ),
            _write_frozen_text(
                serialize_project_config(request.config),
                staging,
                Path("inputs/effective-config.yaml"),
                "config",
            ),
            _copy_frozen_file(cutlist_path, staging, Path("inputs/cutlist.yaml"), "cutlist"),
        ]
        for evidence in report.evidence:
            evidence_path = canonical(Path(evidence.path))
            evidence_relative = evidence_path.relative_to(report_path.parent)
            files.append(
                _copy_frozen_file(
                    evidence_path,
                    staging,
                    release_qc_root / evidence_relative,
                    "qc_evidence",
                )
            )
        frozen = planned.model_copy(update={"files": files})
        version_manifest_path = staging / "version.json"
        atomic_write_text(version_manifest_path, frozen.model_dump_json(indent=2) + "\n")
        atomic_write_text(staging / "version.sha256", sha256_file(version_manifest_path) + "\n")
        try:
            staging.rename(final)
        except OSError as exc:
            raise PathSafetyError(
                "version_publish_failed",
                "Could not publish the frozen version atomically.",
                details={"path": str(final), "reason": str(exc)},
            ) from exc
        return FreezeResult(manifest=frozen, version_path=final, dry_run=False)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def list_versions(config: ProjectConfig) -> list[VersionSummary]:
    summaries: list[VersionSummary] = []
    for path in sorted(_versions_root(config).glob("v[0-9][0-9][0-9][0-9]")):
        manifest, _ = load_version(config, path.name)
        summaries.append(
            VersionSummary(
                version_id=manifest.version_id,
                created_at=manifest.created_at,
                source_run_id=manifest.source_run_id,
                source_report_id=manifest.source_report_id,
                note=manifest.note,
                output_sha256=manifest.output_sha256,
            )
        )
    return summaries


def verify_version(config: ProjectConfig, version_id: str) -> VersionVerification:
    manifest, root = load_version(config, version_id)
    issues: list[VersionVerificationIssue] = []
    manifest_path = root / "version.json"
    checksum_path = root / "version.sha256"
    if manifest_path.is_symlink() or checksum_path.is_symlink():
        issues.append(
            VersionVerificationIssue(
                code="version_metadata_symlink",
                message="Version manifest and checksum must be regular files, not symlinks.",
            )
        )
    try:
        expected_manifest_hash = checksum_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        expected_manifest_hash = ""
    if expected_manifest_hash != sha256_file(manifest_path):
        issues.append(
            VersionVerificationIssue(
                code="version_manifest_modified",
                message="Version manifest does not match its detached checksum.",
                relative_path="version.json",
            )
        )
    declared: set[str] = set()
    for item in manifest.files:
        relative = Path(item.relative_path)
        if relative.is_absolute() or ".." in relative.parts or item.relative_path in declared:
            issues.append(
                VersionVerificationIssue(
                    code="frozen_path_invalid",
                    message="Frozen manifest contains an invalid or duplicate relative path.",
                    relative_path=item.relative_path,
                )
            )
            continue
        declared.add(item.relative_path)
        candidate = root / relative
        path = canonical(candidate)
        current = root
        contains_symlink = False
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                contains_symlink = True
                break
        if contains_symlink:
            issues.append(
                VersionVerificationIssue(
                    code="frozen_file_symlink",
                    message="A declared frozen path contains a symlink.",
                    relative_path=item.relative_path,
                )
            )
        elif not is_within(path, root) or not candidate.is_file():
            issues.append(
                VersionVerificationIssue(
                    code="frozen_file_missing",
                    message="A declared frozen file is missing or not a regular file.",
                    relative_path=item.relative_path,
                )
            )
        elif path.stat().st_size != item.size or sha256_file(path) != item.sha256:
            issues.append(
                VersionVerificationIssue(
                    code="frozen_file_modified",
                    message="A frozen file no longer matches its recorded size or checksum.",
                    relative_path=item.relative_path,
                )
            )
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if (path.is_file() or path.is_symlink())
        and path.relative_to(root).as_posix() not in {"version.json", "version.sha256"}
    }
    for unexpected in sorted(actual - declared):
        issues.append(
            VersionVerificationIssue(
                code="frozen_file_unexpected",
                message="Frozen version contains an undeclared file.",
                relative_path=unexpected,
            )
        )
    return VersionVerification(
        version_id=version_id,
        state="failed" if issues else "passed",
        checked_file_count=len(declared),
        issues=issues,
    )
