from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from interview_edit.adapters.artifacts import validated_audio_proxy
from interview_edit.adapters.filesystem import quick_fingerprint, sha256_file
from interview_edit.config.models import ProjectConfig
from interview_edit.errors import InterviewEditError
from interview_edit.ingest.service import read_media_index
from interview_edit.models.media import MediaAsset, MediaIndex, ProxyManifest
from interview_edit.models.operation import OperationRunManifest
from interview_edit.models.qc import QCReport
from interview_edit.models.render import RenderRunManifest
from interview_edit.models.transcript import TranscriptManifest
from interview_edit.project.layout import artifact_path, canonical, is_within
from interview_edit.qc.service import canonical_config_sha256
from interview_edit.sync.service import load_current_sync_report
from interview_edit.version.service import load_version

StageValidity = Literal["missing", "current", "partial", "invalid"]

ARTIFACT_STAGES: dict[str, tuple[str, ...]] = {
    "ingest": ("index",),
    "proxy": ("proxies", "audio", "contact-sheets"),
    "transcribe": ("transcripts",),
    "sync": ("sync",),
    "render": ("renders",),
    "qc": ("qc",),
    "version": ("versions",),
}


@dataclass(frozen=True)
class ProjectStatus:
    project_id: str
    name: str
    privacy_mode: str
    artifact_root: Path
    stages: dict[str, dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "projectId": self.project_id,
            "name": self.name,
            "privacyMode": self.privacy_mode,
            "artifactRoot": str(self.artifact_root),
            "stages": self.stages,
        }


def _file_count(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for candidate in directory.rglob("*") if candidate.is_file())


def _published_renders(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    published: list[Path] = []
    for candidate in directory.rglob("*.mp4"):
        relative = candidate.relative_to(directory)
        if relative.parts and relative.parts[0] not in {"cache", "runs"} and candidate.is_file():
            published.append(candidate)
    return sorted(published)


def _stage_summary(
    paths: list[Path],
    *,
    file_count: int,
    valid_count: int,
    expected_count: int,
    reason_codes: list[str],
) -> dict[str, Any]:
    if file_count == 0:
        validity: StageValidity = "missing"
    elif expected_count > 0 and valid_count == expected_count:
        validity = "current"
    elif valid_count > 0:
        validity = "partial"
    else:
        validity = "invalid"
    return {
        "state": "present" if file_count else "missing",
        "validity": validity,
        "fileCount": file_count,
        "validCount": valid_count,
        "expectedCount": expected_count,
        "reasonCodes": sorted(set(reason_codes)),
        "paths": [str(path) for path in paths],
    }


def _source_is_current(asset: MediaAsset) -> bool:
    """Run the lightweight source check; release gates still enforce optional full hashes."""
    try:
        source = Path(asset.canonical_path)
        stat = source.stat()
        return (
            stat.st_size == asset.size
            and stat.st_mtime_ns == asset.mtime_ns
            and quick_fingerprint(source) == asset.fingerprint
        )
    except OSError:
        return False


def _ingest_status(
    config: ProjectConfig, paths: list[Path]
) -> tuple[dict[str, Any], MediaIndex | None]:
    file_count = sum(_file_count(path) for path in paths)
    if file_count == 0:
        return (
            _stage_summary(
                paths,
                file_count=0,
                valid_count=0,
                expected_count=1,
                reason_codes=[],
            ),
            None,
        )
    try:
        index = read_media_index(config, required=True, validate_sources=True)
        assert index is not None
    except InterviewEditError as error:
        return (
            _stage_summary(
                paths,
                file_count=file_count,
                valid_count=0,
                expected_count=1,
                reason_codes=[error.code],
            ),
            None,
        )
    if not index.assets:
        return (
            _stage_summary(
                paths,
                file_count=file_count,
                valid_count=0,
                expected_count=1,
                reason_codes=["media_index_empty"],
            ),
            index,
        )
    stale = [asset.asset_id for asset in index.assets if not _source_is_current(asset)]
    return (
        _stage_summary(
            paths,
            file_count=file_count,
            valid_count=0 if stale else 1,
            expected_count=1,
            reason_codes=["source_changed_since_ingest"] if stale else [],
        ),
        index,
    )


def _expected_proxy_outputs(config: ProjectConfig, asset: MediaAsset) -> set[tuple[str, Path]]:
    expected: set[tuple[str, Path]] = set()
    if asset.video_stream is not None:
        expected.update(
            {
                ("video", artifact_path(config.artifact_root, "proxies", f"{asset.asset_id}.mp4")),
                (
                    "thumbnail",
                    artifact_path(config.artifact_root, "proxies", f"{asset.asset_id}.jpg"),
                ),
                (
                    "time_map",
                    artifact_path(
                        config.artifact_root, "proxies", f"{asset.asset_id}.time-map.json"
                    ),
                ),
            }
        )
    if asset.audio_streams:
        expected.add(
            ("audio", artifact_path(config.artifact_root, "audio", f"{asset.asset_id}.wav"))
        )
    return expected


def _proxy_manifest_is_valid(config: ProjectConfig, asset: MediaAsset) -> bool:
    path = artifact_path(config.artifact_root, "proxies", f"{asset.asset_id}.manifest.json")
    try:
        manifest = ProxyManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError):
        return False
    if (
        manifest.asset_id != asset.asset_id
        or manifest.source_fingerprint != asset.fingerprint
        or manifest.source_full_hash != asset.full_hash
        or manifest.settings != config.proxy.model_dump(mode="json")
        or not _source_is_current(asset)
    ):
        return False
    expected = _expected_proxy_outputs(config, asset)
    actual = {(output.kind, canonical(Path(output.path))) for output in manifest.outputs}
    if actual != {(kind, canonical(path)) for kind, path in expected}:
        return False
    try:
        return all(
            is_within(canonical(Path(output.path)), config.artifact_root)
            and Path(output.path).is_file()
            and Path(output.path).stat().st_size == output.size
            for output in manifest.outputs
        )
    except OSError:
        return False


def _contact_sheet_manifest_is_valid(config: ProjectConfig, index: MediaIndex) -> bool:
    root = artifact_path(config.artifact_root, "contact-sheets")
    path = root / "manifest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        sheets = payload.get("sheets")
        if (
            payload.get("schema_version") != "1"
            or payload.get("project_id") != config.project_id
            or not isinstance(sheets, list)
        ):
            return False
        expected_assets = {
            asset.asset_id for asset in index.assets if asset.video_stream is not None
        }
        observed_assets: set[str] = set()
        for sheet in sheets:
            if not isinstance(sheet, dict) or not isinstance(sheet.get("cells"), list):
                return False
            sheet_path = canonical(Path(str(sheet.get("path", ""))))
            if not is_within(sheet_path, root) or not sheet_path.is_file():
                return False
            with sheet_path.open("rb") as handle:
                if handle.read(2) != b"\xff\xd8":
                    return False
            for cell in sheet["cells"]:
                if not isinstance(cell, dict) or not isinstance(cell.get("asset_id"), str):
                    return False
                if cell["asset_id"] in observed_assets:
                    return False
                observed_assets.add(cell["asset_id"])
        return observed_assets == expected_assets
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False


def _proxy_status(
    config: ProjectConfig, paths: list[Path], index: MediaIndex | None
) -> dict[str, Any]:
    file_count = sum(_file_count(path) for path in paths)
    if index is None:
        return _stage_summary(
            paths,
            file_count=file_count,
            valid_count=0,
            expected_count=1,
            reason_codes=["media_index_invalid"] if file_count else [],
        )
    asset_valid_count = sum(1 for asset in index.assets if _proxy_manifest_is_valid(config, asset))
    contact_valid = _contact_sheet_manifest_is_valid(config, index)
    expected_count = len(index.assets) + 1
    valid_count = asset_valid_count + int(contact_valid)
    reasons: list[str] = []
    if asset_valid_count != len(index.assets):
        reasons.append("proxy_evidence_invalid")
    if not contact_valid:
        reasons.append("contact_sheet_evidence_invalid")
    return _stage_summary(
        paths,
        file_count=file_count,
        valid_count=valid_count,
        expected_count=expected_count,
        reason_codes=reasons,
    )


def _asset_stage_status(
    paths: list[Path],
    *,
    index: MediaIndex | None,
    validator: Callable[[MediaAsset], bool],
    missing_reason: str,
    select: Callable[[MediaAsset], bool] = lambda asset: True,
) -> dict[str, Any]:
    file_count = sum(_file_count(path) for path in paths)
    if index is None:
        return _stage_summary(
            paths,
            file_count=file_count,
            valid_count=0,
            expected_count=1,
            reason_codes=["media_index_invalid"] if file_count else [],
        )
    selected = [asset for asset in index.assets if select(asset)]
    valid_count = sum(1 for asset in selected if validator(asset))
    reasons = [missing_reason] if valid_count != len(selected) else []
    if not selected:
        reasons = [f"{missing_reason}_not_applicable"] if file_count else []
    return _stage_summary(
        paths,
        file_count=file_count,
        valid_count=valid_count,
        expected_count=max(1, len(selected)),
        reason_codes=reasons,
    )


def _correction_fingerprint(project_root: Path) -> str | None:
    path = project_root / "dictionaries" / "corrections.yaml"
    try:
        raw = path.read_bytes() if path.exists() else b""
    except OSError:
        return None
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _transcript_manifest_is_valid(
    config: ProjectConfig, project_root: Path, asset: MediaAsset
) -> bool:
    root = artifact_path(config.artifact_root, "transcripts", asset.asset_id)
    try:
        manifest = TranscriptManifest.model_validate_json(
            (root / "manifest.json").read_text(encoding="utf-8")
        )
        audio = validated_audio_proxy(config, asset)
    except (InterviewEditError, OSError, UnicodeError, ValidationError):
        return False
    correction_fingerprint = _correction_fingerprint(project_root)
    if (
        manifest.asset_id != asset.asset_id
        or manifest.source_fingerprint != asset.fingerprint
        or manifest.source_full_hash != asset.full_hash
        or manifest.audio_proxy_sha256 != audio.sha256
        or correction_fingerprint is None
        or manifest.correction_fingerprint != correction_fingerprint
    ):
        return False
    expected = {
        "raw_jsonl": root / "raw.jsonl",
        "corrected_jsonl": root / "corrected.jsonl",
        "raw_srt": root / "raw.srt",
        "corrected_srt": root / "corrected.srt",
    }
    if {(output.kind, canonical(Path(output.path))) for output in manifest.outputs} != {
        (kind, canonical(path)) for kind, path in expected.items()
    }:
        return False
    try:
        return all(
            is_within(canonical(Path(output.path)), config.artifact_root)
            and Path(output.path).is_file()
            and Path(output.path).stat().st_size == output.size
            and sha256_file(Path(output.path)) == output.sha256
            for output in manifest.outputs
        )
    except OSError:
        return False


def _sync_status(
    config: ProjectConfig, paths: list[Path], index: MediaIndex | None
) -> dict[str, Any]:
    file_count = sum(_file_count(path) for path in paths)
    reports = sorted(paths[0].glob("*/sync.json")) if paths[0].is_dir() else []
    reasons: list[str] = []
    valid_count = 0
    if index is None and reports:
        reasons.append("media_index_invalid")
    elif index is not None:
        for report in reports:
            try:
                load_current_sync_report(config, index, report.parent.name)
            except InterviewEditError as error:
                reasons.append(error.code)
            else:
                valid_count += 1
    return _stage_summary(
        paths,
        file_count=file_count,
        valid_count=valid_count,
        expected_count=max(1, len(reports)),
        reason_codes=reasons,
    )


def _render_manifest_output(config: ProjectConfig, path: Path) -> Path | None:
    try:
        manifest = RenderRunManifest.model_validate_json(path.read_text(encoding="utf-8"))
        if (
            manifest.project_id != config.project_id
            or manifest.state != "succeeded"
            or manifest.completed_at is None
            or manifest.output is None
            or manifest.config_sha256 != canonical_config_sha256(config)
        ):
            return None
        cutlist = canonical(Path(manifest.cutlist_path))
        output = canonical(Path(manifest.output.path))
        valid = (
            cutlist.is_file()
            and sha256_file(cutlist) == manifest.cutlist_sha256
            and is_within(output, artifact_path(config.artifact_root, "renders"))
            and output.is_file()
            and output.stat().st_size == manifest.output.size
        )
        return output if valid else None
    except (OSError, UnicodeError, ValidationError):
        return None


def _render_status(config: ProjectConfig, paths: list[Path]) -> dict[str, Any]:
    published = _published_renders(paths[0])
    run_root = artifact_path(config.artifact_root, "renders", "runs")
    runs = sorted(run_root.glob("render_*.json")) if run_root.is_dir() else []
    valid_outputs = {
        output for path in runs if (output := _render_manifest_output(config, path)) is not None
    }
    valid_count = len(valid_outputs.intersection(map(canonical, published)))
    return _stage_summary(
        paths,
        file_count=len(published),
        valid_count=min(valid_count, len(published)),
        expected_count=max(1, len(published)),
        reason_codes=["successful_render_required"] if published and valid_count == 0 else [],
    )


def _qc_report_is_current(config: ProjectConfig, path: Path) -> tuple[bool, str | None]:
    try:
        report = QCReport.model_validate_json(path.read_text(encoding="utf-8"))
        checksum = path.with_name("report.sha256").read_text(encoding="utf-8").strip()
        render_manifest = canonical(Path(report.render_manifest_path))
        cutlist = canonical(Path(report.cutlist_path))
        output = canonical(Path(report.output_path)) if report.output_path is not None else None
        evidence_valid = all(
            is_within(canonical(Path(item.path)), path.parent)
            and Path(item.path).is_file()
            and Path(item.path).stat().st_size == item.size
            and sha256_file(Path(item.path)) == item.sha256
            for item in report.evidence
        )
        current = (
            checksum == sha256_file(path)
            and report.project_id == config.project_id
            and report.state == "passed"
            and report.completed_at is not None
            and report.config_sha256 == canonical_config_sha256(config)
            and render_manifest.is_file()
            and sha256_file(render_manifest) == report.render_manifest_sha256
            and cutlist.is_file()
            and sha256_file(cutlist) == report.cutlist_sha256
            and output is not None
            and is_within(output, artifact_path(config.artifact_root, "renders"))
            and output.is_file()
            and output.stat().st_size == report.output_size
            and evidence_valid
        )
        return current, None if current else "qc_evidence_stale"
    except (OSError, UnicodeError, ValidationError):
        return False, "qc_report_invalid"


def _qc_status(config: ProjectConfig, paths: list[Path]) -> dict[str, Any]:
    file_count = sum(_file_count(path) for path in paths)
    reports = sorted(paths[0].glob("qc_*/report.json")) if paths[0].is_dir() else []
    results = [_qc_report_is_current(config, report) for report in reports]
    valid_count = sum(1 for valid, _ in results if valid)
    reasons = [reason for valid, reason in results if not valid and reason is not None]
    return _stage_summary(
        paths,
        file_count=file_count,
        valid_count=valid_count,
        expected_count=max(1, len(reports)),
        reason_codes=reasons,
    )


def _version_status(config: ProjectConfig, paths: list[Path]) -> dict[str, Any]:
    file_count = sum(_file_count(path) for path in paths)
    roots = (
        sorted(path for path in paths[0].glob("v[0-9][0-9][0-9][0-9]") if path.is_dir())
        if paths[0].is_dir()
        else []
    )
    valid_count = 0
    reasons: list[str] = []
    for root in roots:
        try:
            manifest, loaded_root = load_version(config, root.name)
            manifest_path = loaded_root / "version.json"
            checksum_path = loaded_root / "version.sha256"
            expected_manifest_hash = checksum_path.read_text(encoding="utf-8").strip()
            declared: set[str] = set()
            payload_valid = expected_manifest_hash == sha256_file(manifest_path)
            for item in manifest.files:
                relative = Path(item.relative_path)
                candidate = loaded_root / relative
                valid_relative = (
                    not relative.is_absolute()
                    and ".." not in relative.parts
                    and item.relative_path not in declared
                )
                declared.add(item.relative_path)
                current = loaded_root
                contains_symlink = False
                for part in relative.parts:
                    current /= part
                    if current.is_symlink():
                        contains_symlink = True
                        break
                payload_valid = payload_valid and (
                    valid_relative
                    and not contains_symlink
                    and is_within(canonical(candidate), loaded_root)
                    and candidate.is_file()
                    and candidate.stat().st_size == item.size
                )
            actual = {
                path.relative_to(loaded_root).as_posix()
                for path in loaded_root.rglob("*")
                if (path.is_file() or path.is_symlink())
                and path.relative_to(loaded_root).as_posix()
                not in {"version.json", "version.sha256"}
            }
            payload_valid = payload_valid and actual == declared
        except InterviewEditError as error:
            reasons.append(error.code)
            continue
        except (OSError, UnicodeError):
            reasons.append("version_control_evidence_invalid")
            continue
        if payload_valid:
            valid_count += 1
        else:
            reasons.append("version_control_evidence_invalid")
    return _stage_summary(
        paths,
        file_count=file_count,
        valid_count=valid_count,
        expected_count=max(1, len(roots)),
        reason_codes=reasons,
    )


def _latest_operation_runs(config: ProjectConfig) -> dict[str, dict[str, Any]]:
    root = artifact_path(config.artifact_root, "logs")
    if not root.is_dir():
        return {}
    stage_for_command = {
        "proxy_build": "proxy",
        "transcribe": "transcribe",
        "sync": "sync",
    }
    latest: dict[str, tuple[str, str, OperationRunManifest, Path]] = {}
    for path in root.glob("*.json"):
        try:
            manifest = OperationRunManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError):
            continue
        if manifest.project_id != config.project_id or path.stem != manifest.run_id:
            continue
        stage = stage_for_command[manifest.command]
        key = (manifest.started_at, manifest.run_id)
        current = latest.get(stage)
        if current is None or key > current[:2]:
            latest[stage] = (manifest.started_at, manifest.run_id, manifest, path)
    result: dict[str, dict[str, Any]] = {}
    for stage, (_, _, manifest, path) in latest.items():
        result[stage] = {
            "runId": manifest.run_id,
            "state": manifest.state,
            "expectedCount": len(manifest.progress.expected_items),
            "completedCount": len(manifest.progress.completed_items),
            "cachedCount": len(manifest.progress.cached_items),
            "skippedCount": len(manifest.progress.skipped_items),
            "errorCode": manifest.error.code if manifest.error is not None else None,
            "startedAt": manifest.started_at,
            "completedAt": manifest.completed_at,
            "manifestPath": str(path),
        }
    return result


def read_project_status(
    config: ProjectConfig, *, project_root: Path | None = None
) -> ProjectStatus:
    paths = {
        stage: [artifact_path(config.artifact_root, directory) for directory in directories]
        for stage, directories in ARTIFACT_STAGES.items()
    }
    ingest, index = _ingest_status(config, paths["ingest"])
    root = canonical(project_root or config.artifact_root.parent)
    proxy = _proxy_status(config, paths["proxy"], index)
    transcribe = _asset_stage_status(
        paths["transcribe"],
        index=index,
        validator=lambda asset: _transcript_manifest_is_valid(config, root, asset),
        missing_reason="transcript_evidence_invalid",
        select=lambda asset: bool(asset.audio_streams),
    )
    stages = {
        "ingest": ingest,
        "proxy": proxy,
        "transcribe": transcribe,
        "sync": _sync_status(config, paths["sync"], index),
        "render": _render_status(config, paths["render"]),
        "qc": _qc_status(config, paths["qc"]),
        "version": _version_status(config, paths["version"]),
    }
    for stage, latest_run in _latest_operation_runs(config).items():
        stages[stage]["latestRun"] = latest_run
    return ProjectStatus(
        project_id=config.project_id,
        name=config.name,
        privacy_mode=config.privacy_mode.value,
        artifact_root=config.artifact_root,
        stages=stages,
    )
