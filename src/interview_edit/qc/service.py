from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError

from interview_edit.adapters.filesystem import sha256_file
from interview_edit.adapters.media import ProbeMetadata, tool_version
from interview_edit.adapters.process import ProcessRunner, SubprocessRunner
from interview_edit.adapters.qc import (
    extract_frame,
    measure_loudness,
    probe_qc_media,
    scan_black,
    scan_silence,
)
from interview_edit.adapters.text import inspect_text_layout
from interview_edit.config.models import ProjectConfig, RenderProfile
from interview_edit.cutlist.service import load_cutlist
from interview_edit.cutlist.validation import validate_cutlist
from interview_edit.errors import PathSafetyError, PreflightError, UsageError
from interview_edit.models.cutlist import CutList, OverlayKind, TimelineItem, TimelineItemKind
from interview_edit.models.qc import (
    QCEvidence,
    QCFinding,
    QCFindingSeverity,
    QCMeasurements,
    QCPolicy,
    QCReport,
    QCStreamSummary,
    QCTimeRange,
)
from interview_edit.models.render import RenderRunManifest
from interview_edit.project.layout import atomic_write_text, canonical, is_within


@dataclass(frozen=True)
class QCRequest:
    config: ProjectConfig
    project_root: Path
    run_id: str | None = None
    policy: QCPolicy = QCPolicy.PREVIEW
    dry_run: bool = False


@dataclass(frozen=True)
class QCResult:
    report: QCReport
    report_path: Path | None
    checksum_path: Path | None
    dry_run: bool


@dataclass(frozen=True)
class TimelineSegment:
    item: TimelineItem
    start_us: int
    end_us: int


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _report_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"qc_{stamp}_{uuid.uuid4().hex[:10]}"


def canonical_config_sha256(config: ProjectConfig) -> str:
    encoded = json.dumps(
        config.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_path(config: ProjectConfig, run_id: str) -> Path:
    if not run_id.startswith("render_") or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
        for character in run_id
    ):
        raise UsageError(
            "render_run_id_invalid",
            "Render run ID has an invalid format.",
            details={"runId": run_id},
        )
    return config.artifact_root / "renders" / "runs" / f"{run_id}.json"


def load_render_run(config: ProjectConfig, run_id: str) -> tuple[RenderRunManifest, Path]:
    path = _run_path(config, run_id)
    try:
        manifest = RenderRunManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PreflightError(
            "render_run_missing",
            f"Render run manifest does not exist: {run_id}",
            details={"path": str(path)},
        ) from exc
    except (OSError, UnicodeError, ValidationError) as exc:
        raise PreflightError(
            "render_run_invalid",
            f"Render run manifest is invalid: {run_id}",
            details={"path": str(path), "reason": str(exc)},
        ) from exc
    if manifest.run_id != run_id or manifest.project_id != config.project_id:
        raise PreflightError(
            "render_run_project_mismatch",
            "Render run manifest does not belong to this project.",
            details={"path": str(path), "runId": run_id},
        )
    return manifest, path


def latest_successful_render(config: ProjectConfig) -> tuple[RenderRunManifest, Path]:
    root = config.artifact_root / "renders" / "runs"
    candidates: list[tuple[str, str, RenderRunManifest, Path]] = []
    for path in root.glob("render_*.json"):
        try:
            manifest = RenderRunManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError):
            continue
        if (
            manifest.project_id == config.project_id
            and manifest.state == "succeeded"
            and manifest.completed_at is not None
        ):
            candidates.append((manifest.completed_at, manifest.run_id, manifest, path))
    if not candidates:
        raise PreflightError(
            "successful_render_required",
            "No successful render run is available for QC.",
            details={"path": str(root)},
        )
    _, _, manifest, path = max(candidates, key=lambda value: (value[0], value[1]))
    return manifest, path


def _severity_for_content(policy: QCPolicy) -> QCFindingSeverity:
    return QCFindingSeverity.ERROR if policy is QCPolicy.RELEASE else QCFindingSeverity.WARNING


def _finding(
    findings: list[QCFinding],
    severity: QCFindingSeverity,
    code: str,
    message: str,
    *,
    item: TimelineItem | None = None,
    timeline_time_us: int | None = None,
    evidence_path: str | None = None,
    suggested_action: str | None = None,
    **details: Any,
) -> None:
    findings.append(
        QCFinding(
            severity=severity,
            code=code,
            message=message,
            item_id=item.item_id if item is not None else None,
            timeline_time_us=timeline_time_us,
            source_id=item.source_id if item is not None else None,
            evidence_path=evidence_path,
            suggested_action=suggested_action,
            details=details,
        )
    )


def _selected_segments(cutlist: CutList, manifest: RenderRunManifest) -> list[TimelineSegment]:
    raw_ids = manifest.selection.get("itemIds")
    if (
        not isinstance(raw_ids, list)
        or not raw_ids
        or not all(isinstance(value, str) for value in raw_ids)
    ):
        raise PreflightError(
            "render_selection_invalid",
            "Render manifest does not contain a valid selected item list.",
        )
    by_id = {item.item_id: item for act in cutlist.acts for item in act.items}
    segments: list[TimelineSegment] = []
    cursor = 0
    for item_id in raw_ids:
        item = by_id.get(item_id)
        if item is None:
            raise PreflightError(
                "render_selection_stale",
                "A rendered item is no longer present in the cut-list.",
                details={"itemId": item_id},
            )
        segments.append(
            TimelineSegment(item=item, start_us=cursor, end_us=cursor + item.timeline_duration_us)
        )
        cursor += item.timeline_duration_us
    return segments


def _segment_at(segments: list[TimelineSegment], timeline_time_us: int) -> TimelineSegment | None:
    for segment in segments:
        if segment.start_us <= timeline_time_us < segment.end_us:
            return segment
    return segments[-1] if segments and timeline_time_us == segments[-1].end_us else None


def _range_is_planned(
    segments: list[TimelineSegment], span: QCTimeRange, kinds: set[TimelineItemKind]
) -> bool:
    overlaps = [
        segment
        for segment in segments
        if span.start_us < segment.end_us and segment.start_us < span.end_us
    ]
    if not overlaps:
        return False
    covered_start = min(max(span.start_us, segment.start_us) for segment in overlaps)
    covered_end = max(min(span.end_us, segment.end_us) for segment in overlaps)
    return (
        covered_start == span.start_us
        and covered_end == span.end_us
        and all(segment.item.kind in kinds for segment in overlaps)
    )


def _resolved_path(cutlist_path: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    return canonical(cutlist_path.parent / candidate if not candidate.is_absolute() else candidate)


def _font_path(config: ProjectConfig, cutlist_path: Path, *values: str | None) -> Path | None:
    selected = next((value for value in values if value), None)
    if selected is not None:
        return _resolved_path(cutlist_path, selected)
    return canonical(config.fonts[0]) if config.fonts else None


def _check_text(
    *,
    config: ProjectConfig,
    cutlist: CutList,
    cutlist_path: Path,
    profile: RenderProfile,
    segments: list[TimelineSegment],
    policy: QCPolicy,
    findings: list[QCFinding],
) -> None:
    severity = _severity_for_content(policy)
    for segment in segments:
        item = segment.item
        text_specs: list[tuple[str, str, str | None, int]] = []
        if item.kind is TimelineItemKind.TITLE and item.title_text is not None:
            text_specs.append(("title", item.title_text, item.font_path, segment.start_us))
        for overlay in item.overlays:
            if overlay.kind is OverlayKind.TITLE and overlay.text is not None:
                text_specs.append(
                    (
                        "title",
                        overlay.text,
                        overlay.font_path or item.font_path,
                        segment.start_us + overlay.start_us,
                    )
                )
        if cutlist.subtitle_policy.enabled:
            for subtitle in item.subtitles:
                text_specs.append(
                    (
                        "subtitle",
                        subtitle.text,
                        subtitle.font_path or item.font_path,
                        segment.start_us + subtitle.start_us,
                    )
                )
        for placement, text, declared_font, time_us in text_specs:
            font = _font_path(config, cutlist_path, declared_font)
            if font is None or not font.is_file():
                continue
            inspection = inspect_text_layout(
                text=text,
                font_path=font,
                width=profile.width,
                height=profile.height,
                placement="subtitle" if placement == "subtitle" else "center",
                safe_area_percent=cutlist.subtitle_policy.safe_area_percent,
            )
            if not inspection.within_safe_area:
                _finding(
                    findings,
                    severity,
                    "text_outside_safe_area",
                    "Rendered text extends outside the configured safe area.",
                    item=item,
                    timeline_time_us=time_us,
                    suggested_action=(
                        "Shorten the text or choose a font/layout that fits the safe area."
                    ),
                    placement=placement,
                    alphaBounds=inspection.alpha_bounds,
                    safeBounds=inspection.safe_bounds,
                )
            if inspection.missing_glyph_count:
                _finding(
                    findings,
                    severity,
                    "font_missing_glyphs",
                    "The selected font cannot render every required glyph.",
                    item=item,
                    timeline_time_us=time_us,
                    suggested_action="Choose a local font with complete glyph coverage.",
                    placement=placement,
                    missingGlyphCount=inspection.missing_glyph_count,
                )


def _check_duplicate_sources(segments: list[TimelineSegment], findings: list[QCFinding]) -> None:
    uses: dict[tuple[str, int, int], str] = {}
    for segment in segments:
        item = segment.item
        candidates: list[tuple[str, int, int]] = []
        if (
            item.kind is TimelineItemKind.BROLL
            and item.source_id is not None
            and item.source_in_us is not None
            and item.source_out_us is not None
        ):
            candidates.append((item.source_id, item.source_in_us, item.source_out_us))
        candidates.extend(
            (overlay.source_id, overlay.source_in_us, overlay.source_out_us)
            for overlay in item.overlays
            if overlay.kind is OverlayKind.BROLL
            and overlay.source_id is not None
            and overlay.source_in_us is not None
            and overlay.source_out_us is not None
        )
        for source_id, source_in_us, source_out_us in candidates:
            key = (source_id, source_in_us, source_out_us)
            first_item = uses.get(key)
            if first_item is not None:
                _finding(
                    findings,
                    QCFindingSeverity.WARNING,
                    "source_range_reused",
                    "The exact same B-roll source range is used more than once.",
                    item=item,
                    timeline_time_us=segment.start_us,
                    suggested_action="Review whether the repeated visual is intentional.",
                    firstItemId=first_item,
                )
            else:
                uses[key] = item.item_id


def _expected_video_codec(profile: RenderProfile) -> str:
    return (
        "h264"
        if profile.video_codec in {"auto", "libx264", "h264_videotoolbox"}
        else profile.video_codec
    )


def _check_streams(
    metadata: ProbeMetadata,
    profile: RenderProfile,
    policy: QCPolicy,
    findings: list[QCFinding],
) -> None:
    video = metadata.video_stream
    if video is None:
        _finding(
            findings,
            QCFindingSeverity.BLOCKING,
            "video_stream_missing",
            "Rendered output has no video stream.",
        )
    else:
        expected_codec = _expected_video_codec(profile)
        checks = {
            "video_codec_mismatch": (video.codec_name, expected_codec, "video codec"),
            "video_width_mismatch": (video.width, profile.width, "video width"),
            "video_height_mismatch": (video.height, profile.height, "video height"),
            "pixel_format_mismatch": (video.pixel_format, "yuv420p", "pixel format"),
        }
        for code, (actual, expected, label) in checks.items():
            if actual != expected:
                _finding(
                    findings,
                    QCFindingSeverity.ERROR,
                    code,
                    f"Rendered {label} does not match the profile.",
                    suggested_action="Re-render from the validated profile.",
                    actual=actual,
                    expected=expected,
                )
        try:
            actual_rate = Fraction(video.average_frame_rate or "0/1")
            expected_rate = Fraction(profile.frame_rate)
        except (ValueError, ZeroDivisionError):
            actual_rate = Fraction(0, 1)
            expected_rate = Fraction(1, 1)
        if actual_rate != expected_rate:
            _finding(
                findings,
                QCFindingSeverity.ERROR,
                "frame_rate_mismatch",
                "Rendered frame rate does not match the profile.",
                suggested_action="Re-render from the validated profile.",
                actual=video.average_frame_rate,
                expected=profile.frame_rate,
            )
        if any(
            value is None
            for value in (
                video.color_range,
                video.color_space,
                video.color_transfer,
                video.color_primaries,
            )
        ):
            _finding(
                findings,
                QCFindingSeverity.WARNING,
                "color_metadata_incomplete",
                "Rendered video does not declare complete color metadata.",
                suggested_action="Confirm delivery color requirements before publishing.",
            )

    if not metadata.audio_streams:
        _finding(
            findings,
            QCFindingSeverity.BLOCKING,
            "audio_stream_missing",
            "Rendered output has no audio stream.",
        )
    else:
        audio = metadata.audio_streams[0]
        audio_checks = {
            "audio_codec_mismatch": (audio.codec_name, profile.audio_codec, "audio codec"),
            "audio_sample_rate_mismatch": (
                audio.sample_rate,
                profile.audio_sample_rate,
                "audio sample rate",
            ),
            "audio_channels_mismatch": (audio.channels, profile.audio_channels, "audio channels"),
        }
        for code, (actual, expected, label) in audio_checks.items():
            if actual != expected:
                _finding(
                    findings,
                    QCFindingSeverity.ERROR,
                    code,
                    f"Rendered {label} does not match the profile.",
                    suggested_action="Re-render from the validated profile.",
                    actual=actual,
                    expected=expected,
                )


def _cut_points(segments: list[TimelineSegment]) -> list[int]:
    points = {segment.start_us for segment in segments[1:]}
    for segment in segments:
        for cut in segment.item.camera_cuts:
            points.add(segment.start_us + cut.start_us)
            points.add(segment.start_us + cut.end_us)
        for overlay in segment.item.overlays:
            points.add(segment.start_us + overlay.start_us)
            points.add(segment.start_us + overlay.end_us)
    duration = segments[-1].end_us if segments else 0
    return sorted(point for point in points if 0 < point < duration)


def _thresholds(config: ProjectConfig) -> dict[str, int | float]:
    return config.qc.model_dump(mode="json")


def _write_report(staging: Path, final: Path, report: QCReport) -> Path:
    report_path = staging / "report.json"
    atomic_write_text(report_path, report.model_dump_json(indent=2) + "\n")
    atomic_write_text(staging / "report.sha256", sha256_file(report_path) + "\n")
    try:
        staging.rename(final)
    except OSError as exc:
        raise PathSafetyError(
            "qc_report_publish_failed",
            "Could not publish the QC report directory atomically.",
            details={"path": str(final), "reason": str(exc)},
        ) from exc
    return final / "report.json"


def run_qc(
    request: QCRequest,
    *,
    runner: ProcessRunner | None = None,
) -> QCResult:
    active_runner = runner or SubprocessRunner()
    manifest, run_path = (
        load_render_run(request.config, request.run_id)
        if request.run_id is not None
        else latest_successful_render(request.config)
    )
    report_id = _report_id()
    started_at = _utc_now()
    base_report = QCReport(
        report_id=report_id,
        state="planned" if request.dry_run else "failed",
        policy=request.policy,
        project_id=request.config.project_id,
        run_id=manifest.run_id,
        render_manifest_path=str(run_path),
        render_manifest_sha256=sha256_file(run_path),
        config_sha256=manifest.config_sha256,
        cutlist_path=manifest.cutlist_path,
        cutlist_sha256=manifest.cutlist_sha256,
        output_path=manifest.output.path if manifest.output is not None else None,
        output_size=manifest.output.size if manifest.output is not None else None,
        output_sha256=manifest.output.sha256 if manifest.output is not None else None,
        profile=manifest.profile,
        thresholds=_thresholds(request.config),
        started_at=started_at,
    )
    if request.dry_run:
        return QCResult(report=base_report, report_path=None, checksum_path=None, dry_run=True)

    final_root = request.config.artifact_root / "qc" / report_id
    staging = request.config.artifact_root / "qc" / f".{report_id}.{uuid.uuid4().hex}.tmp"
    staging.mkdir(parents=True, exist_ok=False)
    findings: list[QCFinding] = []
    commands = []
    evidence: list[QCEvidence] = []
    metadata: ProbeMetadata | None = None
    measurements = QCMeasurements()
    cutlist: CutList | None = None
    segments: list[TimelineSegment] = []
    try:
        if manifest.state != "succeeded" or manifest.output is None:
            _finding(
                findings,
                QCFindingSeverity.BLOCKING,
                "render_run_incomplete",
                "QC requires a successful render run with a recorded output.",
            )
        if request.policy is QCPolicy.RELEASE and manifest.profile != "master":
            _finding(
                findings,
                QCFindingSeverity.BLOCKING,
                "release_requires_master",
                "Release QC requires a successful master render.",
                suggested_action="Render the approved cut-list with the master profile.",
            )
        if canonical_config_sha256(request.config) != manifest.config_sha256:
            _finding(
                findings,
                QCFindingSeverity.BLOCKING,
                "render_config_stale",
                "Project configuration changed after this render.",
                suggested_action="Re-render with the current project configuration.",
            )

        cutlist_path = canonical(Path(manifest.cutlist_path))
        if not cutlist_path.is_file() or sha256_file(cutlist_path) != manifest.cutlist_sha256:
            _finding(
                findings,
                QCFindingSeverity.BLOCKING,
                "render_cutlist_stale",
                "Cut-list is missing or changed after this render.",
                suggested_action="Restore or re-render the exact cut-list revision.",
            )
        else:
            cutlist = load_cutlist(cutlist_path)
            validation = validate_cutlist(
                request.config,
                cutlist,
                cutlist_path=cutlist_path,
                profile_name=manifest.profile,
            )
            for issue in validation.issues:
                _finding(
                    findings,
                    QCFindingSeverity.BLOCKING
                    if issue.severity == "error"
                    else QCFindingSeverity.WARNING,
                    f"cutlist_{issue.code}",
                    issue.message,
                    suggested_action="Correct and re-render the cut-list before release.",
                    cutlistPath=issue.path,
                    **issue.details,
                )
            try:
                segments = _selected_segments(cutlist, manifest)
            except PreflightError as exc:
                _finding(
                    findings,
                    QCFindingSeverity.BLOCKING,
                    exc.code,
                    exc.message,
                    **exc.details,
                )

        output_record = manifest.output
        output_path = canonical(Path(output_record.path)) if output_record is not None else None
        output_valid = False
        if output_record is not None and output_path is not None:
            render_root = request.config.artifact_root / "renders"
            if not is_within(output_path, render_root):
                _finding(
                    findings,
                    QCFindingSeverity.BLOCKING,
                    "render_output_outside_artifacts",
                    "Recorded render output is outside the project render root.",
                )
            elif not output_path.is_file():
                _finding(
                    findings,
                    QCFindingSeverity.BLOCKING,
                    "render_output_missing",
                    "Recorded render output is missing.",
                )
            elif (
                output_path.stat().st_size != output_record.size
                or sha256_file(output_path) != output_record.sha256
            ):
                _finding(
                    findings,
                    QCFindingSeverity.BLOCKING,
                    "render_output_modified",
                    "Rendered output no longer matches its run manifest.",
                )
            else:
                output_valid = True

        profile = request.config.render_profiles.get(manifest.profile)
        if profile is None:
            _finding(
                findings,
                QCFindingSeverity.BLOCKING,
                "render_profile_missing",
                "The render profile no longer exists in project configuration.",
            )

        if output_valid and output_path is not None and profile is not None:
            metadata, command = probe_qc_media(output_path, active_runner)
            commands.append(command)
            _check_streams(metadata, profile, request.policy, findings)
            black, command = scan_black(
                output_path,
                active_runner,
                min_duration_seconds=request.config.qc.black_min_duration_seconds,
                pixel_threshold=request.config.qc.black_pixel_threshold,
                picture_ratio=request.config.qc.black_picture_ratio,
            )
            commands.append(command)
            silence, command = scan_silence(
                output_path,
                active_runner,
                min_duration_seconds=request.config.qc.silence_min_duration_seconds,
                noise_db=request.config.qc.silence_noise_db,
            )
            commands.append(command)
            loudness, command = measure_loudness(
                output_path,
                active_runner,
                integrated_lufs=request.config.audio_targets.integrated_lufs,
                true_peak_dbtp=request.config.audio_targets.true_peak_dbtp,
                loudness_range_lu=request.config.audio_targets.loudness_range_lu,
            )
            commands.append(command)

            video_duration = metadata.video_stream.duration_us if metadata.video_stream else None
            audio_duration = (
                metadata.audio_streams[0].duration_us if metadata.audio_streams else None
            )
            av_delta = (
                abs(video_duration - audio_duration)
                if video_duration is not None and audio_duration is not None
                else None
            )
            timeline_duration = segments[-1].end_us if segments else None
            output_delta = (
                abs(metadata.duration_us - timeline_duration)
                if timeline_duration is not None
                else None
            )
            measurements = QCMeasurements(
                black_intervals=black,
                silence_intervals=silence,
                loudness=loudness,
                av_duration_delta_us=av_delta,
                timeline_duration_us=timeline_duration,
                output_duration_delta_us=output_delta,
            )
            if av_delta is not None and av_delta > request.config.qc.max_av_duration_delta_us:
                _finding(
                    findings,
                    QCFindingSeverity.ERROR,
                    "av_duration_mismatch",
                    "Rendered audio and video durations differ beyond the configured tolerance.",
                    actualDeltaUs=av_delta,
                    allowedDeltaUs=request.config.qc.max_av_duration_delta_us,
                )
            if (
                output_delta is not None
                and output_delta > request.config.qc.max_timeline_duration_delta_us
            ):
                _finding(
                    findings,
                    QCFindingSeverity.ERROR,
                    "timeline_duration_mismatch",
                    "Rendered output duration differs from the selected cut-list duration.",
                    actualDeltaUs=output_delta,
                    allowedDeltaUs=request.config.qc.max_timeline_duration_delta_us,
                )

            for position, span in enumerate(black[: request.config.qc.max_detection_findings]):
                midpoint = min(metadata.duration_us - 1, span.start_us + span.duration_us // 2)
                segment = _segment_at(segments, midpoint)
                planned = _range_is_planned(segments, span, {TimelineItemKind.TITLE})
                evidence_name = f"black-{position + 1:04d}.jpg"
                staging_path = staging / "evidence" / evidence_name
                staging_path.parent.mkdir(parents=True, exist_ok=True)
                commands.append(
                    extract_frame(
                        output_path,
                        staging_path,
                        active_runner,
                        timeline_time_us=midpoint,
                    )
                )
                final_evidence = final_root / "evidence" / evidence_name
                evidence.append(
                    QCEvidence(
                        kind="black_frame",
                        path=str(final_evidence),
                        size=staging_path.stat().st_size,
                        sha256=sha256_file(staging_path),
                        timeline_time_us=midpoint,
                        item_id=segment.item.item_id if segment else None,
                    )
                )
                _finding(
                    findings,
                    QCFindingSeverity.INFO if planned else _severity_for_content(request.policy),
                    "planned_black_interval" if planned else "black_interval",
                    "Black interval is contained in an explicit title item."
                    if planned
                    else "A sustained black interval was detected.",
                    item=segment.item if segment else None,
                    timeline_time_us=span.start_us,
                    evidence_path=str(final_evidence),
                    suggested_action=None
                    if planned
                    else "Review the evidence and cut-list timing.",
                    durationUs=span.duration_us,
                )
            for span in silence[: request.config.qc.max_detection_findings]:
                midpoint = span.start_us + span.duration_us // 2
                segment = _segment_at(segments, midpoint)
                planned = _range_is_planned(
                    segments, span, {TimelineItemKind.TITLE, TimelineItemKind.STILL}
                )
                _finding(
                    findings,
                    QCFindingSeverity.INFO if planned else _severity_for_content(request.policy),
                    "planned_silence_interval" if planned else "silence_interval",
                    "Silence is contained in an explicitly silent visual item."
                    if planned
                    else "A sustained silent interval was detected.",
                    item=segment.item if segment else None,
                    timeline_time_us=span.start_us,
                    suggested_action=None
                    if planned
                    else "Review the primary audio at this interval.",
                    durationUs=span.duration_us,
                )
            content_severity = _severity_for_content(request.policy)
            if loudness.integrated_lufs is None or loudness.true_peak_dbtp is None:
                _finding(
                    findings,
                    content_severity,
                    "loudness_unmeasurable",
                    "Output loudness or true peak could not be measured.",
                    suggested_action=(
                        "Review the audio stream and re-render if it is unexpectedly silent."
                    ),
                )
            else:
                integrated_delta = abs(
                    loudness.integrated_lufs - request.config.audio_targets.integrated_lufs
                )
                if integrated_delta > request.config.qc.integrated_lufs_tolerance:
                    _finding(
                        findings,
                        content_severity,
                        "integrated_loudness_out_of_range",
                        "Integrated loudness is outside the configured tolerance.",
                        actual=loudness.integrated_lufs,
                        target=request.config.audio_targets.integrated_lufs,
                        tolerance=request.config.qc.integrated_lufs_tolerance,
                    )
                maximum_peak = (
                    request.config.audio_targets.true_peak_dbtp
                    + request.config.qc.true_peak_tolerance_db
                )
                if loudness.true_peak_dbtp > maximum_peak:
                    _finding(
                        findings,
                        content_severity,
                        "true_peak_exceeded",
                        "True peak exceeds the configured delivery ceiling.",
                        actual=loudness.true_peak_dbtp,
                        maximum=maximum_peak,
                    )

            if segments:
                for position, point in enumerate(
                    _cut_points(segments)[: request.config.qc.max_evidence_cuts]
                ):
                    offset = request.config.qc.cut_evidence_offset_us
                    before = max(0, point - offset)
                    after = min(metadata.duration_us - 1, point + offset)
                    segment = _segment_at(segments, point)
                    for kind, timestamp in (("cut_before", before), ("cut_after", after)):
                        side = "before" if kind == "cut_before" else "after"
                        name = f"cut-{position + 1:04d}-{side}.jpg"
                        staging_path = staging / "evidence" / name
                        staging_path.parent.mkdir(parents=True, exist_ok=True)
                        commands.append(
                            extract_frame(
                                output_path,
                                staging_path,
                                active_runner,
                                timeline_time_us=timestamp,
                            )
                        )
                        final_evidence = final_root / "evidence" / name
                        evidence.append(
                            QCEvidence(
                                kind=cast(Literal["cut_before", "cut_after", "black_frame"], kind),
                                path=str(final_evidence),
                                size=staging_path.stat().st_size,
                                sha256=sha256_file(staging_path),
                                timeline_time_us=timestamp,
                                item_id=segment.item.item_id if segment else None,
                            )
                        )

            if cutlist is not None and segments:
                _check_duplicate_sources(segments, findings)
                _check_text(
                    config=request.config,
                    cutlist=cutlist,
                    cutlist_path=cutlist_path,
                    profile=profile,
                    segments=segments,
                    policy=request.policy,
                    findings=findings,
                )

        state = (
            "failed"
            if any(
                finding.severity in {QCFindingSeverity.ERROR, QCFindingSeverity.BLOCKING}
                for finding in findings
            )
            else "passed"
        )
        report = base_report.model_copy(
            update={
                "state": state,
                "streams": QCStreamSummary(
                    duration_us=metadata.duration_us,
                    video=metadata.video_stream,
                    audio=metadata.audio_streams,
                )
                if metadata is not None
                else None,
                "measurements": measurements,
                "findings": findings,
                "evidence": evidence,
                "ffmpeg_version": tool_version("ffmpeg", active_runner),
                "ffprobe_version": tool_version("ffprobe", active_runner),
                "commands": commands,
                "completed_at": _utc_now(),
            }
        )
        report_path = _write_report(staging, final_root, report)
        return QCResult(
            report=report,
            report_path=report_path,
            checksum_path=report_path.with_name("report.sha256"),
            dry_run=False,
        )
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
