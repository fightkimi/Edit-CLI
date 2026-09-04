from __future__ import annotations

import fnmatch
import hashlib
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import ValidationError

from interview_edit.adapters.filesystem import full_sha256, quick_fingerprint
from interview_edit.adapters.media import probe_media, tool_version
from interview_edit.adapters.process import ProcessRunner, SubprocessRunner
from interview_edit.config.models import ProjectConfig
from interview_edit.errors import PathSafetyError, PreflightError, UsageError
from interview_edit.models.media import (
    CameraMap,
    MediaAsset,
    MediaIndex,
    MediaIndexChanges,
    MediaIndexWarning,
)
from interview_edit.project.layout import (
    atomic_write_text,
    canonical,
    is_within,
    validate_artifact_boundary,
    validate_artifact_path,
    validate_media_roots,
)

DEFAULT_EXTENSIONS = (
    ".aac",
    ".aif",
    ".aiff",
    ".avi",
    ".flac",
    ".m4a",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".wav",
    ".webm",
)
INDEX_FILENAME = "media-index.json"


@dataclass(frozen=True)
class IngestRequest:
    config: ProjectConfig
    media_roots: list[Path] | None = None
    camera_map: Path | None = None
    extensions: list[str] | None = None
    full_hash: bool = False
    resume: bool = False
    force: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class IngestResult:
    index: MediaIndex
    index_path: Path
    dry_run: bool
    resumed: bool


@dataclass(frozen=True)
class _SourceCandidate:
    media_root: Path
    relative_path: Path
    canonical_path: Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def normalize_extensions(values: list[str] | None) -> list[str]:
    if not values:
        return list(DEFAULT_EXTENSIONS)
    normalized: set[str] = set()
    for value in values:
        for candidate in value.split(","):
            extension = candidate.strip().lower()
            if not extension:
                continue
            if not extension.startswith("."):
                extension = f".{extension}"
            if any(character in extension for character in "/\\*?"):
                raise UsageError(
                    "extension_invalid",
                    f"Invalid media extension: {candidate}",
                    details={"value": candidate},
                )
            normalized.add(extension)
    if not normalized:
        raise UsageError("extension_required", "At least one media extension is required.")
    return sorted(normalized)


def _normalized_path(path: Path) -> str:
    return unicodedata.normalize("NFC", path.as_posix())


def compute_asset_id(media_root: Path, relative_path: Path) -> str:
    normalized_root = unicodedata.normalize("NFC", str(canonical(media_root)))
    identity = f"{normalized_root}\0{_normalized_path(relative_path)}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"asset_{digest}"


def _safe_candidates(
    roots: list[Path], artifact_root: Path, extensions: set[str]
) -> tuple[list[_SourceCandidate], list[MediaIndexWarning]]:
    candidates: list[_SourceCandidate] = []
    warnings: list[MediaIndexWarning] = []
    selected_targets: set[Path] = set()

    for root in roots:
        stack: list[tuple[Path, Path]] = [(root, Path())]
        visited_directories: set[Path] = set()
        while stack:
            logical_directory, relative_directory = stack.pop()
            resolved_directory = canonical(logical_directory)
            if resolved_directory in visited_directories:
                continue
            visited_directories.add(resolved_directory)
            try:
                children = sorted(logical_directory.iterdir(), key=lambda item: item.name)
            except OSError as exc:
                raise PathSafetyError(
                    "media_scan_failed",
                    f"Could not read media directory: {logical_directory}",
                    details={"path": str(logical_directory), "reason": str(exc)},
                ) from exc
            for child in reversed(children):
                relative = relative_directory / child.name
                try:
                    target = canonical(child)
                    is_symlink = child.is_symlink()
                    if is_symlink and not is_within(target, root):
                        warnings.append(
                            MediaIndexWarning(
                                code="source_symlink_outside_root",
                                message=(
                                    "Skipped a source symlink whose target is outside "
                                    "its media root."
                                ),
                                details={"path": str(child), "target": str(target)},
                            )
                        )
                        continue
                    if is_within(target, artifact_root):
                        continue
                    if child.is_dir():
                        stack.append((child, relative))
                        continue
                    if not child.is_file() or child.suffix.lower() not in extensions:
                        continue
                except OSError as exc:
                    warnings.append(
                        MediaIndexWarning(
                            code="source_entry_unreadable",
                            message="Skipped an unreadable source entry.",
                            details={"path": str(child), "reason": str(exc)},
                        )
                    )
                    continue
                if target in selected_targets:
                    warnings.append(
                        MediaIndexWarning(
                            code="duplicate_source_target",
                            message="Skipped a path that resolves to an already indexed source.",
                            details={"path": str(child), "target": str(target)},
                        )
                    )
                    continue
                selected_targets.add(target)
                candidates.append(
                    _SourceCandidate(
                        media_root=root,
                        relative_path=relative,
                        canonical_path=target,
                    )
                )
    candidates.sort(key=lambda item: (str(item.media_root), _normalized_path(item.relative_path)))
    return candidates, warnings


def _load_camera_map(path: Path | None) -> CameraMap:
    if path is None:
        return CameraMap()
    resolved = canonical(path)
    if not resolved.is_file():
        raise UsageError(
            "camera_map_not_found",
            f"Camera map was not found: {resolved}",
            details={"path": str(resolved)},
        )
    try:
        raw: object = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise UsageError(
            "camera_map_read_failed",
            f"Could not read camera map: {resolved}",
            details={"path": str(resolved), "reason": str(exc)},
        ) from exc
    try:
        return CameraMap.model_validate(raw or {})
    except ValidationError as exc:
        raise UsageError(
            "camera_map_invalid",
            f"Camera map is invalid: {resolved}",
            details={"path": str(resolved), "errors": exc.errors(include_url=False)},
        ) from exc


def _camera_fields(camera_map: CameraMap, relative_path: Path) -> tuple[str | None, str | None]:
    relative = _normalized_path(relative_path)
    camera_id: str | None = None
    take_id: str | None = None
    for rule in camera_map.rules:
        if fnmatch.fnmatchcase(relative, unicodedata.normalize("NFC", rule.glob)):
            if rule.camera_id is not None:
                camera_id = rule.camera_id
            if rule.take_id is not None:
                take_id = rule.take_id
    return camera_id, take_id


def index_path_for(config: ProjectConfig) -> Path:
    return validate_artifact_path(
        config.artifact_root / "index" / INDEX_FILENAME,
        config.artifact_root,
    )


def read_media_index(
    config: ProjectConfig,
    *,
    required: bool = True,
    validate_sources: bool = True,
) -> MediaIndex | None:
    path = index_path_for(config)
    if not path.exists():
        if required:
            raise PreflightError(
                "media_index_missing",
                "Run `interview-edit ingest` before building proxies.",
                details={"path": str(path)},
            )
        return None
    try:
        index = MediaIndex.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise PreflightError(
            "media_index_invalid",
            f"Existing media index is invalid: {path}",
            details={"path": str(path), "reason": str(exc)},
        ) from exc
    if index.project_id != config.project_id:
        raise PreflightError(
            "media_index_project_mismatch",
            "Media index does not belong to the configured project.",
            details={
                "path": str(path),
                "expectedProjectId": config.project_id,
                "actualProjectId": index.project_id,
            },
        )
    if not validate_sources:
        return index
    indexed_roots = validate_media_roots([Path(value) for value in index.media_roots])
    validate_artifact_boundary(config.artifact_root, indexed_roots)
    roots_by_path = {str(root): root for root in indexed_roots}
    for asset in index.assets:
        root = roots_by_path.get(str(canonical(Path(asset.media_root))))
        relative = Path(asset.relative_path)
        if (
            root is None
            or relative.is_absolute()
            or ".." in relative.parts
            or compute_asset_id(root, relative) != asset.asset_id
            or not is_within(Path(asset.canonical_path), root)
        ):
            raise PreflightError(
                "media_index_path_invalid",
                "Media index contains an asset outside its declared media root.",
                details={"assetId": asset.asset_id, "path": asset.canonical_path},
            )
    return index


def _ensure_source_stable(path: Path, *, size: int, mtime_ns: int) -> None:
    try:
        current = path.stat()
    except OSError as exc:
        raise PathSafetyError(
            "media_read_failed",
            f"Source media became unreadable during ingest: {path}",
            details={"path": str(path), "reason": str(exc)},
        ) from exc
    if current.st_size != size or current.st_mtime_ns != mtime_ns:
        raise PreflightError(
            "media_changed_during_ingest",
            "Source media changed while it was being indexed; retry after copying completes.",
            details={"path": str(path)},
        )


def _asset_from_candidate(
    candidate: _SourceCandidate,
    *,
    camera_map: CameraMap,
    probe_version: str,
    runner: ProcessRunner,
    include_full_hash: bool,
    previous: MediaAsset | None,
    force: bool,
) -> MediaAsset:
    path = candidate.canonical_path
    try:
        stat = path.stat()
        fingerprint = quick_fingerprint(path)
    except OSError as exc:
        raise PathSafetyError(
            "media_read_failed",
            f"Could not read source media: {path}",
            details={"path": str(path), "reason": str(exc)},
        ) from exc
    asset_id = compute_asset_id(candidate.media_root, candidate.relative_path)
    camera_id, take_id = _camera_fields(camera_map, candidate.relative_path)
    same_fast_revision = previous is not None and previous.fingerprint == fingerprint
    full_hash = previous.full_hash if same_fast_revision and previous is not None else None
    if include_full_hash:
        try:
            full_hash = full_sha256(path)
        except OSError as exc:
            raise PathSafetyError(
                "media_read_failed",
                f"Could not hash source media: {path}",
                details={"path": str(path), "reason": str(exc)},
            ) from exc
    can_reuse = (
        previous is not None
        and same_fast_revision
        and previous.probe_version == probe_version
        and (not include_full_hash or previous.full_hash in {None, full_hash})
        and not force
    )
    if can_reuse and previous is not None:
        asset = previous.model_copy(
            update={
                "canonical_path": str(path),
                "media_root": str(candidate.media_root),
                "relative_path": _normalized_path(candidate.relative_path),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "full_hash": full_hash,
                "camera_id": camera_id,
                "take_id": take_id,
            }
        )
    else:
        probe = probe_media(path, runner)
        asset = MediaAsset(
            asset_id=asset_id,
            canonical_path=str(path),
            media_root=str(candidate.media_root),
            relative_path=_normalized_path(candidate.relative_path),
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            fingerprint=fingerprint,
            full_hash=full_hash,
            duration_us=probe.duration_us,
            stream_time_base=probe.stream_time_base,
            start_time_us=probe.start_time_us,
            video_stream=probe.video_stream,
            audio_streams=probe.audio_streams,
            camera_id=camera_id,
            take_id=take_id,
            capture_time=probe.capture_time,
            probe_version=probe_version,
        )
    _ensure_source_stable(path, size=stat.st_size, mtime_ns=stat.st_mtime_ns)
    return asset


def _changes(previous: MediaIndex | None, assets: list[MediaAsset]) -> MediaIndexChanges:
    old = {asset.asset_id: asset for asset in previous.assets} if previous is not None else {}
    current = {asset.asset_id: asset for asset in assets}
    added: list[str] = []
    changed: list[str] = []
    unchanged: list[str] = []
    for asset_id, asset in current.items():
        prior = old.get(asset_id)
        if prior is None:
            added.append(asset_id)
        elif prior.fingerprint != asset.fingerprint or (
            prior.full_hash is not None
            and asset.full_hash is not None
            and prior.full_hash != asset.full_hash
        ):
            changed.append(asset_id)
        else:
            unchanged.append(asset_id)
    return MediaIndexChanges(
        added=sorted(added),
        changed=sorted(changed),
        unchanged=sorted(unchanged),
        removed=sorted(set(old) - set(current)),
    )


def ingest_media(
    request: IngestRequest,
    *,
    runner: ProcessRunner | None = None,
    progress: Callable[[str], None] | None = None,
) -> IngestResult:
    selected_runner = runner or SubprocessRunner()
    if progress is not None:
        progress("Scanning source-media roots...")
    roots = validate_media_roots(request.media_roots or request.config.media_roots)
    validate_artifact_boundary(request.config.artifact_root, roots)
    extensions = normalize_extensions(request.extensions)
    camera_map = _load_camera_map(request.camera_map)
    previous = read_media_index(request.config, required=False, validate_sources=False)
    previous_by_id = (
        {asset.asset_id: asset for asset in previous.assets} if previous is not None else {}
    )
    probe_version = tool_version("ffprobe", selected_runner)
    candidates, warnings = _safe_candidates(roots, request.config.artifact_root, set(extensions))
    if not candidates:
        warnings.append(
            MediaIndexWarning(
                code="no_media_found",
                message="No files matched the selected media extensions.",
                details={"mediaRoots": [str(root) for root in roots]},
            )
        )
    assets: list[MediaAsset] = []
    seen_asset_ids: dict[str, str] = {}
    if progress is not None:
        progress(f"Indexing {len(candidates)} matching source file(s)...")
    for position, candidate in enumerate(candidates, start=1):
        asset_id = compute_asset_id(candidate.media_root, candidate.relative_path)
        previous_path = seen_asset_ids.get(asset_id)
        if previous_path is not None:
            raise PreflightError(
                "asset_id_collision",
                "Two source paths normalize to the same stable asset identity.",
                details={
                    "assetId": asset_id,
                    "firstPath": previous_path,
                    "secondPath": str(candidate.relative_path),
                },
            )
        seen_asset_ids[asset_id] = str(candidate.relative_path)
        if progress is not None:
            progress(f"[{position}/{len(candidates)}] {candidate.relative_path.as_posix()}")
        assets.append(
            _asset_from_candidate(
                candidate,
                camera_map=camera_map,
                probe_version=probe_version,
                runner=selected_runner,
                include_full_hash=request.full_hash,
                previous=previous_by_id.get(asset_id),
                force=request.force,
            )
        )
    assets.sort(key=lambda item: item.asset_id)
    index = MediaIndex(
        project_id=request.config.project_id,
        generated_at=_utc_now(),
        probe_version=probe_version,
        media_roots=[str(root) for root in roots],
        extensions=extensions,
        assets=assets,
        changes=_changes(previous, assets),
        warnings=warnings,
    )
    path = index_path_for(request.config)
    if not request.dry_run:
        atomic_write_text(path, index.model_dump_json(indent=2) + "\n")
    if progress is not None:
        progress("Media index ready." if not request.dry_run else "Media index plan ready.")
    return IngestResult(
        index=index,
        index_path=path,
        dry_run=request.dry_run,
        resumed=request.resume,
    )
