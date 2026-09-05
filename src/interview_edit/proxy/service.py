from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from interview_edit.adapters.filesystem import full_sha256, quick_fingerprint, sha256_file
from interview_edit.adapters.media import probe_media, run_ffmpeg, tool_version
from interview_edit.adapters.process import ProcessRunner, SubprocessRunner
from interview_edit.config.models import ProjectConfig
from interview_edit.errors import PathSafetyError, PreflightError, UsageError
from interview_edit.models.media import (
    MediaAsset,
    MediaIndex,
    ProxyManifest,
    ProxyOutput,
    ProxyOutputKind,
    TimeMap,
)
from interview_edit.operation.service import OperationRecorder, fail_operation, start_operation
from interview_edit.project.layout import artifact_path, atomic_write_text

_PROXY_SCHEMA = "proxy-v1"


@dataclass(frozen=True)
class ProxyRequest:
    config: ProjectConfig
    index: MediaIndex
    asset_ids: list[str] | None = None
    resume: bool = False
    force: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class ProxyResult:
    built: list[str]
    cached: list[str]
    planned: list[str]
    skipped: list[str]
    artifacts: list[Path]
    contact_sheet_manifest: Path
    dry_run: bool
    resumed: bool
    run_id: str | None
    run_manifest_path: Path | None


@dataclass(frozen=True)
class _Paths:
    video: Path
    audio: Path
    thumbnail: Path
    time_map: Path
    manifest: Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    return sha256_file(path)


def validate_source_revision(asset: MediaAsset) -> None:
    source = Path(asset.canonical_path)
    try:
        stat = source.stat()
        matches = (
            stat.st_size == asset.size
            and stat.st_mtime_ns == asset.mtime_ns
            and quick_fingerprint(source) == asset.fingerprint
            and (asset.full_hash is None or full_sha256(source) == asset.full_hash)
        )
    except OSError as exc:
        raise PreflightError(
            "source_unavailable_since_ingest",
            f"Indexed source media is no longer readable: {source}",
            details={"assetId": asset.asset_id, "path": str(source), "reason": str(exc)},
        ) from exc
    if not matches:
        raise PreflightError(
            "source_changed_since_ingest",
            "Source media changed after the current index was written; run ingest again.",
            details={"assetId": asset.asset_id, "path": str(source)},
        )


def _cache_key(
    asset: MediaAsset,
    *,
    ffmpeg_version: str,
    ffprobe_version: str,
    settings: dict[str, Any],
) -> str:
    payload = {
        "schema": _PROXY_SCHEMA,
        "asset_id": asset.asset_id,
        "source_fingerprint": asset.fingerprint,
        "source_full_hash": asset.full_hash,
        "ffmpeg_version": ffmpeg_version,
        "ffprobe_version": ffprobe_version,
        "settings": settings,
        "has_video": asset.video_stream is not None,
        "has_audio": bool(asset.audio_streams),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _paths(config: ProjectConfig, asset: MediaAsset) -> _Paths:
    proxy_root = artifact_path(config.artifact_root, "proxies")
    return _Paths(
        video=proxy_root / f"{asset.asset_id}.mp4",
        audio=artifact_path(config.artifact_root, "audio", f"{asset.asset_id}.wav"),
        thumbnail=proxy_root / f"{asset.asset_id}.jpg",
        time_map=proxy_root / f"{asset.asset_id}.time-map.json",
        manifest=proxy_root / f"{asset.asset_id}.manifest.json",
    )


def _expected_paths(asset: MediaAsset, paths: _Paths) -> list[tuple[ProxyOutputKind, Path]]:
    expected: list[tuple[ProxyOutputKind, Path]] = []
    if asset.video_stream is not None:
        expected.extend(
            [
                ("video", paths.video),
                ("thumbnail", paths.thumbnail),
                ("time_map", paths.time_map),
            ]
        )
    if asset.audio_streams:
        expected.append(("audio", paths.audio))
    return expected


def _read_valid_manifest(
    path: Path,
    cache_key: str,
    expected: list[tuple[ProxyOutputKind, Path]],
) -> ProxyManifest | None:
    try:
        manifest = ProxyManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError):
        return None
    if manifest.cache_key != cache_key:
        return None
    actual_outputs = {(output.kind, output.path) for output in manifest.outputs}
    expected_outputs = {(kind, str(output_path)) for kind, output_path in expected}
    if actual_outputs != expected_outputs:
        return None
    for output in manifest.outputs:
        candidate = Path(output.path)
        try:
            if not candidate.is_file() or candidate.stat().st_size != output.size:
                return None
            if _sha256(candidate) != output.sha256:
                return None
        except OSError:
            return None
    return manifest


def _temporary_path(final_path: Path) -> Path:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=final_path.parent,
        prefix=f".{final_path.stem}.",
        suffix=f".tmp{final_path.suffix}",
    )
    os.close(descriptor)
    return Path(name)


def _write_temporary_text(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _video_args(asset: MediaAsset, output: Path, settings: dict[str, Any]) -> list[str]:
    max_width = settings["max_width"]
    args = [
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        asset.canonical_path,
        "-map",
        "0:v:0",
    ]
    if asset.audio_streams:
        args.extend(["-map", "0:a:0", "-c:a", "aac", "-b:a", "96k"])
    else:
        args.append("-an")
    args.extend(
        [
            "-vf",
            f"scale=w='trunc(min({max_width},iw)/2)*2':h=-2:force_original_aspect_ratio=decrease,setsar=1,format=yuv420p",
            "-c:v",
            str(settings["video_codec"]),
            "-preset",
            str(settings["preset"]),
            "-crf",
            str(settings["crf"]),
            "-fps_mode",
            "passthrough",
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    return args


def _audio_args(asset: MediaAsset, output: Path, settings: dict[str, Any]) -> list[str]:
    return [
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        asset.canonical_path,
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        str(settings["audio_channels"]),
        "-ar",
        str(settings["audio_sample_rate"]),
        "-c:a",
        "pcm_s16le",
        str(output),
    ]


def _thumbnail_args(asset: MediaAsset, output: Path, settings: dict[str, Any]) -> list[str]:
    seek_seconds = max(0.0, asset.duration_us / 2_000_000)
    return [
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{seek_seconds:.6f}",
        "-i",
        asset.canonical_path,
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
        "-vf",
        f"scale=w={settings['thumbnail_width']}:h=-2:force_original_aspect_ratio=decrease",
        "-q:v",
        "3",
        "-f",
        "image2",
        str(output),
    ]


def _build_one(
    asset: MediaAsset,
    *,
    config: ProjectConfig,
    runner: ProcessRunner,
    ffmpeg_version: str,
    ffprobe_version: str,
    settings: dict[str, Any],
) -> list[Path]:
    paths = _paths(config, asset)
    temporary: dict[str, Path] = {}
    try:
        if asset.video_stream is not None:
            temporary["video"] = _temporary_path(paths.video)
            temporary["thumbnail"] = _temporary_path(paths.thumbnail)
            temporary["time_map"] = _temporary_path(paths.time_map)
            run_ffmpeg(
                _video_args(asset, temporary["video"], settings),
                runner,
                source=Path(asset.canonical_path),
            )
            run_ffmpeg(
                _thumbnail_args(asset, temporary["thumbnail"], settings),
                runner,
                source=Path(asset.canonical_path),
            )
            proxy_probe = probe_media(temporary["video"], runner)
            time_map = TimeMap(
                asset_id=asset.asset_id,
                source_start_us=asset.start_time_us or 0,
                source_duration_us=asset.duration_us,
                proxy_start_us=proxy_probe.start_time_us or 0,
                proxy_duration_us=proxy_probe.duration_us,
                source_time_base=asset.stream_time_base,
                proxy_time_base=proxy_probe.stream_time_base,
            )
            _write_temporary_text(temporary["time_map"], time_map.model_dump_json(indent=2) + "\n")
        if asset.audio_streams:
            temporary["audio"] = _temporary_path(paths.audio)
            run_ffmpeg(
                _audio_args(asset, temporary["audio"], settings),
                runner,
                source=Path(asset.canonical_path),
            )

        outputs: list[ProxyOutput] = []
        final_by_kind = dict(_expected_paths(asset, paths))
        for kind, final_path in _expected_paths(asset, paths):
            temporary_path = temporary[kind]
            size = temporary_path.stat().st_size
            if size == 0:
                raise PathSafetyError(
                    "proxy_output_empty",
                    f"Generated proxy artifact is empty: {final_path}",
                    details={"path": str(final_path)},
                )
            outputs.append(
                ProxyOutput(
                    kind=kind,
                    path=str(final_path),
                    size=size,
                    sha256=_sha256(temporary_path),
                )
            )

        manifest = ProxyManifest(
            asset_id=asset.asset_id,
            source_fingerprint=asset.fingerprint,
            source_full_hash=asset.full_hash,
            cache_key=_cache_key(
                asset,
                ffmpeg_version=ffmpeg_version,
                ffprobe_version=ffprobe_version,
                settings=settings,
            ),
            ffmpeg_version=ffmpeg_version,
            ffprobe_version=ffprobe_version,
            settings=settings,
            outputs=outputs,
            completed_at=_utc_now(),
        )
        temporary["manifest"] = _temporary_path(paths.manifest)
        _write_temporary_text(temporary["manifest"], manifest.model_dump_json(indent=2) + "\n")
        for kind, _final_path in _expected_paths(asset, paths):
            os.replace(temporary.pop(kind), final_by_kind[kind])
        os.replace(temporary.pop("manifest"), paths.manifest)
        return [*final_by_kind.values(), paths.manifest]
    except OSError as exc:
        raise PathSafetyError(
            "proxy_write_failed",
            f"Could not commit proxy artifacts for {asset.asset_id}.",
            details={"assetId": asset.asset_id, "reason": str(exc)},
        ) from exc
    finally:
        for path in temporary.values():
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _contact_sheet_args(
    items: list[tuple[MediaAsset, Path]],
    *,
    columns: int,
    output: Path,
) -> list[str]:
    tile_width = 320
    image_height = 180
    rows = (len(items) + columns - 1) // columns
    width = columns * tile_width
    height = max(1, rows) * image_height
    args = ["-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    for _, thumbnail in items:
        args.extend(["-i", str(thumbnail)])
    filters = [
        (
            f"[{index}:v]scale={tile_width}:{image_height}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={tile_width}:{image_height}:(ow-iw)/2:(oh-ih)/2:color=0x121212,"
            "drawbox=x=0:y=0:w=iw:h=ih:color=0xf4d67a@0.8:t=2"
            f"[v{index}]"
        )
        for index in range(len(items))
    ]
    if len(items) == 1:
        filters.append(f"[v0]pad={width}:{height}:0:0:color=0x121212[out]")
    else:
        inputs = "".join(f"[v{index}]" for index in range(len(items)))
        layout = "|".join(
            f"{index % columns * tile_width}_{index // columns * image_height}"
            for index in range(len(items))
        )
        filters.append(f"{inputs}xstack=inputs={len(items)}:layout={layout}:fill=0x121212[stack]")
        filters.append(f"[stack]pad={width}:{height}:0:0:color=0x121212[out]")
    args.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-frames:v",
            "1",
            "-q:v",
            "3",
            "-f",
            "image2",
            str(output),
        ]
    )
    return args


def _build_contact_sheets(
    config: ProjectConfig,
    index: MediaIndex,
    *,
    runner: ProcessRunner,
    ffmpeg_version: str,
    ffprobe_version: str,
    settings: dict[str, Any],
) -> tuple[Path, list[Path]]:
    root = artifact_path(config.artifact_root, "contact-sheets")
    try:
        root.mkdir(parents=True, exist_ok=True)
        available: list[tuple[MediaAsset, Path]] = []
        for asset in index.assets:
            if asset.video_stream is None:
                continue
            paths = _paths(config, asset)
            expected = _expected_paths(asset, paths)
            cache_key = _cache_key(
                asset,
                ffmpeg_version=ffmpeg_version,
                ffprobe_version=ffprobe_version,
                settings=settings,
            )
            if _read_valid_manifest(paths.manifest, cache_key, expected) is not None:
                available.append((asset, paths.thumbnail))
        page_size = config.proxy.contact_sheet_columns * config.proxy.contact_sheet_rows
        sheet_entries: list[dict[str, Any]] = []
        sheet_paths: list[Path] = []
        for offset in range(0, len(available), page_size):
            page = available[offset : offset + page_size]
            page_identity = "\0".join(
                f"{asset.asset_id}:{asset.relative_path}:{asset.fingerprint}" for asset, _ in page
            )
            page_digest = hashlib.sha256(page_identity.encode("utf-8")).hexdigest()[:12]
            sheet_path = root / f"sheet-{offset // page_size + 1:03d}-{page_digest}.jpg"
            temporary = _temporary_path(sheet_path)
            try:
                run_ffmpeg(
                    _contact_sheet_args(
                        page,
                        columns=config.proxy.contact_sheet_columns,
                        output=temporary,
                    ),
                    runner,
                    source=page[0][1],
                )
                if temporary.stat().st_size == 0:
                    raise PathSafetyError(
                        "contact_sheet_empty",
                        f"Generated contact sheet is empty: {sheet_path}",
                        details={"path": str(sheet_path)},
                    )
                os.replace(temporary, sheet_path)
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            sheet_paths.append(sheet_path)
            sheet_entries.append(
                {
                    "path": str(sheet_path),
                    "cells": [
                        {
                            "asset_id": asset.asset_id,
                            "relative_path": asset.relative_path,
                            "row": cell_index // config.proxy.contact_sheet_columns,
                            "column": cell_index % config.proxy.contact_sheet_columns,
                        }
                        for cell_index, (asset, _) in enumerate(page)
                    ],
                }
            )
        manifest_path = root / "manifest.json"
        contact_manifest = {
            "schema_version": "1",
            "project_id": config.project_id,
            "sheets": sheet_entries,
        }
        atomic_write_text(
            manifest_path,
            json.dumps(contact_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        return manifest_path, sheet_paths
    except OSError as exc:
        raise PathSafetyError(
            "contact_sheet_write_failed",
            "Could not build contact-sheet artifacts.",
            details={"path": str(root), "reason": str(exc)},
        ) from exc


def _selected_asset_ids(request: ProxyRequest) -> list[str]:
    indexed = {asset.asset_id: asset for asset in request.index.assets}
    if request.asset_ids:
        unknown = sorted(set(request.asset_ids) - set(indexed))
        if unknown:
            raise UsageError(
                "asset_unknown",
                "One or more requested assets are not present in the media index.",
                details={"assetIds": unknown},
            )
        return sorted(set(request.asset_ids))
    return sorted(indexed)


def _build_selected_proxies(
    request: ProxyRequest,
    *,
    selected_ids: list[str],
    operation: OperationRecorder | None,
    runner: ProcessRunner | None = None,
    progress: Callable[[str], None] | None = None,
) -> ProxyResult:
    selected_runner = runner or SubprocessRunner()
    ffmpeg_version = tool_version("ffmpeg", selected_runner)
    ffprobe_version = tool_version("ffprobe", selected_runner)
    if operation is not None:
        operation.checkpoint(tools={"ffmpeg": ffmpeg_version, "ffprobe": ffprobe_version})
    settings = request.config.proxy.model_dump(mode="json")
    indexed = {asset.asset_id: asset for asset in request.index.assets}
    if progress is not None:
        progress(f"Preparing {len(selected_ids)} indexed asset(s) for proxy build...")

    built: list[str] = []
    cached: list[str] = []
    planned: list[str] = []
    skipped: list[str] = []
    artifacts: list[Path] = []
    for position, asset_id in enumerate(selected_ids, start=1):
        asset = indexed[asset_id]
        validate_source_revision(asset)
        if asset.video_stream is None and not asset.audio_streams:
            skipped.append(asset_id)
            if operation is not None:
                operation.checkpoint(
                    completed_items=built,
                    cached_items=cached,
                    skipped_items=skipped,
                    artifacts=artifacts,
                )
            continue
        paths = _paths(request.config, asset)
        expected = _expected_paths(asset, paths)
        cache_key = _cache_key(
            asset,
            ffmpeg_version=ffmpeg_version,
            ffprobe_version=ffprobe_version,
            settings=settings,
        )
        if (
            not request.force
            and _read_valid_manifest(paths.manifest, cache_key, expected) is not None
        ):
            if progress is not None:
                progress(f"[{position}/{len(selected_ids)}] cache hit: {asset.relative_path}")
            cached.append(asset_id)
            artifacts.extend([path for _, path in _expected_paths(asset, paths)])
            artifacts.append(paths.manifest)
            if operation is not None:
                operation.checkpoint(
                    completed_items=built,
                    cached_items=cached,
                    skipped_items=skipped,
                    artifacts=artifacts,
                )
            continue
        if request.dry_run:
            if progress is not None:
                progress(f"[{position}/{len(selected_ids)}] planned: {asset.relative_path}")
            planned.append(asset_id)
            continue
        if progress is not None:
            progress(f"[{position}/{len(selected_ids)}] building: {asset.relative_path}")
        artifacts.extend(
            _build_one(
                asset,
                config=request.config,
                runner=selected_runner,
                ffmpeg_version=ffmpeg_version,
                ffprobe_version=ffprobe_version,
                settings=settings,
            )
        )
        built.append(asset_id)
        if operation is not None:
            operation.checkpoint(
                completed_items=built,
                cached_items=cached,
                skipped_items=skipped,
                artifacts=artifacts,
            )

    contact_manifest = artifact_path(
        request.config.artifact_root, "contact-sheets", "manifest.json"
    )
    if not request.dry_run:
        if progress is not None:
            progress("Updating contact sheets...")
        contact_manifest, sheets = _build_contact_sheets(
            request.config,
            request.index,
            runner=selected_runner,
            ffmpeg_version=ffmpeg_version,
            ffprobe_version=ffprobe_version,
            settings=settings,
        )
        artifacts.extend([contact_manifest, *sheets])
    if progress is not None:
        progress("Proxy stage ready." if not request.dry_run else "Proxy plan ready.")
    if operation is not None:
        operation.finish(artifacts=artifacts)
    return ProxyResult(
        built=built,
        cached=cached,
        planned=planned,
        skipped=skipped,
        artifacts=artifacts,
        contact_sheet_manifest=contact_manifest,
        dry_run=request.dry_run,
        resumed=request.resume,
        run_id=operation.run_id if operation is not None else None,
        run_manifest_path=operation.path if operation is not None else None,
    )


def build_proxies(
    request: ProxyRequest,
    *,
    runner: ProcessRunner | None = None,
    progress: Callable[[str], None] | None = None,
) -> ProxyResult:
    selected_ids = _selected_asset_ids(request)
    indexed = {asset.asset_id: asset for asset in request.index.assets}
    operation = start_operation(
        request.config,
        command="proxy_build",
        invocation={
            "assetIds": selected_ids,
            "resume": request.resume,
            "force": request.force,
        },
        expected_items=selected_ids,
        input_fingerprints={
            asset_id: indexed[asset_id].full_hash or indexed[asset_id].fingerprint
            for asset_id in selected_ids
        },
        enabled=not request.dry_run,
    )
    try:
        return _build_selected_proxies(
            request,
            selected_ids=selected_ids,
            operation=operation,
            runner=runner,
            progress=progress,
        )
    except BaseException as error:
        fail_operation(operation, error)
        raise
