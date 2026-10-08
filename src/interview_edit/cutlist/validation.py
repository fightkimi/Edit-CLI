from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path
from typing import Protocol

from PIL import Image

from interview_edit.adapters.artifacts import validated_video_proxy
from interview_edit.adapters.text import inspect_text_layout
from interview_edit.config.models import ProjectConfig
from interview_edit.cutlist.color import correction_filter, is_hdr
from interview_edit.errors import InterviewEditError
from interview_edit.ingest.service import read_media_index
from interview_edit.models.cutlist import (
    CutList,
    CutListValidationReport,
    OverlayKind,
    TimelineItem,
    TimelineItemKind,
    ValidationIssue,
)
from interview_edit.models.media import MediaAsset, MediaIndex
from interview_edit.models.sync import SyncReport
from interview_edit.motion.service import verify_motion
from interview_edit.project.layout import canonical
from interview_edit.proxy.service import validate_source_revision
from interview_edit.sync.service import load_current_sync_report


def _issue(
    issues: list[ValidationIssue],
    code: str,
    message: str,
    *,
    path: str | None = None,
    severity: str = "error",
    **details: object,
) -> None:
    issues.append(
        ValidationIssue(
            severity="warning" if severity == "warning" else "error",
            code=code,
            message=message,
            path=path,
            details=details,
        )
    )


def _spans_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a < end_b and start_b < end_a


def _asset_range(
    issues: list[ValidationIssue],
    asset: MediaAsset | None,
    source_in_us: int | None,
    source_out_us: int | None,
    *,
    path: str,
    purpose: str,
) -> None:
    if asset is None:
        _issue(issues, "source_unknown", f"{purpose} references an unknown asset.", path=path)
        return
    if asset.video_stream is None:
        _issue(issues, "source_video_missing", f"{purpose} requires a video stream.", path=path)
    if source_in_us is None or source_out_us is None:
        return
    if source_out_us > asset.duration_us:
        _issue(
            issues,
            "source_range_out_of_bounds",
            f"{purpose} exceeds the indexed source duration.",
            path=path,
            sourceOutUs=source_out_us,
            sourceDurationUs=asset.duration_us,
        )


def _current_source(
    issues: list[ValidationIssue],
    asset: MediaAsset,
    *,
    path: str,
) -> None:
    try:
        validate_source_revision(asset)
    except InterviewEditError as exc:
        source = canonical(Path(asset.canonical_path))
        _issue(
            issues,
            "source_index_stale",
            "Indexed source media is missing, unreadable, or changed; "
            "run ingest and rebuild dependent artifacts.",
            path=path,
            sourcePath=str(source),
            assetId=asset.asset_id,
            reason=exc.message,
        )


def _image_asset(
    issues: list[ValidationIssue],
    image: Path,
    *,
    path: str,
) -> None:
    if not image.is_file():
        _issue(
            issues,
            "image_asset_missing",
            "Image asset does not exist.",
            path=path,
            resolvedPath=str(image),
        )
        return
    try:
        with Image.open(image) as opened:
            opened.verify()
    except (OSError, ValueError) as exc:
        _issue(
            issues,
            "image_asset_invalid",
            "Image asset is not readable by the local rasterizer.",
            path=path,
            resolvedPath=str(image),
            reason=str(exc),
        )


def _resolved_asset_path(cutlist_path: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return canonical(cutlist_path.parent / path if not path.is_absolute() else path)


def _font_for(config: ProjectConfig, cutlist_path: Path, *values: str | None) -> Path | None:
    selected = next((value for value in values if value), None)
    if selected is not None:
        return _resolved_asset_path(cutlist_path, selected)
    return canonical(config.fonts[0]) if config.fonts else None


def _sync_report(config: ProjectConfig, index: MediaIndex, take_id: str) -> SyncReport:
    return load_current_sync_report(config, index, take_id)


class _TimedSpan(Protocol):
    start_us: int

    @property
    def end_us(self) -> int: ...


def _validate_local_ranges(issues: list[ValidationIssue], item: TimelineItem, *, path: str) -> None:
    def check_spans(collection_name: str, spans: Sequence[_TimedSpan]) -> None:
        for position, span in enumerate(spans):
            span_path = f"{path}.{collection_name}[{position}]"
            if span.end_us > item.timeline_duration_us:
                _issue(
                    issues,
                    "item_relative_range_out_of_bounds",
                    f"{collection_name} range exceeds its item duration.",
                    path=span_path,
                    endUs=span.end_us,
                    itemDurationUs=item.timeline_duration_us,
                )
        ordered = sorted(spans, key=lambda span: (span.start_us, span.end_us))
        for left, right in zip(ordered, ordered[1:], strict=False):
            if _spans_overlap(left.start_us, left.end_us, right.start_us, right.end_us):
                _issue(
                    issues,
                    f"{collection_name}_overlap",
                    f"{collection_name} ranges must not overlap.",
                    path=path,
                )

    check_spans("camera_cuts", item.camera_cuts)
    check_spans("overlays", item.overlays)
    check_spans("subtitles", item.subtitles)


def validate_cutlist(
    config: ProjectConfig,
    cutlist: CutList,
    *,
    cutlist_path: Path,
    profile_name: str | None = None,
) -> CutListValidationReport:
    resolved_path = canonical(cutlist_path)
    profile_id = profile_name or cutlist.render_profile
    issues: list[ValidationIssue] = []
    if cutlist.project_id != config.project_id:
        _issue(
            issues,
            "cutlist_project_mismatch",
            "Cut-list project_id does not match the selected project.",
            path="project_id",
            expected=config.project_id,
            actual=cutlist.project_id,
        )
    if not any(act.items for act in cutlist.acts):
        _issue(
            issues,
            "cutlist_empty",
            "Cut-list has no timeline items to validate or render.",
            path="acts",
        )

    profile = config.render_profiles.get(profile_id)
    if profile is None:
        _issue(
            issues,
            "render_profile_unknown",
            f"Render profile is not configured: {profile_id}",
            path="render_profile",
        )
    else:
        try:
            Fraction(profile.frame_rate)
        except (ValueError, ZeroDivisionError):
            _issue(
                issues,
                "render_frame_rate_invalid",
                "Render profile frame_rate must be a positive rational.",
                path=f"render_profiles.{profile_id}.frame_rate",
            )
        if profile.width % 2 or profile.height % 2:
            _issue(
                issues,
                "render_dimensions_incompatible",
                "Render width and height must be even for the configured H.264 pipeline.",
                path=f"render_profiles.{profile_id}",
            )
        if profile.frame_rate != cutlist.timeline.frame_rate:
            _issue(
                issues,
                "render_frame_rate_conversion",
                "Render profile changes the editorial timeline frame rate.",
                path="timeline.frame_rate",
                severity="warning",
                timelineFrameRate=cutlist.timeline.frame_rate,
                outputFrameRate=profile.frame_rate,
            )

    try:
        index = read_media_index(config)
    except InterviewEditError as exc:
        index = None
        _issue(
            issues,
            exc.code,
            exc.message,
            path="media-index",
            errorDetails=exc.details,
        )
    assets = {asset.asset_id: asset for asset in index.assets} if index is not None else {}
    for source_id, grade in cutlist.color_policy.by_source.items():
        asset = assets.get(source_id)
        if asset is None or asset.video_stream is None:
            _issue(
                issues,
                "color_source_unknown",
                "Color policy requires an indexed video source.",
                path=f"color_policy.by_source.{source_id}",
            )
        elif correction_filter(grade) and is_hdr(asset.video_stream.color_transfer):
            _issue(
                issues,
                "color_hdr_unsupported",
                "Color correction requires an SDR source; HDR tonemapping is not implemented.",
                path=f"color_policy.by_source.{source_id}",
            )
    checked_sources: set[str] = set()

    ids: dict[str, str] = {}
    overlay_uses: dict[tuple[str, int, int], str] = {}

    def track(identifier: str, path: str) -> None:
        earlier = ids.get(identifier)
        if earlier is not None:
            _issue(
                issues,
                "id_duplicate",
                f"Identifier is already used at {earlier}.",
                path=path,
                identifier=identifier,
                firstPath=earlier,
            )
        else:
            ids[identifier] = path

    for act_position, act in enumerate(cutlist.acts):
        act_path = f"acts[{act_position}]"
        track(act.act_id, f"{act_path}.act_id")
        for item_position, item in enumerate(act.items):
            item_path = f"{act_path}.items[{item_position}]"
            track(item.item_id, f"{item_path}.item_id")
            _validate_local_ranges(issues, item, path=item_path)
            if item.kind is TimelineItemKind.TRANSITION:
                _issue(
                    issues,
                    "standalone_transition_unsupported",
                    "V1 transitions must be paired on adjacent content items.",
                    path=f"{item_path}.kind",
                )

            source = assets.get(item.source_id or "")
            if item.kind in {TimelineItemKind.PRIMARY, TimelineItemKind.BROLL}:
                _asset_range(
                    issues,
                    source,
                    item.source_in_us,
                    item.source_out_us,
                    path=f"{item_path}.source_id",
                    purpose="Timeline item",
                )
                if source is not None and source.asset_id not in checked_sources:
                    _current_source(issues, source, path=f"{item_path}.source_id")
                    checked_sources.add(source.asset_id)
                if profile_id == "preview" and source is not None:
                    try:
                        validated_video_proxy(config, source)
                    except InterviewEditError as exc:
                        _issue(
                            issues,
                            exc.code,
                            exc.message,
                            path=f"{item_path}.source_id",
                            errorDetails=exc.details,
                        )
            if (
                item.kind is TimelineItemKind.PRIMARY
                and item.base_camera is not None
                and source is not None
                and item.base_camera != source.camera_id
            ):
                _issue(
                    issues,
                    "base_camera_source_mismatch",
                    "base_camera must identify the item's source asset camera in V1.",
                    path=f"{item_path}.base_camera",
                    sourceCameraId=source.camera_id,
                )

            audio_asset = assets.get(item.audio_source or "") if item.audio_source else source
            if item.audio_source is not None and audio_asset is None:
                _issue(
                    issues,
                    "audio_source_unknown",
                    "Item audio_source is not present in the media index.",
                    path=f"{item_path}.audio_source",
                )
            elif (
                audio_asset is not None
                and not audio_asset.audio_streams
                and (item.kind is TimelineItemKind.PRIMARY or item.audio_source is not None)
            ):
                _issue(
                    issues,
                    "audio_stream_missing",
                    "Selected audio source has no audio stream.",
                    path=f"{item_path}.audio_source",
                )
            if audio_asset is not None and audio_asset.asset_id not in checked_sources:
                _current_source(issues, audio_asset, path=f"{item_path}.audio_source")
                checked_sources.add(audio_asset.asset_id)

            if item.kind is TimelineItemKind.STILL and item.image_path:
                image = _resolved_asset_path(resolved_path, item.image_path)
                _image_asset(issues, image, path=f"{item_path}.image_path")

            if item.kind is TimelineItemKind.TITLE:
                font = _font_for(config, resolved_path, item.font_path)
                if font is None or not font.is_file():
                    _issue(
                        issues,
                        "font_required",
                        "A readable local font is required for titles and subtitles.",
                        path=f"{item_path}.font_path",
                        resolvedPath=str(font) if font is not None else None,
                    )

            for cut_position, cut in enumerate(item.camera_cuts):
                track(cut.cut_id, f"{item_path}.camera_cuts[{cut_position}].cut_id")
            if item.camera_cuts:
                if source is None or source.take_id is None:
                    _issue(
                        issues,
                        "camera_take_required",
                        "Camera cuts require a mapped source take.",
                        path=f"{item_path}.source_id",
                    )
                else:
                    take_assets = {
                        asset.camera_id: asset
                        for asset in assets.values()
                        if asset.take_id == source.take_id and asset.camera_id is not None
                    }
                    base_camera = item.base_camera or source.camera_id
                    if base_camera is None or base_camera not in take_assets:
                        _issue(
                            issues,
                            "base_camera_unknown",
                            "Primary base camera is not mapped in its take.",
                            path=f"{item_path}.base_camera",
                        )
                    report = None
                    if index is not None:
                        try:
                            report = _sync_report(config, index, source.take_id)
                        except InterviewEditError as exc:
                            _issue(
                                issues,
                                exc.code,
                                exc.message,
                                path=f"{item_path}.camera_cuts",
                                takeId=source.take_id,
                                errorDetails=exc.details,
                            )
                    if report is None:
                        if index is None:
                            _issue(
                                issues,
                                "sync_report_required",
                                "Camera cuts require a valid sync report for the take.",
                                path=f"{item_path}.camera_cuts",
                                takeId=source.take_id,
                            )
                    else:
                        report_cameras = {camera.camera_id: camera for camera in report.cameras}
                        for cut_position, cut in enumerate(item.camera_cuts):
                            cut_path = f"{item_path}.camera_cuts[{cut_position}].camera_id"
                            target = take_assets.get(cut.camera_id)
                            evidence = report_cameras.get(cut.camera_id)
                            if target is None:
                                _issue(
                                    issues,
                                    "camera_unknown",
                                    "Camera cut target is not mapped in the source take.",
                                    path=cut_path,
                                )
                            elif profile_id == "preview":
                                try:
                                    validated_video_proxy(config, target)
                                except InterviewEditError as exc:
                                    _issue(
                                        issues,
                                        exc.code,
                                        exc.message,
                                        path=cut_path,
                                        errorDetails=exc.details,
                                    )
                            if target is not None and target.asset_id not in checked_sources:
                                _current_source(issues, target, path=cut_path)
                                checked_sources.add(target.asset_id)
                            if (
                                target is None
                                or evidence is None
                                or evidence.status == "uncertain"
                                or evidence.asset_id != target.asset_id
                            ):
                                _issue(
                                    issues,
                                    "camera_sync_uncertain",
                                    "Camera cut target lacks confirmed sync evidence.",
                                    path=cut_path,
                                )

            for overlay_position, overlay in enumerate(item.overlays):
                overlay_path = f"{item_path}.overlays[{overlay_position}]"
                track(overlay.overlay_id, f"{overlay_path}.overlay_id")
                if overlay.kind is OverlayKind.MOTION:
                    try:
                        motion_root = _resolved_asset_path(cutlist_path, overlay.motion_path or "")
                        spec, _ = verify_motion(config, motion_root)
                        if overlay.duration_us > spec.duration_us:
                            _issue(
                                issues,
                                "motion_duration_exceeded",
                                "Motion overlay exceeds its declared source duration.",
                                path=overlay_path,
                            )
                        if profile is not None and Fraction(spec.width, spec.height) != Fraction(
                            profile.width, profile.height
                        ):
                            _issue(
                                issues,
                                "motion_aspect_mismatch",
                                "Motion canvas must match the render aspect ratio.",
                                path=overlay_path,
                            )
                        if (
                            spec.template == "lower_third"
                            and cutlist.subtitle_policy.enabled
                            and item.subtitles
                        ):
                            _issue(
                                issues,
                                "motion_caption_review",
                                "Review lower-third/subtitle spacing in the preview.",
                                path=overlay_path,
                                severity="warning",
                            )
                    except InterviewEditError as exc:
                        _issue(issues, exc.code, exc.message, path=overlay_path)
                elif overlay.kind is OverlayKind.BROLL:
                    overlay_asset = assets.get(overlay.source_id or "")
                    _asset_range(
                        issues,
                        overlay_asset,
                        overlay.source_in_us,
                        overlay.source_out_us,
                        path=f"{overlay_path}.source_id",
                        purpose="B-roll overlay",
                    )
                    if overlay_asset is not None and overlay_asset.asset_id not in checked_sources:
                        _current_source(issues, overlay_asset, path=f"{overlay_path}.source_id")
                        checked_sources.add(overlay_asset.asset_id)
                    if profile_id == "preview" and overlay_asset is not None:
                        try:
                            validated_video_proxy(config, overlay_asset)
                        except InterviewEditError as exc:
                            _issue(
                                issues,
                                exc.code,
                                exc.message,
                                path=overlay_path,
                                errorDetails=exc.details,
                            )
                    if (
                        overlay.source_id is not None
                        and overlay.source_in_us is not None
                        and overlay.source_out_us is not None
                    ):
                        key = (overlay.source_id, overlay.source_in_us, overlay.source_out_us)
                        earlier = overlay_uses.get(key)
                        if earlier is not None:
                            _issue(
                                issues,
                                "overlay_source_reused",
                                "The exact B-roll source range is reused.",
                                path=overlay_path,
                                severity="warning",
                                firstPath=earlier,
                            )
                        else:
                            overlay_uses[key] = overlay_path
                elif overlay.kind is OverlayKind.STILL and overlay.image_path:
                    image = _resolved_asset_path(resolved_path, overlay.image_path)
                    _image_asset(issues, image, path=f"{overlay_path}.image_path")
                elif overlay.kind is OverlayKind.TITLE:
                    font = _font_for(config, resolved_path, overlay.font_path, item.font_path)
                    if font is None or not font.is_file():
                        _issue(
                            issues,
                            "font_required",
                            "A readable local font is required for title overlays.",
                            path=f"{overlay_path}.font_path",
                        )

            for subtitle_position, subtitle in enumerate(item.subtitles):
                subtitle_path = f"{item_path}.subtitles[{subtitle_position}]"
                track(subtitle.subtitle_id, f"{subtitle_path}.subtitle_id")
                if cutlist.subtitle_policy.enabled:
                    font = _font_for(
                        config,
                        resolved_path,
                        subtitle.font_path,
                        item.font_path,
                    )
                    if font is None or not font.is_file():
                        _issue(
                            issues,
                            "font_required",
                            "A readable local font is required for subtitles.",
                            path=f"{subtitle_path}.font_path",
                        )

            if profile is not None:
                texts = [(item.title_text, item.font_path, False)]
                texts.extend(
                    (overlay.text, overlay.font_path or item.font_path, False)
                    for overlay in item.overlays
                    if overlay.kind is OverlayKind.TITLE
                )
                if cutlist.subtitle_policy.enabled:
                    texts.extend(
                        (subtitle.text, subtitle.font_path or item.font_path, True)
                        for subtitle in item.subtitles
                    )
                for text, declared_font, is_subtitle in texts:
                    font = _font_for(config, resolved_path, declared_font)
                    if not text or font is None or not font.is_file():
                        continue
                    try:
                        layout = inspect_text_layout(
                            text=text,
                            font_path=font,
                            width=profile.width,
                            height=profile.height,
                            placement="subtitle" if is_subtitle else "center",
                            safe_area_percent=cutlist.subtitle_policy.safe_area_percent,
                            style=cutlist.subtitle_policy.style if is_subtitle else "standard",
                        )
                        if layout.overflow:
                            _issue(
                                issues,
                                "text_layout_overflow",
                                "Text exceeds the layout; split it before rendering.",
                                path=item_path,
                                lineCount=layout.line_count,
                            )
                    except InterviewEditError as exc:
                        _issue(issues, exc.code, exc.message, path=item_path)

        for item_position, item in enumerate(act.items):
            item_path = f"{act_path}.items[{item_position}]"
            previous = act.items[item_position - 1] if item_position > 0 else None
            following = act.items[item_position + 1] if item_position + 1 < len(act.items) else None
            if item.transition_in is not None:
                if previous is None or previous.transition_out != item.transition_in:
                    _issue(
                        issues,
                        "transition_pair_invalid",
                        "transition_in must exactly match the preceding item's transition_out.",
                        path=f"{item_path}.transition_in",
                    )
            if item.transition_out is not None:
                if following is None or following.transition_in != item.transition_out:
                    _issue(
                        issues,
                        "transition_pair_invalid",
                        "transition_out must exactly match the following item's transition_in.",
                        path=f"{item_path}.transition_out",
                    )
                elif item.transition_out.duration_us * 2 > min(
                    item.timeline_duration_us, following.timeline_duration_us
                ):
                    _issue(
                        issues,
                        "transition_duration_too_long",
                        "Transition duration may not exceed half of either adjacent item.",
                        path=f"{item_path}.transition_out.duration_us",
                    )

    item_count = sum(len(act.items) for act in cutlist.acts)
    duration = sum(item.timeline_duration_us for act in cutlist.acts for item in act.items)
    return CutListValidationReport(
        cutlist_path=str(resolved_path),
        project_id=cutlist.project_id,
        profile=profile_id,
        ok=not any(issue.severity == "error" for issue in issues),
        act_count=len(cutlist.acts),
        item_count=item_count,
        timeline_duration_us=duration,
        issues=issues,
    )
