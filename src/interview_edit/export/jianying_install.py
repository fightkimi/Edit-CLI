from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from interview_edit.adapters.filesystem import sha256_file
from interview_edit.adapters.jianying import DRAFT_PATH
from interview_edit.errors import PathSafetyError, PreflightError
from interview_edit.export.jianying import validate_name, verify_draft
from interview_edit.models.jianying import DraftFile
from interview_edit.project.layout import (
    atomic_write_text,
    canonical,
    is_within,
    validate_artifact_path,
)


def _local_paths(value: Any, destination: Path) -> Any:
    if isinstance(value, list):
        return [_local_paths(v, destination) for v in value]
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key in {"path", "font_path", "file_Path", "media_path"} and isinstance(child, str):
                if child.startswith(DRAFT_PATH + "/"):
                    relative = child[len(DRAFT_PATH) + 1 :]
                    result[key] = validate_artifact_path(
                        destination / relative, destination
                    ).as_posix()
                else:
                    result[key] = child
            elif key == "content" and isinstance(child, str):
                result[key] = json.dumps(
                    _local_paths(json.loads(child), destination), ensure_ascii=False
                )
            else:
                result[key] = _local_paths(child, destination)
        return result
    return value


def install_draft(
    package: Path, draft_root: Path, target: Literal["macos", "windows"], *, dry_run: bool = False
) -> Path:
    manifest = verify_draft(package)
    if manifest.platform not in {"both", target}:
        raise PreflightError(
            "jianying_platform_mismatch", "Package has no entry for this platform."
        )
    if not manifest.bundled_media:
        raise PreflightError(
            "jianying_bundle_required", "Bundle media before installing a portable draft."
        )
    validate_name(manifest.draft_name)
    if (
        not draft_root.is_dir()
        or draft_root.is_symlink()
        or canonical(draft_root) != draft_root.absolute()
    ):
        raise PathSafetyError(
            "jianying_draft_root_invalid", "Use the real existing Jianying draft directory."
        )
    root = canonical(draft_root)
    package = canonical(package)
    if is_within(root, package) or is_within(package, root):
        raise PathSafetyError(
            "jianying_install_overlap", "Package and draft library must be separate."
        )
    destination = validate_artifact_path(root / f"{manifest.draft_name}-{manifest.export_id}", root)
    if destination.exists():
        raise PathSafetyError(
            "jianying_draft_exists", "This draft is already installed; existing work is preserved."
        )
    if dry_run:
        return destination
    staging = Path(tempfile.mkdtemp(prefix=".interview-edit-", dir=root))
    try:
        for record in manifest.files:
            source = validate_artifact_path(package / record.relative_path, package)
            copy = validate_artifact_path(staging / record.relative_path, staging)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, copy)
            if sha256_file(copy) != record.sha256:
                raise PreflightError(
                    "jianying_package_changed", "Package changed during installation."
                )
        entry = "draft_info.json" if target == "macos" else "draft_content.json"
        other = "draft_content.json" if target == "macos" else "draft_info.json"
        (staging / other).unlink(missing_ok=True)
        content = _local_paths(
            json.loads((staging / entry).read_text(encoding="utf-8")), destination
        )
        atomic_write_text(staging / entry, json.dumps(content, ensure_ascii=False, indent=2))
        meta = _local_paths(
            json.loads((staging / "draft_meta_info.json").read_text(encoding="utf-8")), destination
        )
        meta.update(draft_fold_path=str(destination), draft_root_path=str(root))
        atomic_write_text(
            staging / "draft_meta_info.json", json.dumps(meta, ensure_ascii=False, indent=2)
        )
        # Each install has a separate receipt; the global app registry is never rewritten.
        atomic_write_text(
            staging / "interview-edit-install.json",
            json.dumps(
                {
                    "installationId": str(uuid4()),
                    "package": str(package),
                    "nativeValidation": "not_run",
                }
            ),
        )
        files = [
            DraftFile(
                relative_path=p.relative_to(staging).as_posix(),
                size=p.stat().st_size,
                sha256=sha256_file(p),
            )
            for p in sorted(staging.rglob("*"))
            if p.is_file()
        ]
        installed = manifest.model_copy(update={"platform": target, "files": files})
        atomic_write_text(staging / "export-manifest.json", installed.model_dump_json(indent=2))
        verify_draft(staging, native_root=destination)
        if destination.exists():
            raise PathSafetyError(
                "jianying_draft_exists", "Draft appeared during installation; no overwrite."
            )
        os.rename(staging, destination)
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging)
