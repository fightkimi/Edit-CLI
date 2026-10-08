from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from interview_edit.adapters.artifacts import validated_video_proxy
from interview_edit.adapters.filesystem import sha256_file
from interview_edit.adapters.media import probe_media
from interview_edit.adapters.process import ProcessRunner, SubprocessRunner
from interview_edit.adapters.qc import extract_frame
from interview_edit.adapters.render import seconds
from interview_edit.adapters.timeline import (
    audio_levels,
    audio_window,
    draw_timeline,
    presentation_times,
)
from interview_edit.config.models import ProjectConfig
from interview_edit.cutlist.audio import audio_range
from interview_edit.cutlist.service import _read_corrected_transcript, load_cutlist
from interview_edit.cutlist.validation import validate_cutlist
from interview_edit.errors import PreflightError, UsageError
from interview_edit.ingest.service import read_media_index
from interview_edit.models.media import MediaAsset, MediaIndex
from interview_edit.models.review import PhraseIndex, ReviewFrame, TimelineReview, TimelineWord
from interview_edit.models.transcript import TranscriptSegment
from interview_edit.project.layout import (
    artifact_path,
    atomic_write_text,
    canonical,
    validate_artifact_path,
)
from interview_edit.proxy.service import validate_source_revision
from interview_edit.qc.service import _selected_segments, canonical_config_sha256, load_render_run
from interview_edit.review.phrases import group_phrases


@dataclass(frozen=True)
class ReviewResult:
    path: Path
    dry_run: bool
    count: int
    warnings: list[str]


def _remember(path: Path, hashes: dict[str, str]) -> None:
    digest = sha256_file(path)
    if str(path) in hashes and hashes[str(path)] != digest:
        raise PreflightError("review_inputs_changed", "A previously captured review input changed.")
    hashes[str(path)] = digest


def _index(config: ProjectConfig, hashes: dict[str, str]) -> MediaIndex:
    _remember(artifact_path(config.artifact_root, "index", "media-index.json"), hashes)
    index = read_media_index(config, required=True, validate_sources=True)
    assert index is not None
    return index


def _transcript(
    config: ProjectConfig, asset: MediaAsset, hashes: dict[str, str]
) -> list[TranscriptSegment]:
    root = artifact_path(config.artifact_root, "transcripts", asset.asset_id)
    for name in ["manifest.json", "corrected.jsonl"]:
        _remember(root / name, hashes)
    return _read_corrected_transcript(config, asset)


def _check_inputs(hashes: dict[str, str], assets: list[MediaAsset]) -> None:
    if any(sha256_file(Path(p)) != digest for p, digest in hashes.items()):
        raise PreflightError(
            "review_inputs_changed", "Review inputs changed; retry with current evidence."
        )
    for asset in assets:
        validate_source_revision(asset)


def phrase_view(
    config: ProjectConfig,
    *,
    asset_ids: list[str] | None = None,
    pause_us: int = 500_000,
    dry_run: bool = False,
) -> ReviewResult:
    if not 1 <= pause_us <= 5_000_000:
        raise UsageError("review_pause_invalid", "Phrase pause must be 1–5000000 microseconds.")
    hashes: dict[str, str] = {}
    index = _index(config, hashes)
    by_id = {a.asset_id: a for a in index.assets}
    selected = (
        asset_ids
        if asset_ids
        else [
            a.asset_id
            for a in index.assets
            if artifact_path(
                config.artifact_root, "transcripts", a.asset_id, "manifest.json"
            ).is_file()
        ]
    )
    if not selected or len(set(selected)) != len(selected) or any(a not in by_id for a in selected):
        raise UsageError(
            "review_assets_invalid", "Select unique indexed assets with completed transcripts."
        )
    assets = [by_id[a] for a in selected]
    phrases = []
    for asset in assets:
        validate_source_revision(asset)
        phrases.extend(group_phrases(asset.asset_id, _transcript(config, asset, hashes), pause_us))
    warnings = ["segment_timing_only"] if any(p.timing == "segment" for p in phrases) else []
    final = artifact_path(config.artifact_root, "review", f"phrases_{uuid4().hex}")
    _check_inputs(hashes, assets)
    if dry_run:
        return ReviewResult(final, True, len(phrases), warnings)
    final.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".phrases-", dir=final.parent))
    try:
        document = PhraseIndex(
            project_id=config.project_id,
            phrases=phrases,
            input_hashes=hashes,
            source_fingerprints={a.asset_id: a.fingerprint for a in assets},
        )
        atomic_write_text(staging / "phrases.json", document.model_dump_json(indent=2))
        lines = [
            "# Source phrase view",
            "",
            "Contains transcript text. Observe project privacy mode.",
            "",
        ]
        for asset in assets:
            lines.extend([f"## {asset.asset_id} ({asset.relative_path})", ""])
            for phrase in (p for p in phrases if p.asset_id == asset.asset_id):
                lines.append(
                    f"[{seconds(phrase.start_us)}–{seconds(phrase.end_us)}] "
                    f"({phrase.timing}; speaker unknown) {phrase.text.replace(chr(10), ' ')}"
                )
            lines.append("")
        atomic_write_text(staging / "phrases.md", "\n".join(lines))
        _check_inputs(hashes, assets)
        os.rename(staging, final)
        return ReviewResult(final, False, len(phrases), warnings)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def timeline_review(
    config: ProjectConfig,
    *,
    focus_us: int,
    window_us: int = 1_500_000,
    asset_id: str | None = None,
    run_id: str | None = None,
    frame_count: int = 8,
    dry_run: bool = False,
    runner: ProcessRunner | None = None,
) -> ReviewResult:
    if (asset_id is None) == (run_id is None):
        raise UsageError("review_target_invalid", "Select exactly one source asset or render run.")
    if not 0 <= focus_us or not 1 <= window_us <= 5_000_000 or not 2 <= frame_count <= 16:
        raise UsageError(
            "review_window_invalid", "Use a nonnegative focus, 1–5000000us radius and 2–16 frames."
        )
    active = runner or SubprocessRunner()
    hashes: dict[str, str] = {}
    index = _index(config, hashes)
    by_id = {a.asset_id: a for a in index.assets}
    used: dict[str, MediaAsset] = {}
    words: list[TimelineWord] = []
    warnings: list[str] = []
    mode: Literal["source", "render"]
    if asset_id:
        if asset_id not in by_id:
            raise UsageError("asset_unknown", "Review asset is not indexed.")
        asset = by_id[asset_id]
        validate_source_revision(asset)
        used[asset_id] = asset
        media = validated_video_proxy(config, asset)
        mode = "source"
        duration = asset.duration_us
        _remember(
            artifact_path(config.artifact_root, "proxies", f"{asset_id}.manifest.json"), hashes
        )
        _remember(media, hashes)
        validated_video_proxy(config, asset)
        segments = None
    else:
        assert run_id is not None
        run, path = load_render_run(config, run_id)
        _remember(path, hashes)
        current_run, _ = load_render_run(config, run_id)
        if current_run != run:
            raise PreflightError("review_inputs_changed", "Render evidence changed while loading.")
        if run.state != "succeeded" or run.output is None:
            raise PreflightError(
                "review_render_incomplete", "Timeline review requires a successful render."
            )
        if canonical_config_sha256(config) != run.config_sha256:
            raise PreflightError("render_config_stale", "Configuration changed since rendering.")
        cutlist = canonical(Path(run.cutlist_path))
        _remember(cutlist, hashes)
        if hashes[str(cutlist)] != run.cutlist_sha256:
            raise PreflightError("render_cutlist_stale", "Cut-list changed since rendering.")
        document = load_cutlist(cutlist)
        validation = validate_cutlist(
            config, document, cutlist_path=cutlist, profile_name=run.profile
        )
        if not validation.ok:
            raise PreflightError(
                "review_cutlist_invalid", "Rendered cut-list evidence is no longer valid."
            )
        segments = _selected_segments(document, run)
        media = validate_artifact_path(Path(run.output.path), config.artifact_root)
        _remember(media, hashes)
        if media.stat().st_size != run.output.size or hashes[str(media)] != run.output.sha256:
            raise PreflightError("render_output_stale", "Rendered video changed after publication.")
        mode = "render"
        duration = run.output.duration_us
        for key, digest in run.input_fingerprints.items():
            kind, _, value = key.partition(":")
            if kind == "source":
                evidence_asset = by_id.get(value)
                if (
                    evidence_asset is None
                    or (evidence_asset.full_hash or evidence_asset.fingerprint) != digest
                ):
                    raise PreflightError("render_input_stale", "Indexed render source changed.")
                used[value] = evidence_asset
                validate_source_revision(evidence_asset)
                continue
            if kind == "proxy":
                input_path = validated_video_proxy(config, by_id[value])
            elif kind == "sync":
                input_path = artifact_path(config.artifact_root, "sync", value, "sync.json")
            elif kind == "file":
                input_path = canonical(Path(value))
            else:
                raise PreflightError("review_input_invalid", "Unknown render input evidence kind.")
            _remember(input_path, hashes)
            if hashes[str(input_path)] != digest:
                raise PreflightError("render_input_stale", "Render input evidence changed.")
    if focus_us >= duration:
        raise UsageError("review_focus_outside", "Focus must be inside the reviewed timeline.")
    start, end = max(0, focus_us - window_us), min(duration, focus_us + window_us)
    if segments is None:
        assert asset_id is not None
        if artifact_path(config.artifact_root, "transcripts", asset_id, "manifest.json").is_file():
            for phrase in group_phrases(
                asset_id, _transcript(config, used[asset_id], hashes), 500_000
            ):
                for word in phrase.words:
                    if word.start_us < end and word.end_us > start:
                        words.append(
                            TimelineWord(
                                asset_id=asset_id,
                                source_start_us=word.start_us,
                                source_end_us=word.end_us,
                                start_us=word.start_us,
                                end_us=word.end_us,
                                text=word.text,
                            )
                        )
        else:
            warnings.append("word_timing_unavailable")
    else:
        for segment in segments:
            if segment.start_us >= end or segment.end_us <= start:
                continue
            interval = audio_range(config, index, segment.item)
            if interval is None:
                continue
            aid, source_start, source_length = interval
            asset = by_id[aid]
            used[aid] = asset
            if not artifact_path(
                config.artifact_root, "transcripts", aid, "manifest.json"
            ).is_file():
                warnings.append("word_timing_unavailable")
                continue
            for phrase in group_phrases(aid, _transcript(config, asset, hashes), 500_000):
                for word in phrase.words:
                    if word.end_us <= source_start or word.start_us >= source_start + source_length:
                        continue
                    clipped = (
                        word.start_us < source_start or word.end_us > source_start + source_length
                    )
                    if clipped:
                        warnings.append("word_clipped_at_cut")
                    begin = (
                        segment.start_us
                        + (max(word.start_us, source_start) - source_start)
                        * segment.item.timeline_duration_us
                        // source_length
                    )
                    finish = (
                        segment.start_us
                        + (min(word.end_us, source_start + source_length) - source_start)
                        * segment.item.timeline_duration_us
                        // source_length
                    )
                    if begin < end and finish > start and finish > begin:
                        words.append(
                            TimelineWord(
                                asset_id=aid,
                                item_id=segment.item.item_id,
                                source_start_us=word.start_us,
                                source_end_us=word.end_us,
                                start_us=begin,
                                end_us=finish,
                                text=word.text,
                                clipped=clipped,
                            )
                        )
    final = artifact_path(config.artifact_root, "review", f"timeline_{uuid4().hex}")
    _check_inputs(hashes, list(used.values()))
    if dry_run:
        return ReviewResult(final, True, len(words), sorted(set(warnings)))
    final.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".timeline-", dir=final.parent))
    try:
        metadata = probe_media(media, active)
        samples = (
            audio_window(media, staging / "window.wav", start, end - start, active)
            if metadata.audio_streams
            else None
        )
        peak, rms = audio_levels(samples) if samples is not None else (None, None)
        frames = []
        paths = []
        available = presentation_times(media, start, end, active)
        desired = [start + (end - start - 1) * i // (frame_count - 1) for i in range(frame_count)]
        times = [
            max((t for t in available if t <= target), default=available[0]) for target in desired
        ]
        for position, time in enumerate(times):
            path = staging / f"frame-{position:02d}.jpg"
            extract_frame(media, path, active, timeline_time_us=time)
            paths.append(path)
            frames.append(
                ReviewFrame(time_us=time, path=str(final / path.name), sha256=sha256_file(path))
            )
        image = staging / "timeline.png"
        font = config.fonts[0] if config.fonts else None
        if font is not None:
            _remember(font, hashes)
        if font is None and any(any(ord(c) > 255 for c in word.text) for word in words):
            raise PreflightError(
                "review_font_required", "Declare a local font for non-Latin word labels."
            )
        draw_timeline(paths, times, samples, words, start, end, focus_us, image, font)
        report = TimelineReview(
            project_id=config.project_id,
            mode=mode,
            media_path=str(media),
            media_sha256=hashes[str(media)],
            start_us=start,
            end_us=end,
            focus_us=focus_us,
            words=words,
            frames=frames,
            image_path=str(final / image.name),
            image_sha256=sha256_file(image),
            audio_status="decoded" if samples is not None else "missing",
            audio_path=str(final / "window.wav") if samples is not None else None,
            audio_sha256=sha256_file(staging / "window.wav") if samples is not None else None,
            peak_dbfs=peak,
            rms_dbfs=rms,
            input_hashes=hashes,
            source_fingerprints={a.asset_id: a.fingerprint for a in used.values()},
            warnings=sorted(set(warnings)),
        )
        atomic_write_text(staging / "report.json", report.model_dump_json(indent=2))
        _check_inputs(hashes, list(used.values()))
        if asset_id is not None:
            validated_video_proxy(config, used[asset_id])
        os.rename(staging, final)
        return ReviewResult(final, False, len(words), report.warnings)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
