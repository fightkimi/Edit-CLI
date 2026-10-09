from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from interview_edit.adapters.color import color_contact, color_frame, image_stats
from interview_edit.adapters.filesystem import sha256_file
from interview_edit.adapters.process import ProcessRunner, SubprocessRunner
from interview_edit.adapters.timeline import presentation_times
from interview_edit.config.models import ProjectConfig
from interview_edit.cutlist.color import is_hdr, suggest_correction
from interview_edit.cutlist.service import load_cutlist
from interview_edit.cutlist.timing import map_source_range
from interview_edit.errors import PreflightError, UsageError
from interview_edit.models.color import ColorReferenceSample, ColorReview, ColorSample
from interview_edit.models.cutlist import ColorCorrection
from interview_edit.models.media import MediaAsset
from interview_edit.project.layout import artifact_path, atomic_write_text, canonical
from interview_edit.review.service import ReviewResult, _check_inputs, _index, _remember


@dataclass(frozen=True)
class ColorResult(ReviewResult):
    report: ColorReview | None = None


def source_video_end(asset: MediaAsset) -> int:
    stream = asset.video_stream
    assert stream is not None
    if stream.duration_us is not None and stream.duration_us > 0:
        origin = asset.start_time_us or 0
        stream_start = stream.start_time_us if stream.start_time_us is not None else origin
        return min(asset.duration_us, stream_start - origin + stream.duration_us)
    return asset.duration_us


def source_frame_times(asset: MediaAsset, start: int, end: int, runner: ProcessRunner) -> list[int]:
    origin = asset.start_time_us or 0
    raw = presentation_times(
        canonical(Path(asset.canonical_path)), start + origin, end + origin, runner
    )
    times = [t - origin for t in raw if t >= origin]
    if not times:
        raise PreflightError("color_frames_unavailable", "No source-relative frames are available.")
    return times


def review_color(
    config: ProjectConfig,
    *,
    asset_id: str,
    start_us: int = 0,
    end_us: int | None = None,
    reference_id: str | None = None,
    cutlist_path: Path | None = None,
    samples: int = 4,
    dry_run: bool = False,
    runner: ProcessRunner | None = None,
) -> ColorResult:
    hashes: dict[str, str] = {}
    index = _index(config, hashes)
    assets = {a.asset_id: a for a in index.assets}
    asset = assets.get(asset_id)
    if asset is None or asset.video_stream is None:
        raise UsageError("color_source_unknown", "Choose an indexed video source.")
    video_end = source_video_end(asset)
    end = min(video_end, start_us + 3_000_000) if end_us is None else end_us
    if not 0 <= start_us < end <= video_end or end - start_us > 30_000_000 or not 2 <= samples <= 8:
        raise UsageError(
            "color_window_invalid",
            "Choose 2–8 samples in a source window no longer than 30 seconds.",
        )
    used = [asset]
    reference = None
    reference_start = 0
    reference_length = 0
    if reference_id:
        reference = assets.get(reference_id)
        if reference is None or reference.video_stream is None:
            raise UsageError(
                "color_reference_unknown", "Reference must be an indexed video source."
            )
        if asset.take_id and reference.asset_id != asset.asset_id:
            _remember(
                artifact_path(config.artifact_root, "sync", asset.take_id, "sync.json"), hashes
            )
        reference_start, reference_length = map_source_range(
            config=config,
            index=index,
            source=asset,
            target=reference,
            start_us=start_us,
            duration_us=end - start_us,
        )
        if reference_start + reference_length > source_video_end(reference):
            raise PreflightError(
                "color_reference_range_invalid", "Mapped range exceeds reference video duration."
            )
        used.append(reference)
    for value in used:
        assert value.video_stream is not None
        if is_hdr(value.video_stream.color_transfer):
            raise PreflightError(
                "color_hdr_unsupported",
                "Color diagnosis requires SDR; HDR tonemapping is not implemented.",
            )
        _remember(canonical(Path(value.canonical_path)), hashes)
    correction = None
    reference_correction = ColorCorrection()
    status: Literal["proposed", "configured"] = "proposed"
    if cutlist_path:
        _remember(cutlist_path, hashes)
        document = load_cutlist(cutlist_path)
        if document.project_id != config.project_id:
            raise PreflightError("cutlist_project_mismatch", "Cut-list belongs to another project.")
        correction = document.color_policy.by_source.get(asset_id, ColorCorrection())
        if reference_id:
            reference_correction = document.color_policy.by_source.get(
                reference_id, ColorCorrection()
            )
        status = "configured"
    root = artifact_path(config.artifact_root, "review", f"color_{uuid4().hex}")
    _check_inputs(hashes, used)
    if dry_run:
        return ColorResult(root, True, samples, [])
    root.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".color-", dir=root.parent))
    active = runner or SubprocessRunner()
    try:
        media = canonical(Path(asset.canonical_path))
        available = source_frame_times(asset, start_us, end, active)
        desired = [start_us + (end - start_us - 1) * i // (samples - 1) for i in range(samples)]
        times = [
            max((time for time in available if time <= point), default=available[0])
            for point in desired
        ]
        before = []
        for i, time in enumerate(times):
            path = stage / f"before-{i:02d}.jpg"
            color_frame(media, time, path, ColorCorrection(), active)
            before.append(path)
        original_stats = image_stats(before)
        ref_stats = None
        reference_records = []
        if reference is not None:
            ref_paths = []
            ref_media = canonical(Path(reference.canonical_path))
            ref_available = source_frame_times(
                reference, reference_start, reference_start + reference_length, active
            )
            for i, time in enumerate(times):
                point = reference_start + (time - start_us) * reference_length // (end - start_us)
                point = max((t for t in ref_available if t <= point), default=ref_available[0])
                path = stage / f"reference-{i:02d}.jpg"
                color_frame(ref_media, point, path, reference_correction, active)
                ref_paths.append(path)
                reference_records.append(
                    ColorReferenceSample(
                        time_us=point, path=str(root / path.name), sha256=sha256_file(path)
                    )
                )
            ref_stats = image_stats(ref_paths)
        if correction is None:
            correction = suggest_correction(original_stats, ref_stats)
        after = []
        records = []
        for i, time in enumerate(times):
            path = stage / f"after-{i:02d}.jpg"
            color_frame(media, time, path, correction, active)
            after.append(path)
            records.append(
                ColorSample(
                    time_us=time,
                    original_path=str(root / before[i].name),
                    original_sha256=sha256_file(before[i]),
                    corrected_path=str(root / path.name),
                    corrected_sha256=sha256_file(path),
                )
            )
        updated_stats = image_stats(after)
        warnings = ["pixel_statistics_not_scene_judgment"]
        if asset.video_stream.color_transfer in {None, "unknown", "unspecified"}:
            warnings.append("color_transfer_unknown")
        if original_stats.luma_p95 - original_stats.luma_p05 < 0.08:
            warnings.append("low_variation_samples")
        if updated_stats.highlight_fraction > original_stats.highlight_fraction + 0.02:
            warnings.append("highlights_increased")
        image = stage / "comparison.png"
        color_contact(before, after, times, image, status)
        report = ColorReview(
            project_id=config.project_id,
            asset_id=asset_id,
            reference_id=reference_id,
            start_us=start_us,
            end_us=end,
            source_clock_origin_us=asset.start_time_us or 0,
            reference_clock_origin_us=(reference.start_time_us or 0) if reference else None,
            before=original_stats,
            after=updated_stats,
            reference=ref_stats,
            reference_start_us=reference_start if reference else None,
            reference_end_us=reference_start + reference_length if reference else None,
            reference_correction=reference_correction if reference else None,
            reference_samples=reference_records,
            correction=correction,
            correction_status=status,
            samples=records,
            image_path=str(root / image.name),
            image_sha256=sha256_file(image),
            input_hashes=hashes,
            source_fingerprints={a.asset_id: a.fingerprint for a in used},
            color_transfer=asset.video_stream.color_transfer,
            warnings=warnings,
        )
        atomic_write_text(stage / "report.json", report.model_dump_json(indent=2))
        _check_inputs(hashes, used)
        os.rename(stage, root)
        return ColorResult(root, False, samples, warnings, report)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
