from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from interview_edit.adapters.filesystem import quick_fingerprint, sha256_file
from interview_edit.adapters.jianying import DRAFT_PATH, DraftBuilder, Target, template
from interview_edit.adapters.verified_copy import copy_verified
from interview_edit.config.models import ProjectConfig
from interview_edit.cutlist.color import correction_filter
from interview_edit.cutlist.service import parse_cutlist
from interview_edit.cutlist.validation import validate_cutlist
from interview_edit.errors import PathSafetyError, PreflightError, UsageError
from interview_edit.export.jianying_validation import validate_native
from interview_edit.ingest.service import read_media_index
from interview_edit.models.cutlist import CutList
from interview_edit.models.jianying import DraftFile, DraftSource, JianyingManifest
from interview_edit.models.media import MediaIndex
from interview_edit.project.layout import (
    artifact_path,
    atomic_write_text,
    canonical,
    validate_artifact_path,
)
from interview_edit.proxy.service import validate_source_revision


@dataclass(frozen=True)
class ExportResult:
    draft_path: Path
    manifest: JianyingManifest | None
    dry_run: bool
    resource_bytes: int
    cached_resources: int = 0


def byte_progress(
    label: str, callback: Callable[[str], None] | None
) -> Callable[[int, int], None] | None:
    if callback is None:
        return None
    last_percent = -5

    def report(current: int, total: int) -> None:
        nonlocal last_percent
        percent = min(100, current * 100 // max(1, total))
        if percent >= last_percent + 5 or (percent == 100 and last_percent != 100):
            callback(f"{label}: {percent}% ({current}/{total} bytes)")
            last_percent = percent

    return report


def validate_name(name: str) -> None:
    if (
        not name.strip()
        or len(name) > 100
        or name in {".", ".."}
        or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
        or name.endswith((" ", "."))
        or name.split(".")[0].upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *[f"COM{i}" for i in range(1, 10)],
            *[f"LPT{i}" for i in range(1, 10)],
        }
    ):
        raise UsageError(
            "jianying_name_invalid", "Use a portable draft name without path characters."
        )


def export_jianying(
    config: ProjectConfig,
    document: CutList,
    cutlist_path: Path,
    *,
    name: str,
    target: Target = "both",
    bundle_media: bool = True,
    dry_run: bool = False,
    resume: bool = False,
    progress: Callable[[str], None] | None = None,
) -> ExportResult:
    config = config.model_copy(deep=True)
    validate_name(name)
    snapshot = cutlist_path.read_bytes()
    document_snapshot = parse_cutlist(snapshot, cutlist_path)
    if document_snapshot != document:
        raise PreflightError(
            "jianying_cutlist_snapshot_mismatch", "Cut-list changed before export began."
        )
    document = document_snapshot
    if any(
        overlay.kind == "motion"
        for act in document.acts
        for item in act.items
        for overlay in item.overlays
    ):
        raise PreflightError(
            "jianying_motion_unsupported",
            "Motion source assets are regenerable; native motion mapping is not yet verified.",
        )
    if any(correction_filter(v) for v in document.color_policy.by_source.values()):
        raise PreflightError(
            "jianying_color_unsupported",
            "Native color mapping is unverified; reset source corrections before editable export.",
        )
    cutlist_hash = hashlib.sha256(snapshot).hexdigest()
    report = validate_cutlist(config, document, cutlist_path=cutlist_path, profile_name="master")
    if not report.ok:
        raise PreflightError(
            "cutlist_validation_failed",
            "Export requires a valid cut-list.",
            details={"issues": [i.model_dump(mode="json") for i in report.issues]},
        )
    index_path = artifact_path(config.artifact_root, "index", "media-index.json")
    index_snapshot = index_path.read_bytes()
    index = read_media_index(config, required=True, validate_sources=True)
    assert index is not None
    if index != MediaIndex.model_validate_json(index_snapshot):
        raise PreflightError(
            "jianying_input_changed", "Media index changed while capturing export inputs."
        )
    control_paths = [artifact_path(config.artifact_root, "index", "media-index.json")]
    for take in {a.take_id for a in index.assets if a.take_id}:
        report_path = artifact_path(config.artifact_root, "sync", take, "sync.json")
        if report_path.exists():
            control_paths.append(report_path)
    control_hashes = {str(p): sha256_file(p) for p in control_paths}
    control_hashes[str(index_path)] = hashlib.sha256(index_snapshot).hexdigest()
    builder = DraftBuilder(config, document, cutlist_path, index, bundle_media)
    draft, records = builder.build()
    export_id = draft["id"]
    destination = artifact_path(config.artifact_root, "exports", f"{name}-{export_id}")
    resources = builder.resources
    used_assets = [a for a in index.assets if canonical(Path(a.canonical_path)) in resources]
    for asset in used_assets:
        validate_source_revision(asset)
    if any(quick_fingerprint(p) != revision for p, revision in builder.resource_revisions.items()):
        raise PreflightError("jianying_input_changed", "A resource changed during serialization.")
    if sha256_file(cutlist_path) != cutlist_hash:
        raise PreflightError("jianying_input_changed", "Cut-list changed during serialization.")
    resource_bytes = sum(path.stat().st_size for path in resources)
    if dry_run:
        return ExportResult(destination, None, True, resource_bytes if bundle_media else 0)
    required_bytes = resource_bytes * (2 if resume else 1) + 16 * 1024 * 1024
    if bundle_media and shutil.disk_usage(config.artifact_root).free < required_bytes:
        raise PreflightError(
            "jianying_disk_space",
            "Not enough free space to bundle source media.",
            details={"requiredBytes": required_bytes},
        )
    source_hashes = {}
    for position, path in enumerate(resources, 1):
        source_hashes[str(path)] = sha256_file(
            path, progress=byte_progress(f"Checking input {position}/{len(resources)}", progress)
        )
    for asset in used_assets:
        validate_source_revision(asset)
    if any(quick_fingerprint(p) != revision for p, revision in builder.resource_revisions.items()):
        raise PreflightError("jianying_input_changed", "A resource changed while hashing inputs.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".jianying-", dir=destination.parent))
    cached_resources = 0
    try:
        if bundle_media:
            for position, (source, relative) in enumerate(resources.items(), 1):
                copy = validate_artifact_path(staging / relative, staging)
                expected = source_hashes[str(source)]
                selected = source
                if resume:
                    cache = artifact_path(config.artifact_root, "exports", ".media-cache", expected)
                    if cache.is_file() and sha256_file(cache) == expected:
                        cached_resources += 1
                    else:
                        copy_verified(
                            source,
                            cache,
                            expected,
                            byte_progress(
                                f"Caching resource {position}/{len(resources)}", progress
                            ),
                        )
                    selected = cache
                callback = byte_progress(f"Copying resource {position}/{len(resources)}", progress)
                copy_verified(selected, copy, expected, callback)
        now = datetime.now(UTC)
        stamp = int(now.timestamp() * 1_000_000)
        for platform, filename in [("macos", "draft_info.json"), ("windows", "draft_content.json")]:
            if target not in {"both", platform}:
                continue
            content = deepcopy(draft)
            content.update(name=name, create_time=stamp, update_time=stamp)
            for key in ["platform", "last_modified_platform"]:
                content[key]["os"] = "mac" if platform == "macos" else "windows"
                for identity in ["device_id", "hard_disk_id", "mac_address", "os_version"]:
                    content[key][identity] = ""
            atomic_write_text(staging / filename, json.dumps(content, ensure_ascii=False, indent=2))
        meta = template("meta")
        meta.update(
            draft_id=export_id,
            draft_name=name,
            tm_duration=draft["duration"],
            tm_draft_create=stamp,
            tm_draft_modified=stamp,
            draft_timeline_materials_size_=resource_bytes,
            draft_fold_path="",
            draft_root_path="",
        )
        meta["draft_materials"][0]["value"] = records
        atomic_write_text(
            staging / "draft_meta_info.json", json.dumps(meta, ensure_ascii=False, indent=2)
        )
        instructions = (
            "# 剪映可编辑草稿\n\n"
            "视频、主音轨、B-roll 和文字保留在独立轨道。文字仍可编辑，并未烧录进视频。\n\n"
            "本包是实验性草稿协议输出，尚未在你的剪映版本打开验证。\n"
            "Mac 使用 draft_info.json，Windows 使用 draft_content.json。不要手动只导入成片 MP4。\n"
            "在装有剪映的电脑安装本 CLI 后，运行 jianying doctor 查明草稿位置，"
            "关闭剪映，再运行 jianying install --draft PATH。随后打开剪映查看新草稿；"
            "若列表不刷新，退出后重启。若报告损坏，请保留草稿并记录剪映版本。\n\n"
            "剪映中的修改由剪映保存，不会自动同步回原 cut-list；请勿重新导出覆盖它。"
            "最终成片可在剪映里导出，既有 CLI QC 不代表人工修改后的成片已经通过检查。\n"
        )
        if not bundle_media:
            instructions += "\n本包引用本机原素材，移动到另一台电脑可能需要手动重新链接。\n"
        atomic_write_text(staging / "打开草稿说明.md", instructions)
        files = [
            DraftFile(
                relative_path=p.relative_to(staging).as_posix(),
                size=p.stat().st_size,
                sha256=sha256_file(p),
            )
            for p in sorted(staging.rglob("*"))
            if p.is_file()
        ]
        snapshot_path = staging / "input-cutlist.yaml"
        snapshot_path.write_bytes(snapshot)
        files.append(
            DraftFile(relative_path=snapshot_path.name, size=len(snapshot), sha256=cutlist_hash)
        )
        config_hash = hashlib.sha256(
            json.dumps(
                config.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        manifest = JianyingManifest(
            export_id=export_id,
            project_id=config.project_id,
            draft_name=name,
            cutlist_sha256=cutlist_hash,
            platform=target,
            bundled_media=bundle_media,
            duration_us=draft["duration"],
            files=files,
            source_map=builder.source_map,
            source_fingerprints=source_hashes,
            created_at=now.isoformat(),
            input_snapshot="input-cutlist.yaml",
            config_sha256=config_hash,
            control_fingerprints=control_hashes,
            source_assets={
                a.asset_id: DraftSource(
                    source_path=a.canonical_path,
                    resource_path=resources[canonical(Path(a.canonical_path))],
                    duration_us=a.duration_us,
                    sha256=source_hashes[str(canonical(Path(a.canonical_path)))],
                )
                for a in used_assets
            },
            material_sources={
                identifier: asset_id for (asset_id, _), identifier in builder.media_ids.items()
            },
        )
        atomic_write_text(staging / "export-manifest.json", manifest.model_dump_json(indent=2))
        if (
            sha256_file(cutlist_path) != cutlist_hash
            or any(sha256_file(Path(p)) != h for p, h in source_hashes.items())
            or any(sha256_file(Path(p)) != h for p, h in control_hashes.items())
        ):
            raise PreflightError(
                "jianying_input_changed", "Inputs changed before draft publication."
            )
        for asset in used_assets:
            validate_source_revision(asset)
        verify_draft(staging)
        if destination.exists():
            raise PathSafetyError("jianying_output_exists", "Draft output already exists.")
        os.rename(staging, destination)
        return ExportResult(
            destination, manifest, False, resource_bytes if bundle_media else 0, cached_resources
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _verify_draft(path: Path, *, native_root: Path | None = None) -> JianyingManifest:
    if path.is_symlink():
        raise PathSafetyError("jianying_package_symlink", "Draft package cannot be a symlink.")
    root = canonical(path)
    manifest_path = validate_artifact_path(root / "export-manifest.json", root)
    try:
        if manifest_path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("manifest too large")
        manifest = JianyingManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError) as exc:
        raise PreflightError(
            "jianying_manifest_invalid", "Draft export manifest is missing or invalid."
        ) from exc
    expected = set()
    if manifest.schema_version != "2":
        raise PreflightError(
            "jianying_reexport_required",
            "Re-export this legacy experimental package with input snapshots.",
        )
    for record in manifest.files:
        relative = PurePosixPath(record.relative_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in record.relative_path
            or record.relative_path in expected
            or record.relative_path == "export-manifest.json"
        ):
            raise PathSafetyError(
                "jianying_package_path_invalid", "Unsafe or duplicate draft file path."
            )
        file = validate_artifact_path(root / record.relative_path, root)
        expected.add(record.relative_path)
        if (
            not file.is_file()
            or file.stat().st_size != record.size
            or sha256_file(file) != record.sha256
        ):
            raise PreflightError(
                "jianying_package_changed", "Draft package is missing files or has changed."
            )
    actual = {
        p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() or p.is_symlink()
    }
    if actual != expected | {"export-manifest.json"}:
        raise PreflightError("jianying_package_changed", "Draft package contains untracked files.")
    filenames = (
        ["draft_info.json", "draft_content.json"]
        if manifest.platform == "both"
        else ["draft_info.json" if manifest.platform == "macos" else "draft_content.json"]
    )
    require_snapshot = manifest.input_snapshot
    if require_snapshot not in expected:
        raise PreflightError(
            "jianying_snapshot_missing", "Input snapshot is not in the file inventory."
        )
    snapshot_path = validate_artifact_path(root / str(require_snapshot), root)
    if sha256_file(snapshot_path) != manifest.cutlist_sha256:
        raise PreflightError(
            "jianying_snapshot_mismatch", "Input snapshot hash differs from the manifest."
        )
    source_document = parse_cutlist(snapshot_path.read_bytes(), snapshot_path)
    if (
        source_document.project_id != manifest.project_id
        or sum(i.timeline_duration_us for a in source_document.acts for i in a.items)
        != manifest.duration_us
    ):
        raise PreflightError(
            "jianying_snapshot_mismatch", "Input snapshot identity/timing differs."
        )
    meta = json.loads((root / "draft_meta_info.json").read_text(encoding="utf-8"))
    canonical_timeline = None
    for filename in filenames:
        if filename not in expected or "draft_meta_info.json" not in expected:
            raise PreflightError(
                "jianying_package_incomplete", "Native draft entry or metadata is missing."
            )
        content = json.loads((root / filename).read_text(encoding="utf-8"))
        validate_native(content, meta, manifest, source_document)
        timeline = (
            content["tracks"],
            content["materials"],
            content["canvas_config"],
            content["fps"],
        )
        if canonical_timeline is not None and canonical_timeline != timeline:
            raise PreflightError("jianying_platform_diverged", "Mac and Windows timelines differ.")
        canonical_timeline = timeline
        if (
            content.get("id") != manifest.export_id
            or content.get("duration") != manifest.duration_us
        ):
            raise PreflightError(
                "jianying_draft_mismatch", "Native draft identity/timing does not match."
            )
        if manifest.bundled_media:
            allowed_root = (native_root or root).as_posix() + "/"

            def resource_path(value: str, allowed_root: str = allowed_root) -> None:
                if value.startswith(DRAFT_PATH + "/"):
                    relative = value[len(DRAFT_PATH) + 1 :]
                elif value.startswith(allowed_root):
                    relative = value[len(allowed_root) :]
                else:
                    raise PathSafetyError(
                        "jianying_external_resource",
                        "Bundled draft references an external resource.",
                    )
                if not relative.startswith("Resources/") or relative not in expected:
                    raise PathSafetyError(
                        "jianying_external_resource", "Resource is not declared in the package."
                    )

            for category in ("videos", "audios"):
                for material in content["materials"][category]:
                    resource_path(material["path"])
            for material in content["materials"]["texts"]:
                resource_path(material["font_path"])
                rich = json.loads(material["content"])
                for style in rich["styles"]:
                    if style.get("font", {}).get("path"):
                        resource_path(style["font"]["path"])
    return manifest


def verify_draft(path: Path, *, native_root: Path | None = None) -> JianyingManifest:
    try:
        return _verify_draft(path, native_root=native_root)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise PreflightError(
            "jianying_native_invalid", "Draft data is malformed or unreadable."
        ) from exc
