from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from interview_edit.config.models import ProjectConfig
from interview_edit.cutlist.captions import compact, split_subtitle
from interview_edit.cutlist.service import _read_corrected_transcript, serialize_cutlist
from interview_edit.cutlist.validation import validate_cutlist
from interview_edit.errors import PathSafetyError, PreflightError, UsageError
from interview_edit.ingest.service import read_media_index
from interview_edit.models.cutlist import CameraCut, CutList, Overlay, Subtitle, TimelineItem
from interview_edit.models.transcript import TranscriptWord
from interview_edit.project.layout import (
    artifact_path,
    atomic_write_text,
    canonical,
    validate_artifact_path,
)
from interview_edit.proxy.service import validate_source_revision


@dataclass(frozen=True)
class RevisionResult:
    output_path: Path
    item_ids: list[str]
    warnings: list[dict[str, Any]]
    dry_run: bool


def revise_item_range(item: TimelineItem, source_in_us: int, source_out_us: int) -> TimelineItem:
    if item.kind not in {"primary", "broll"} or item.source_in_us is None:
        raise UsageError("item_source_required", "Range changes require a source-backed item.")
    if source_in_us < 0 or source_out_us <= source_in_us:
        raise UsageError("source_range_invalid", "Provide a nonnegative, increasing source range.")
    duration = source_out_us - source_in_us
    shift = item.source_in_us - source_in_us
    payload = item.model_dump(mode="python")
    for name in ("camera_cuts", "overlays", "subtitles"):
        revised: list[CameraCut | Overlay | Subtitle] = []
        for span in getattr(item, name):
            left = span.start_us + shift
            right = span.end_us + shift
            start, end = max(0, left), min(duration, right)
            if end <= start:
                continue
            if name == "subtitles" and (start != left or end != right):
                raise PreflightError(
                    "subtitle_partial_trim",
                    "A boundary cuts through an existing subtitle; split or revise that cue first.",
                    details={"itemId": item.item_id, "subtitleId": span.subtitle_id},
                )
            updates: dict[str, Any] = {"start_us": start, "duration_us": end - start}
            if isinstance(span, Overlay) and span.kind == "broll":
                assert span.source_in_us is not None
                updates["source_in_us"] = span.source_in_us + start - left
                updates["source_out_us"] = updates["source_in_us"] + end - start
            revised.append(type(span).model_validate({**span.model_dump(), **updates}))
        payload[name] = revised
    payload.update(
        source_in_us=source_in_us, source_out_us=source_out_us, timeline_duration_us=duration
    )
    return TimelineItem.model_validate(payload)


def speech_boundaries(item: TimelineItem, words: list[TranscriptWord]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for edge, boundary in (("in", item.source_in_us), ("out", item.source_out_us)):
        if boundary is None:
            continue
        crossing = [w for w in words if w.start_us < boundary < w.end_us]
        if crossing:
            suggested = (
                min(w.start_us for w in crossing)
                if edge == "in"
                else max(w.end_us for w in crossing)
            )
            findings.append(
                {
                    "code": "speech_cut_inside_word",
                    "itemId": item.item_id,
                    "edge": edge,
                    "sourceUs": boundary,
                    "suggestedUs": suggested,
                }
            )
    return findings


def _items(document: CutList, item_id: str | None) -> list[TimelineItem]:
    items = [
        i for act in document.acts for i in act.items if item_id is None or i.item_id == item_id
    ]
    if not items:
        raise UsageError(
            "item_unknown", "No items match the selected scope.", details={"itemId": item_id}
        )
    return items


def _words(config: ProjectConfig, document: CutList) -> dict[str, list[TranscriptWord]]:
    if document.project_id != config.project_id:
        raise PreflightError("cutlist_project_mismatch", "Cut-list belongs to a different project.")
    index = read_media_index(config, required=True, validate_sources=True)
    assert index is not None
    assets = {a.asset_id: a for a in index.assets}
    by_source: dict[str, list[TranscriptWord]] = {}
    for item in _items(document, None):
        source_id = item.source_id
        if source_id is None or source_id in by_source:
            continue
        asset = assets.get(source_id)
        if asset is None:
            raise PreflightError("source_unknown", "Cut-list references an unknown source.")
        validate_source_revision(asset)
        manifest = artifact_path(config.artifact_root, "transcripts", source_id, "manifest.json")
        if not manifest.exists():
            by_source[source_id] = []
            continue
        segments = _read_corrected_transcript(config, asset)
        by_source[source_id] = [w for segment in segments for w in segment.words]
    return by_source


def check_speech(
    config: ProjectConfig, document: CutList, item_id: str | None = None
) -> dict[str, Any]:
    by_source = _words(config, document)
    findings: list[dict[str, Any]] = []
    unknown: list[str] = []
    checked = 0
    for item in _items(document, item_id):
        if item.kind not in {"primary", "broll"}:
            continue
        words = by_source.get(item.source_id or "", [])
        covered = any(
            w.end_us > (item.source_in_us or 0) and w.start_us < (item.source_out_us or 0)
            for w in words
        )
        if not covered or item.audio_source not in {None, item.source_id}:
            unknown.append(item.item_id)
            continue
        checked += 1
        findings.extend(speech_boundaries(item, words))
    return {
        "ok": not findings,
        "wordBoundaryStatus": "needs_revision"
        if findings
        else ("unverified" if unknown else "clear"),
        "checkedItemCount": checked,
        "unverifiedItemIds": unknown,
        "findings": findings,
        "listeningVerified": False,
    }


def _rebase_assets(document: CutList, original: Path) -> None:
    for item in _items(document, None):
        for entry in [item, *item.overlays, *item.subtitles]:
            for field in ("font_path", "image_path"):
                value = getattr(entry, field, None)
                if value:
                    path = Path(value).expanduser()
                    setattr(
                        entry,
                        field,
                        str(canonical(path if path.is_absolute() else original.parent / path)),
                    )


def publish_revision(
    config: ProjectConfig,
    original_path: Path,
    document: CutList,
    *,
    output: Path | None,
    dry_run: bool,
    item_ids: list[str],
    warnings: list[dict[str, Any]],
) -> RevisionResult:
    root = artifact_path(config.artifact_root, "cutlists", "revisions")
    requested = (
        output if output is not None else Path(f"{original_path.stem}-{uuid4().hex[:12]}.yaml")
    )
    path = requested if requested.is_absolute() else root / requested
    path = validate_artifact_path(path, root)
    if path.suffix not in {".yaml", ".yml"}:
        raise UsageError("cutlist_output_invalid", "Revision output must be a YAML file.")
    if path.exists():
        raise PathSafetyError(
            "cutlist_output_exists", "Choose a new revision output; overwriting is disabled."
        )
    _rebase_assets(document, original_path)
    report = validate_cutlist(config, document, cutlist_path=path)
    if not report.ok:
        raise PreflightError(
            "cutlist_validation_failed",
            "The revision failed validation; nothing was written.",
            details={"issues": [i.model_dump(mode="json") for i in report.issues]},
        )
    warnings.extend(i.model_dump(mode="json") for i in report.issues if i.severity == "warning")
    if not dry_run:
        atomic_write_text(path, serialize_cutlist(document), overwrite=False)
    return RevisionResult(path, item_ids, warnings, dry_run)


def set_source_range(
    config: ProjectConfig,
    document: CutList,
    original_path: Path,
    *,
    item_id: str,
    source_in_us: int,
    source_out_us: int,
    output: Path | None = None,
    dry_run: bool = False,
) -> RevisionResult:
    if document.project_id != config.project_id:
        raise PreflightError("cutlist_project_mismatch", "Cut-list belongs to a different project.")
    _items(document, item_id)
    revised = document.model_copy(deep=True)
    for act in revised.acts:
        act.items = [
            revise_item_range(i, source_in_us, source_out_us) if i.item_id == item_id else i
            for i in act.items
        ]
    speech = check_speech(config, revised, item_id)
    if speech["findings"]:
        raise PreflightError(
            "speech_boundary_invalid", "New range cuts through a word.", details=speech
        )
    warnings = (
        [
            {
                "code": "speech_timing_unavailable",
                "message": "Word timing is unavailable; review the join.",
                "details": {"itemIds": speech["unverifiedItemIds"]},
            }
        ]
        if speech["unverifiedItemIds"]
        else []
    )
    return publish_revision(
        config,
        original_path,
        revised,
        output=output,
        dry_run=dry_run,
        item_ids=[item_id],
        warnings=warnings,
    )


def split_captions(
    config: ProjectConfig,
    document: CutList,
    original_path: Path,
    *,
    item_id: str | None = None,
    max_chars: int = 18,
    min_duration_us: int = 0,
    pause_us: int = 0,
    max_chars_per_second: int = 20,
    style: Literal["standard", "minimal"] | None = None,
    output: Path | None = None,
    dry_run: bool = False,
) -> RevisionResult:
    if item_id is not None and style is not None:
        raise UsageError(
            "caption_style_scope_invalid",
            "Style applies to the whole cut-list; do not combine --style with --item.",
        )
    revised = document.model_copy(deep=True)
    selected = _items(revised, item_id)
    by_source = _words(config, revised)
    warnings: list[dict[str, Any]] = []
    occupied: set[str] = set()
    for act in revised.acts:
        occupied.add(act.act_id)
        for existing in act.items:
            occupied.add(existing.item_id)
            occupied.update(cut.cut_id for cut in existing.camera_cuts)
            occupied.update(overlay.overlay_id for overlay in existing.overlays)
            occupied.update(cue.subtitle_id for cue in existing.subtitles)
    for item in selected:
        cues: list[Subtitle] = []
        words = (
            by_source.get(item.source_id or "", [])
            if item.audio_source in {None, item.source_id}
            else []
        )
        for subtitle in item.subtitles:
            parts, estimated = split_subtitle(
                subtitle,
                words=words,
                source_in_us=item.source_in_us or 0,
                max_chars=max_chars,
                min_duration_us=min_duration_us,
                pause_us=pause_us,
            )
            occupied.discard(subtitle.subtitle_id)
            for part in parts:
                base = part.subtitle_id
                suffix = 0
                while part.subtitle_id in occupied:
                    suffix += 1
                    part.subtitle_id = f"{base}.part{suffix}"
                occupied.add(part.subtitle_id)
            cues.extend(parts)
            if estimated:
                warnings.append(
                    {
                        "code": "subtitle_timing_estimated",
                        "message": "Cue timing is estimated from existing duration; review it.",
                        "details": {"itemId": item.item_id, "subtitleId": subtitle.subtitle_id},
                    }
                )
            if any(
                len(compact(cue.text)) * 1_000_000 > max_chars_per_second * cue.duration_us
                for cue in parts
            ):
                warnings.append(
                    {
                        "code": "subtitle_readability_review",
                        "message": "A cue exceeds the configured reading-speed heuristic.",
                        "details": {"itemId": item.item_id, "subtitleId": subtitle.subtitle_id},
                    }
                )
            if any(cue.duration_us < min_duration_us for cue in parts):
                warnings.append(
                    {
                        "code": "subtitle_display_too_short",
                        "message": "Cue bounds or pauses prevent the minimum display time.",
                        "details": {"itemId": item.item_id, "subtitleId": subtitle.subtitle_id},
                    }
                )
        item.subtitles = cues
    if style is not None:
        revised.subtitle_policy.style = style
    return publish_revision(
        config,
        original_path,
        revised,
        output=output,
        dry_run=dry_run,
        item_ids=[i.item_id for i in selected],
        warnings=warnings,
    )


def set_audio_policy(
    config: ProjectConfig,
    document: CutList,
    original_path: Path,
    *,
    edge_fade_us: int,
    output: Path | None = None,
    dry_run: bool = False,
) -> RevisionResult:
    if not 0 <= edge_fade_us <= 50_000:
        raise UsageError("audio_edge_fade_invalid", "Edge fade must be 0–50000 microseconds.")
    revised = document.model_copy(deep=True)
    revised.audio_policy.edge_fade_us = edge_fade_us
    return publish_revision(
        config,
        original_path,
        revised,
        output=output,
        dry_run=dry_run,
        item_ids=[i.item_id for i in _items(revised, None)],
        warnings=[],
    )
