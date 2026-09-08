from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError

from interview_edit.adapters.filesystem import sha256_file
from interview_edit.config.models import ProjectConfig
from interview_edit.cutlist.captions import split_subtitle
from interview_edit.errors import PathSafetyError, PreflightError, UsageError
from interview_edit.ingest.service import read_media_index
from interview_edit.models.cutlist import Act, CutList, Subtitle, TimelineItem, TimelineItemKind
from interview_edit.models.media import MediaAsset
from interview_edit.models.transcript import TranscriptManifest, TranscriptSegment
from interview_edit.project.layout import artifact_path, atomic_write_text, canonical, is_within


@dataclass(frozen=True)
class ScaffoldRequest:
    config: ProjectConfig
    project_root: Path
    asset_id: str | None = None
    output: Path | None = None
    force: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class ScaffoldResult:
    cutlist: CutList
    output_path: Path
    from_transcript: bool
    dry_run: bool
    estimated_subtitle_count: int = 0


def resolve_cutlist_path(project_root: Path, path: Path) -> Path:
    candidate = path.expanduser()
    return canonical(project_root / candidate if not candidate.is_absolute() else candidate)


def load_cutlist(path: Path) -> CutList:
    resolved = canonical(path)
    try:
        content = resolved.read_bytes()
    except OSError as exc:
        raise PreflightError(
            "cutlist_read_failed", "Could not read cut-list.", details={"path": str(resolved)}
        ) from exc
    return parse_cutlist(content, resolved)


def parse_cutlist(content: bytes, path: Path) -> CutList:
    """Parse exactly the bytes whose hash identifies an editing decision snapshot."""
    resolved = canonical(path)
    try:
        loaded: object = yaml.safe_load(content.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError) as exc:
        raise PreflightError(
            "cutlist_read_failed",
            f"Could not read cut-list: {resolved}",
            details={"path": str(resolved), "reason": str(exc)},
        ) from exc
    if not isinstance(loaded, dict):
        raise PreflightError(
            "cutlist_invalid",
            "Cut-list must contain a YAML mapping.",
            details={"path": str(resolved)},
        )
    try:
        return CutList.model_validate(cast(dict[str, Any], loaded))
    except ValidationError as exc:
        raise PreflightError(
            "cutlist_invalid",
            "Cut-list does not conform to schema version 1.",
            details={
                "path": str(resolved),
                "errors": exc.errors(include_url=False, include_context=False),
            },
        ) from exc


def serialize_cutlist(cutlist: CutList) -> str:
    return yaml.safe_dump(
        cutlist.model_dump(mode="json", exclude_none=True),
        allow_unicode=True,
        sort_keys=False,
    )


def _read_corrected_transcript(
    config: ProjectConfig,
    asset: MediaAsset,
) -> list[TranscriptSegment]:
    root = artifact_path(config.artifact_root, "transcripts", asset.asset_id)
    path = root / "corrected.jsonl"
    try:
        manifest = TranscriptManifest.model_validate_json(
            (root / "manifest.json").read_text(encoding="utf-8")
        )
        output = next(
            (
                value
                for value in manifest.outputs
                if value.kind == "corrected_jsonl"
                and canonical(Path(value.path)) == canonical(path)
            ),
            None,
        )
        valid = (
            manifest.asset_id == asset.asset_id
            and manifest.source_fingerprint == asset.fingerprint
            and manifest.source_full_hash == asset.full_hash
            and output is not None
            and path.stat().st_size == output.size
            and sha256_file(path) == output.sha256
        )
        if not valid:
            raise ValueError("transcript manifest or output checksum does not match")
        lines = path.read_text(encoding="utf-8").splitlines()
        return [TranscriptSegment.model_validate_json(line) for line in lines if line.strip()]
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise PreflightError(
            "corrected_transcript_required",
            "A valid corrected transcript is required for transcript scaffolding.",
            details={"assetId": asset.asset_id, "path": str(path)},
        ) from exc


def scaffold_cutlist(request: ScaffoldRequest) -> ScaffoldResult:
    project_root = canonical(request.project_root)
    output = resolve_cutlist_path(
        project_root,
        request.output or Path("cutlists/revisions/cutlist-v001.yaml"),
    )
    if not is_within(output, project_root):
        raise PathSafetyError(
            "cutlist_output_outside_project",
            "Cut-list output must remain inside the editing project.",
            details={"path": str(output), "projectRoot": str(project_root)},
        )
    for media_root in request.config.media_roots:
        if is_within(output, media_root):
            raise PathSafetyError(
                "cutlist_output_in_media_root",
                "Cut-list output must not be written inside a source-media root.",
                details={"path": str(output), "mediaRoot": str(media_root)},
            )
    if output.exists() and not request.force:
        raise PathSafetyError(
            "cutlist_output_exists",
            "Cut-list already exists; pass --force to replace it.",
            details={"path": str(output)},
        )

    items: list[TimelineItem] = []
    estimated_count = 0
    if request.asset_id is not None:
        index = read_media_index(request.config)
        assert index is not None
        asset = next((item for item in index.assets if item.asset_id == request.asset_id), None)
        if asset is None:
            raise UsageError(
                "asset_unknown",
                f"Asset is not present in the media index: {request.asset_id}",
                details={"assetId": request.asset_id},
            )
        segments = _read_corrected_transcript(request.config, asset)
        for position, segment in enumerate(segments, start=1):
            duration = segment.end_us - segment.start_us
            if duration <= 0:
                continue
            subtitle = Subtitle(
                subtitle_id=f"subtitle_{position:04d}",
                start_us=0,
                duration_us=duration,
                text=segment.text,
            )
            subtitles, estimated = split_subtitle(
                subtitle, words=segment.words, source_in_us=segment.start_us
            )
            estimated_count += len(subtitles) if estimated else 0
            items.append(
                TimelineItem(
                    item_id=f"item_{position:04d}",
                    kind=TimelineItemKind.PRIMARY,
                    source_id=asset.asset_id,
                    source_in_us=segment.start_us,
                    source_out_us=segment.end_us,
                    timeline_duration_us=duration,
                    audio_source=asset.asset_id if asset.audio_streams else None,
                    base_camera=asset.camera_id,
                    subtitles=subtitles,
                )
            )

    cutlist = CutList(
        project_id=request.config.project_id,
        timeline=request.config.timeline,
        acts=[Act(act_id="act_001", items=items)],
        render_profile="preview",
    )
    if not request.dry_run:
        atomic_write_text(output, serialize_cutlist(cutlist))
    return ScaffoldResult(
        cutlist=cutlist,
        output_path=output,
        from_transcript=request.asset_id is not None,
        dry_run=request.dry_run,
        estimated_subtitle_count=estimated_count,
    )


def inspect_cutlist(
    cutlist: CutList,
    *,
    cutlist_path: Path,
    act_id: str | None = None,
    item_id: str | None = None,
) -> dict[str, Any]:
    selected_acts = cutlist.acts
    if act_id is not None:
        selected_acts = [act for act in cutlist.acts if act.act_id == act_id]
        if not selected_acts:
            raise UsageError(
                "act_unknown",
                f"Act is not present in the cut-list: {act_id}",
                details={"actId": act_id},
            )

    records: list[dict[str, Any]] = []
    for act in selected_acts:
        for item in act.items:
            if item_id is not None and item.item_id != item_id:
                continue
            records.append(
                {
                    "actId": act.act_id,
                    "itemId": item.item_id,
                    "kind": item.kind.value,
                    "contentRole": item.content_role,
                    "sourceId": item.source_id,
                    "durationUs": item.timeline_duration_us,
                    "cameraCutCount": len(item.camera_cuts),
                    "overlayCount": len(item.overlays),
                    "subtitleCount": len(item.subtitles),
                    "hasTransitionIn": item.transition_in is not None,
                    "hasTransitionOut": item.transition_out is not None,
                }
            )
    if item_id is not None and not records:
        raise UsageError(
            "item_unknown",
            f"Item is not present in the selected cut-list scope: {item_id}",
            details={"itemId": item_id, "actId": act_id},
        )
    return {
        "cutlistPath": str(canonical(cutlist_path)),
        "projectId": cutlist.project_id,
        "renderProfile": cutlist.render_profile,
        "timeline": cutlist.timeline.model_dump(mode="json"),
        "actCount": len(selected_acts),
        "itemCount": len(records),
        "timelineDurationUs": sum(record["durationUs"] for record in records),
        "items": records,
    }
