from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import ValidationError

from interview_edit.adapters.artifacts import validated_audio_proxy, validated_video_proxy
from interview_edit.adapters.filesystem import sha256_file
from interview_edit.adapters.process import ProcessRunner, SubprocessRunner
from interview_edit.config.models import ProjectConfig
from interview_edit.errors import DependencyError, PreflightError, ProcessingError, UsageError
from interview_edit.models.media import MediaAsset, MediaIndex
from interview_edit.models.sync import SyncCamera, SyncEvidence, SyncReport, SyncWindow
from interview_edit.operation.service import OperationRecorder, fail_operation, start_operation
from interview_edit.project.layout import artifact_path, atomic_write_text
from interview_edit.proxy.service import validate_source_revision
from interview_edit.sync.analysis import energy_envelope, estimate_sync, window_centers_us

_SYNC_SCHEMA = "sync-v1"
_OFFSET_PATTERN = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))(us|ms|s)?$")


@dataclass(frozen=True)
class ManualOffset:
    camera_id: str
    offset_us: int
    original_value: str


@dataclass(frozen=True)
class SyncRequest:
    config: ProjectConfig
    index: MediaIndex
    take_id: str
    reference_camera_id: str
    window_count: int | None = None
    visual_check: bool = False
    manual_offsets: tuple[ManualOffset, ...] = ()
    force: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class SyncResult:
    report: SyncReport | None
    report_path: Path
    artifacts: list[Path]
    cached: bool
    uncertain_cameras: list[str]
    dry_run: bool
    run_id: str | None
    run_manifest_path: Path | None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_manual_offset(value: str) -> ManualOffset:
    camera_id, separator, raw_value = value.partition("=")
    camera_id = camera_id.strip()
    raw_value = raw_value.strip()
    if not separator or not camera_id:
        raise UsageError(
            "manual_offset_invalid",
            "Manual offset must use CAMERA=VALUE.",
            details={"value": value},
        )
    match = _OFFSET_PATTERN.fullmatch(raw_value)
    if match is None:
        raise UsageError(
            "manual_offset_invalid",
            "Offset values accept signed integers in us, or decimals with ms/s suffixes.",
            details={"value": value},
        )
    multiplier = {None: Decimal(1), "us": Decimal(1), "ms": Decimal(1000), "s": Decimal(1_000_000)}[
        match.group(2)
    ]
    try:
        offset_us = int(
            (Decimal(match.group(1)) * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
    except InvalidOperation as exc:
        raise UsageError(
            "manual_offset_invalid", "Manual offset is not numeric.", details={"value": value}
        ) from exc
    return ManualOffset(camera_id=camera_id, offset_us=offset_us, original_value=raw_value)


def _take_assets(index: MediaIndex, take_id: str) -> dict[str, MediaAsset]:
    selected = [asset for asset in index.assets if asset.take_id == take_id]
    if not selected:
        raise UsageError(
            "take_unknown",
            "The requested take is not present in the media index.",
            details={"takeId": take_id},
        )
    missing_camera = [asset.asset_id for asset in selected if asset.camera_id is None]
    if missing_camera:
        raise UsageError(
            "take_camera_mapping_incomplete",
            "Every asset in a synchronized take requires a camera ID.",
            details={"assetIds": missing_camera, "takeId": take_id},
        )
    cameras: dict[str, MediaAsset] = {}
    duplicates: list[str] = []
    for asset in selected:
        assert asset.camera_id is not None
        if asset.camera_id in cameras:
            duplicates.append(asset.camera_id)
        cameras[asset.camera_id] = asset
    if duplicates:
        raise UsageError(
            "take_camera_ambiguous",
            "A take must contain at most one asset per camera for M3 synchronization.",
            details={"cameraIds": sorted(set(duplicates)), "takeId": take_id},
        )
    if len(cameras) < 2:
        raise PreflightError(
            "sync_camera_count_insufficient",
            "Synchronization requires at least two mapped cameras in the take.",
            details={"takeId": take_id, "cameraCount": len(cameras)},
        )
    return cameras


def _cache_key(
    *,
    request: SyncRequest,
    cameras: dict[str, MediaAsset],
    audio_hashes: dict[str, str],
    analysis: dict[str, Any],
) -> str:
    payload = {
        "schema": _SYNC_SCHEMA,
        "take_id": request.take_id,
        "reference_camera_id": request.reference_camera_id,
        "cameras": [
            {
                "camera_id": camera_id,
                "asset_id": cameras[camera_id].asset_id,
                "source_fingerprint": cameras[camera_id].fingerprint,
                "audio_proxy_sha256": audio_hashes[camera_id],
            }
            for camera_id in sorted(cameras)
        ],
        "analysis": analysis,
        "manual_offsets": [
            {"camera_id": item.camera_id, "offset_us": item.offset_us}
            for item in sorted(request.manual_offsets, key=lambda item: item.camera_id)
        ],
        "numpy_version": np.__version__,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _checksum_path(report_path: Path) -> Path:
    return report_path.with_name("sync.sha256")


def _report_checksum_valid(report_path: Path) -> bool:
    checksum_path = _checksum_path(report_path)
    try:
        if checksum_path.is_symlink():
            return False
        expected = checksum_path.read_text(encoding="utf-8").strip()
        return expected == sha256_file(report_path)
    except (OSError, UnicodeError):
        return False


def _analysis_settings(
    config: ProjectConfig,
    cameras: dict[str, MediaAsset],
    reference_camera_id: str,
    window_count: int,
) -> dict[str, Any]:
    return {
        "sample_rate": config.sync.sample_rate,
        "envelope_hz": config.sync.envelope_hz,
        "window_count": window_count,
        "window_duration_us": config.sync.window_duration_seconds * 1_000_000,
        "max_offset_us": config.sync.max_offset_seconds * 1_000_000,
        "minimum_confidence": config.sync.minimum_confidence,
        "drift_tolerance_us_per_hour": config.sync.drift_tolerance_us_per_hour,
        "camera_order": [reference_camera_id]
        + [camera for camera in sorted(cameras) if camera != reference_camera_id],
    }


def load_current_sync_report(
    config: ProjectConfig,
    index: MediaIndex,
    take_id: str,
) -> SyncReport:
    """Load a sync report only when its current inputs still reproduce its cache key."""
    path = artifact_path(config.artifact_root, "sync", take_id, "sync.json")
    try:
        report = SyncReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise PreflightError(
            "sync_report_required",
            "A valid sync report is required for camera or alternate-audio mapping.",
            details={"takeId": take_id, "path": str(path)},
        ) from exc
    if not _report_checksum_valid(path):
        raise PreflightError(
            "sync_report_stale",
            "Synchronization report checksum is missing or does not match; run sync again.",
            details={"takeId": take_id, "path": str(path)},
        )
    cameras = _take_assets(index, take_id)
    report_assets = {camera.camera_id: camera.asset_id for camera in report.cameras}
    current_assets = {camera_id: asset.asset_id for camera_id, asset in cameras.items()}
    if (
        report.take_id != take_id
        or report.reference_camera_id not in cameras
        or report_assets != current_assets
        or len(report_assets) != len(report.cameras)
    ):
        raise PreflightError(
            "sync_report_stale",
            "Synchronization inputs changed; run sync again.",
            details={"takeId": take_id, "path": str(path)},
        )
    window_count = report.analysis.get("window_count")
    if not isinstance(window_count, int) or window_count < 3:
        raise PreflightError(
            "sync_report_stale",
            "Synchronization settings are missing or invalid; run sync again.",
            details={"takeId": take_id, "path": str(path)},
        )
    analysis = _analysis_settings(config, cameras, report.reference_camera_id, window_count)
    if report.analysis != analysis:
        raise PreflightError(
            "sync_report_stale",
            "Synchronization settings changed; run sync again.",
            details={"takeId": take_id, "path": str(path)},
        )
    audio_hashes: dict[str, str] = {}
    for camera_id, asset in cameras.items():
        validate_source_revision(asset)
        audio_hashes[camera_id] = validated_audio_proxy(config, asset).sha256
    manual_offsets = tuple(
        ManualOffset(
            camera_id=camera.camera_id,
            offset_us=camera.offset_us,
            original_value=camera.manual_value or f"{camera.offset_us}us",
        )
        for camera in report.cameras
        if camera.provenance == "manual_override"
    )
    expected_key = _cache_key(
        request=SyncRequest(
            config=config,
            index=index,
            take_id=take_id,
            reference_camera_id=report.reference_camera_id,
            window_count=window_count,
            manual_offsets=manual_offsets,
        ),
        cameras=cameras,
        audio_hashes=audio_hashes,
        analysis=analysis,
    )
    if report.cache_key != expected_key:
        raise PreflightError(
            "sync_report_stale",
            "Synchronization inputs changed; run sync again.",
            details={"takeId": take_id, "path": str(path)},
        )
    return report


def _read_cached_report(path: Path, cache_key: str, *, visual_check: bool) -> SyncReport | None:
    if not _report_checksum_valid(path):
        return None
    try:
        report = SyncReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError):
        return None
    if report.cache_key != cache_key:
        return None
    evidence_missing = not report.evidence
    for item in report.evidence:
        path = Path(item.path)
        try:
            valid = (
                path.is_file()
                and path.stat().st_size == item.size
                and sha256_file(path) == item.sha256
            )
        except OSError:
            valid = False
        evidence_missing = evidence_missing or not valid
    if visual_check and evidence_missing:
        return None
    return report


def _video_proxy(config: ProjectConfig, asset: MediaAsset) -> Path:
    if asset.video_stream is None:
        raise PreflightError(
            "sync_visual_proxy_missing",
            "Visual sync evidence requires a video proxy for every selected camera.",
            details={"assetId": asset.asset_id},
        )
    return validated_video_proxy(config, asset)


def _visual_evidence(
    *,
    request: SyncRequest,
    cameras: dict[str, MediaAsset],
    results: list[SyncCamera],
    centers: tuple[int, ...],
    runner: ProcessRunner,
) -> list[SyncEvidence]:
    evidence_root = artifact_path(request.config.artifact_root, "sync", request.take_id, "evidence")
    evidence_root.mkdir(parents=True, exist_ok=True)
    result_by_camera = {item.camera_id: item for item in results}
    ordered_cameras = [request.reference_camera_id] + [
        camera_id for camera_id in sorted(cameras) if camera_id != request.reference_camera_id
    ]
    proxies = [_video_proxy(request.config, cameras[camera_id]) for camera_id in ordered_cameras]
    evidence: list[SyncEvidence] = []
    for index, center_us in enumerate(centers, start=1):
        output = evidence_root / f"window-{index:03d}.jpg"
        descriptor, temporary_name = tempfile.mkstemp(
            dir=evidence_root, prefix=f".{output.stem}.", suffix=".tmp.jpg"
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            args = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
            for camera_id, proxy in zip(ordered_cameras, proxies, strict=True):
                seek_us = max(0, center_us + result_by_camera[camera_id].offset_us)
                args.extend(["-ss", f"{seek_us / 1_000_000:.6f}", "-i", str(proxy)])
            filters = [
                f"[{input_index}:v]scale=480:270:force_original_aspect_ratio=decrease,"
                f"pad=480:270:(ow-iw)/2:(oh-ih)/2[v{input_index}]"
                for input_index in range(len(proxies))
            ]
            stack_inputs = "".join(f"[v{input_index}]" for input_index in range(len(proxies)))
            filters.append(f"{stack_inputs}hstack=inputs={len(proxies)}[out]")
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
                    str(temporary),
                ]
            )
            result = runner.run(args, timeout_seconds=10 * 60)
            if result.return_code == 127:
                raise DependencyError(
                    "ffmpeg_missing", "Required executable is unavailable: ffmpeg."
                )
            if result.return_code != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
                raise ProcessingError(
                    "sync_visual_evidence_failed",
                    "FFmpeg could not generate visual synchronization evidence.",
                    details={"returnCode": result.return_code, "stderr": result.stderr[-4000:]},
                )
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        evidence.append(
            SyncEvidence(
                kind="visual_contact_sheet",
                path=str(output),
                reference_time_us=center_us,
                size=output.stat().st_size,
                sha256=sha256_file(output),
            )
        )
    return evidence


def _sync_take(
    request: SyncRequest,
    *,
    operation: OperationRecorder | None,
    runner: ProcessRunner | None = None,
    progress: Callable[[str], None] | None = None,
) -> SyncResult:
    cameras = _take_assets(request.index, request.take_id)
    if request.reference_camera_id not in cameras:
        raise UsageError(
            "reference_camera_unknown",
            "The reference camera is not present in the requested take.",
            details={"cameraId": request.reference_camera_id, "takeId": request.take_id},
        )
    manual_by_camera: dict[str, ManualOffset] = {}
    for item in request.manual_offsets:
        if item.camera_id not in cameras:
            raise UsageError(
                "manual_offset_camera_unknown",
                "A manual offset names a camera outside the requested take.",
                details={"cameraId": item.camera_id, "takeId": request.take_id},
            )
        if item.camera_id == request.reference_camera_id:
            raise UsageError(
                "manual_offset_reference_forbidden",
                "The reference camera offset is always zero.",
            )
        if item.camera_id in manual_by_camera:
            raise UsageError(
                "manual_offset_duplicate",
                "A camera may have only one manual offset.",
                details={"cameraId": item.camera_id},
            )
        manual_by_camera[item.camera_id] = item

    window_count = request.window_count or request.config.sync.window_count
    if window_count < 3:
        raise UsageError(
            "sync_window_count_invalid", "Synchronization requires at least 3 windows."
        )
    analysis = _analysis_settings(
        request.config, cameras, request.reference_camera_id, window_count
    )
    window_duration_us = request.config.sync.window_duration_seconds * 1_000_000
    max_offset_us = request.config.sync.max_offset_seconds * 1_000_000
    audio_paths: dict[str, Path] = {}
    audio_hashes: dict[str, str] = {}
    for camera_id, asset in cameras.items():
        validate_source_revision(asset)
        audio = validated_audio_proxy(request.config, asset)
        audio_paths[camera_id] = audio.path
        audio_hashes[camera_id] = audio.sha256
    if operation is not None:
        operation.checkpoint(tools={"numpy": np.__version__})
    cache_key = _cache_key(
        request=request, cameras=cameras, audio_hashes=audio_hashes, analysis=analysis
    )
    report_path = artifact_path(request.config.artifact_root, "sync", request.take_id, "sync.json")
    if request.dry_run:
        return SyncResult(
            report=None,
            report_path=report_path,
            artifacts=[],
            cached=False,
            uncertain_cameras=[],
            dry_run=True,
            run_id=None,
            run_manifest_path=None,
        )
    cached = (
        None
        if request.force
        else _read_cached_report(report_path, cache_key, visual_check=request.visual_check)
    )
    if cached is not None:
        cached_uncertain = [
            camera.camera_id for camera in cached.cameras if camera.status == "uncertain"
        ]
        artifacts = [
            report_path,
            _checksum_path(report_path),
            *(Path(item.path) for item in cached.evidence),
        ]
        if operation is not None:
            operation.checkpoint(cached_items=sorted(cameras))
            operation.finish(
                state="review_required" if cached_uncertain else "succeeded",
                artifacts=artifacts,
                warning_codes=["sync_confidence_insufficient"] if cached_uncertain else [],
            )
        return SyncResult(
            report=cached,
            report_path=report_path,
            artifacts=artifacts,
            cached=True,
            uncertain_cameras=cached_uncertain,
            dry_run=False,
            run_id=operation.run_id if operation is not None else None,
            run_manifest_path=operation.path if operation is not None else None,
        )

    if progress is not None:
        progress(f"Analyzing {len(cameras)} cameras across {window_count} sync windows...")
    envelopes = {
        camera_id: energy_envelope(
            audio_paths[camera_id],
            envelope_hz=request.config.sync.envelope_hz,
            sample_rate=request.config.sync.sample_rate,
        )
        for camera_id in sorted(cameras)
    }
    reference = envelopes[request.reference_camera_id]
    reference_duration_us = reference.size * 1_000_000 // request.config.sync.envelope_hz
    centers = window_centers_us(
        reference_duration_us,
        window_count=window_count,
        window_duration_us=window_duration_us,
    )
    camera_results = [
        SyncCamera(
            camera_id=request.reference_camera_id,
            asset_id=cameras[request.reference_camera_id].asset_id,
            status="reference",
            offset_us=0,
            drift_us_per_hour=0,
            drift_ppm=0,
            confidence=1.0,
            provenance="reference",
            windows=[],
        )
    ]
    uncertain: list[str] = []
    for camera_id in sorted(cameras):
        if camera_id == request.reference_camera_id:
            continue
        manual = manual_by_camera.get(camera_id)
        if manual is not None:
            status: Literal["confirmed", "drifting", "uncertain", "manual"] = "manual"
            offset_us = manual.offset_us
            provenance: Literal["automatic_audio_correlation", "manual_override"] = (
                "manual_override"
            )
            drift_us_per_hour = 0
            drift_ppm = 0
            confidence = 0.0
            sync_windows: list[SyncWindow] = []
        else:
            estimate = estimate_sync(
                reference,
                envelopes[camera_id],
                envelope_hz=request.config.sync.envelope_hz,
                window_count=window_count,
                window_duration_us=window_duration_us,
                max_offset_us=max_offset_us,
            )
            offset_us = estimate.offset_us
            provenance = "automatic_audio_correlation"
            drift_us_per_hour = estimate.drift_us_per_hour
            drift_ppm = estimate.drift_ppm
            confidence = estimate.confidence
            sync_windows = [
                SyncWindow(
                    reference_center_us=window.center_us,
                    offset_us=window.offset_us,
                    confidence=window.confidence,
                    peak_margin=window.peak_margin,
                )
                for window in estimate.windows
            ]
            if estimate.confidence < request.config.sync.minimum_confidence:
                status = "uncertain"
                uncertain.append(camera_id)
            elif abs(estimate.drift_us_per_hour) > request.config.sync.drift_tolerance_us_per_hour:
                status = "drifting"
            else:
                status = "confirmed"
        camera_results.append(
            SyncCamera(
                camera_id=camera_id,
                asset_id=cameras[camera_id].asset_id,
                status=status,
                offset_us=offset_us,
                drift_us_per_hour=drift_us_per_hour,
                drift_ppm=drift_ppm,
                confidence=confidence,
                provenance=provenance,
                manual_value=manual.original_value if manual is not None else None,
                windows=sync_windows,
            )
        )
    selected_runner = runner or SubprocessRunner()
    evidence = (
        _visual_evidence(
            request=request,
            cameras=cameras,
            results=camera_results,
            centers=centers,
            runner=selected_runner,
        )
        if request.visual_check
        else []
    )
    report = SyncReport(
        take_id=request.take_id,
        reference_camera_id=request.reference_camera_id,
        cache_key=cache_key,
        analysis=analysis,
        cameras=camera_results,
        evidence=evidence,
        completed_at=_utc_now(),
    )
    atomic_write_text(report_path, report.model_dump_json(indent=2) + "\n")
    checksum_path = _checksum_path(report_path)
    atomic_write_text(checksum_path, sha256_file(report_path) + "\n")
    artifacts = [report_path, checksum_path, *(Path(item.path) for item in evidence)]
    if operation is not None:
        operation.checkpoint(completed_items=sorted(cameras))
        operation.finish(
            state="review_required" if uncertain else "succeeded",
            artifacts=artifacts,
            warning_codes=["sync_confidence_insufficient"] if uncertain else [],
        )
    return SyncResult(
        report=report,
        report_path=report_path,
        artifacts=artifacts,
        cached=False,
        uncertain_cameras=uncertain,
        dry_run=False,
        run_id=operation.run_id if operation is not None else None,
        run_manifest_path=operation.path if operation is not None else None,
    )


def sync_take(
    request: SyncRequest,
    *,
    runner: ProcessRunner | None = None,
    progress: Callable[[str], None] | None = None,
) -> SyncResult:
    selected = [asset for asset in request.index.assets if asset.take_id == request.take_id]
    camera_ids = sorted({asset.camera_id for asset in selected if asset.camera_id is not None})
    operation = start_operation(
        request.config,
        command="sync",
        invocation={
            "takeId": request.take_id,
            "referenceCameraId": request.reference_camera_id,
            "windowCount": request.window_count or request.config.sync.window_count,
            "visualCheck": request.visual_check,
            "manualCameraIds": sorted(item.camera_id for item in request.manual_offsets),
            "force": request.force,
        },
        expected_items=camera_ids,
        input_fingerprints={
            asset.asset_id: asset.full_hash or asset.fingerprint for asset in selected
        },
        enabled=not request.dry_run,
    )
    try:
        return _sync_take(
            request,
            operation=operation,
            runner=runner,
            progress=progress,
        )
    except BaseException as error:
        fail_operation(operation, error)
        raise
