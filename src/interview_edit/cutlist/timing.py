from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from interview_edit.config.models import ProjectConfig
from interview_edit.errors import PreflightError
from interview_edit.models.cutlist import TimelineItem
from interview_edit.models.media import MediaAsset, MediaIndex
from interview_edit.models.sync import SyncCamera, SyncReport
from interview_edit.sync.service import load_current_sync_report


@dataclass(frozen=True)
class VisualInterval:
    asset: MediaAsset
    local_start_us: int
    duration_us: int
    source_start_us: int
    source_duration_us: int


def _sync_report(config: ProjectConfig, index: MediaIndex, take_id: str) -> SyncReport:
    return load_current_sync_report(config, index, take_id)


def _camera_time(reference_us: int, camera: SyncCamera) -> int:
    scaled = Fraction(reference_us * (1_000_000 + camera.drift_ppm), 1_000_000)
    return round(scaled) + camera.offset_us


def _reference_time(camera_us: int, camera: SyncCamera) -> int:
    return round(Fraction((camera_us - camera.offset_us) * 1_000_000, 1_000_000 + camera.drift_ppm))


def map_source_range(
    *,
    config: ProjectConfig,
    index: MediaIndex,
    source: MediaAsset,
    target: MediaAsset,
    start_us: int,
    duration_us: int,
) -> tuple[int, int]:
    if source.asset_id == target.asset_id:
        return start_us, duration_us
    if source.take_id is None or target.take_id != source.take_id:
        raise PreflightError(
            "source_time_mapping_unavailable",
            "Alternate camera/audio source must belong to the primary source take.",
            details={"sourceId": source.asset_id, "targetId": target.asset_id},
        )
    report = _sync_report(config, index, source.take_id)
    cameras = {camera.camera_id: camera for camera in report.cameras}
    source_camera = cameras.get(source.camera_id or "")
    target_camera = cameras.get(target.camera_id or "")
    if (
        source_camera is None
        or target_camera is None
        or source_camera.asset_id != source.asset_id
        or target_camera.asset_id != target.asset_id
        or target_camera.status == "uncertain"
    ):
        raise PreflightError(
            "camera_sync_uncertain",
            "Confirmed sync evidence is required to map source time.",
            details={"sourceId": source.asset_id, "targetId": target.asset_id},
        )
    reference_start = _reference_time(start_us, source_camera)
    reference_end = _reference_time(start_us + duration_us, source_camera)
    target_start = _camera_time(reference_start, target_camera)
    target_end = _camera_time(reference_end, target_camera)
    if target_start < 0 or target_end <= target_start or target_end > target.duration_us:
        raise PreflightError(
            "mapped_source_range_out_of_bounds",
            "Synchronized source mapping falls outside the target camera.",
            details={
                "sourceId": source.asset_id,
                "targetId": target.asset_id,
                "targetStartUs": target_start,
                "targetEndUs": target_end,
                "targetDurationUs": target.duration_us,
            },
        )
    return target_start, target_end - target_start


def visual_intervals(
    config: ProjectConfig,
    index: MediaIndex,
    item: TimelineItem,
    source: MediaAsset,
    assets: dict[str, MediaAsset],
) -> list[VisualInterval]:
    assert item.source_in_us is not None
    if not item.camera_cuts:
        return [
            VisualInterval(
                asset=source,
                local_start_us=0,
                duration_us=item.timeline_duration_us,
                source_start_us=item.source_in_us,
                source_duration_us=item.timeline_duration_us,
            )
        ]
    if source.take_id is None:
        raise PreflightError("camera_take_required", "Camera cuts require a mapped source take.")
    cameras = {
        asset.camera_id: asset
        for asset in assets.values()
        if asset.take_id == source.take_id and asset.camera_id is not None
    }
    base_camera = item.base_camera or source.camera_id
    base_asset = cameras.get(base_camera or "")
    if base_asset is None:
        raise PreflightError(
            "base_camera_unknown", "Primary base camera is not mapped in its take."
        )
    intervals: list[VisualInterval] = []
    cursor = 0
    for cut in sorted(item.camera_cuts, key=lambda value: value.start_us):
        if cut.start_us > cursor:
            target_start, target_duration = map_source_range(
                config=config,
                index=index,
                source=source,
                target=base_asset,
                start_us=item.source_in_us + cursor,
                duration_us=cut.start_us - cursor,
            )
            intervals.append(
                VisualInterval(
                    base_asset,
                    cursor,
                    cut.start_us - cursor,
                    target_start,
                    target_duration,
                )
            )
        target = cameras.get(cut.camera_id)
        if target is None:
            raise PreflightError("camera_unknown", f"Camera is not mapped: {cut.camera_id}")
        target_start, target_duration = map_source_range(
            config=config,
            index=index,
            source=source,
            target=target,
            start_us=item.source_in_us + cut.start_us,
            duration_us=cut.duration_us,
        )
        intervals.append(
            VisualInterval(
                target,
                cut.start_us,
                cut.duration_us,
                target_start,
                target_duration,
            )
        )
        cursor = cut.end_us
    if cursor < item.timeline_duration_us:
        duration = item.timeline_duration_us - cursor
        target_start, target_duration = map_source_range(
            config=config,
            index=index,
            source=source,
            target=base_asset,
            start_us=item.source_in_us + cursor,
            duration_us=duration,
        )
        intervals.append(
            VisualInterval(base_asset, cursor, duration, target_start, target_duration)
        )
    return intervals
