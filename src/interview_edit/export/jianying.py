from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from interview_edit.adapters.filesystem import sha256_file
from interview_edit.adapters.jianying import DRAFT_PATH, DraftBuilder, Target, template
from interview_edit.config.models import ProjectConfig
from interview_edit.cutlist.validation import validate_cutlist
from interview_edit.errors import PathSafetyError, PreflightError, UsageError
from interview_edit.ingest.service import read_media_index
from interview_edit.models.cutlist import CutList
from interview_edit.models.jianying import DraftFile, JianyingManifest
from interview_edit.project.layout import (
    artifact_path,
    atomic_write_text,
    canonical,
    validate_artifact_path,
)


@dataclass(frozen=True)
class ExportResult:
    draft_path: Path
    manifest: JianyingManifest | None
    dry_run: bool
    resource_bytes: int


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
) -> ExportResult:
    validate_name(name)
    report = validate_cutlist(config, document, cutlist_path=cutlist_path, profile_name="master")
    if not report.ok:
        raise PreflightError(
            "cutlist_validation_failed",
            "Export requires a valid cut-list.",
            details={"issues": [i.model_dump(mode="json") for i in report.issues]},
        )
    index = read_media_index(config, required=True, validate_sources=True)
    assert index is not None
    builder = DraftBuilder(config, document, cutlist_path, index, bundle_media)
    draft, records = builder.build()
    export_id = draft["id"]
    destination = artifact_path(config.artifact_root, "exports", f"{name}-{export_id}")
    cutlist_hash = sha256_file(cutlist_path)
    resources = builder.resources
    resource_bytes = sum(path.stat().st_size for path in resources)
    if dry_run:
        return ExportResult(destination, None, True, resource_bytes if bundle_media else 0)
    if (
        bundle_media
        and shutil.disk_usage(config.artifact_root).free < resource_bytes + 16 * 1024 * 1024
    ):
        raise PreflightError(
            "jianying_disk_space",
            "Not enough free space to bundle source media.",
            details={"requiredBytes": resource_bytes},
        )
    source_hashes = {str(path): sha256_file(path) for path in resources}
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".jianying-", dir=destination.parent))
    try:
        if bundle_media:
            for source, relative in resources.items():
                copy = validate_artifact_path(staging / relative, staging)
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, copy)
                if sha256_file(copy) != source_hashes[str(source)]:
                    raise PreflightError(
                        "jianying_source_changed", "A source changed during packaging."
                    )
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
        )
        atomic_write_text(staging / "export-manifest.json", manifest.model_dump_json(indent=2))
        if sha256_file(cutlist_path) != cutlist_hash or any(
            sha256_file(Path(p)) != h for p, h in source_hashes.items()
        ):
            raise PreflightError(
                "jianying_input_changed", "Inputs changed before draft publication."
            )
        verify_draft(staging)
        if destination.exists():
            raise PathSafetyError("jianying_output_exists", "Draft output already exists.")
        os.rename(staging, destination)
        return ExportResult(destination, manifest, False, resource_bytes if bundle_media else 0)
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
    for filename in filenames:
        if filename not in expected or "draft_meta_info.json" not in expected:
            raise PreflightError(
                "jianying_package_incomplete", "Native draft entry or metadata is missing."
            )
        content = json.loads((root / filename).read_text(encoding="utf-8"))
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
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PreflightError(
            "jianying_native_invalid", "Draft data is malformed or unreadable."
        ) from exc
