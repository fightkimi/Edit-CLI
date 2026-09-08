from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from interview_edit.adapters.artifacts import validated_video_proxy
from interview_edit.adapters.filesystem import sha256_file
from interview_edit.adapters.media import tool_version
from interview_edit.adapters.process import ProcessRunner, SubprocessRunner
from interview_edit.adapters.render import (
    concat_entry,
    run_render_command,
    seconds,
    select_video_encoder,
    video_codec_args,
)
from interview_edit.adapters.text import render_text_png
from interview_edit.config.models import ProjectConfig, RenderProfile
from interview_edit.cutlist.timing import map_source_range, visual_intervals
from interview_edit.cutlist.validation import validate_cutlist
from interview_edit.errors import InterviewEditError, PathSafetyError, PreflightError, UsageError
from interview_edit.ingest.service import read_media_index
from interview_edit.models.cutlist import (
    CutList,
    OverlayKind,
    TimelineItem,
    TimelineItemKind,
)
from interview_edit.models.media import MediaAsset, MediaIndex
from interview_edit.models.render import (
    RenderCacheEntry,
    RenderCommand,
    RenderItemManifest,
    RenderOutput,
    RenderRunManifest,
)
from interview_edit.project.layout import (
    artifact_path,
    atomic_write_text,
    canonical,
    is_within,
    validate_artifact_path,
)
from interview_edit.proxy.service import validate_source_revision


@dataclass(frozen=True)
class RenderRequest:
    config: ProjectConfig
    project_root: Path
    cutlist: CutList
    cutlist_path: Path
    act_id: str | None = None
    item_id: str | None = None
    profile_name: str | None = None
    output: Path | None = None
    resume: bool = False
    force: bool = False
    dry_run: bool = False
    context_items: int = 0


@dataclass(frozen=True)
class RenderResult:
    run_id: str | None
    output_path: Path
    output: RenderOutput | None
    manifest_path: Path | None
    cache: list[RenderCacheEntry]
    dry_run: bool


@dataclass(frozen=True)
class _SelectedItem:
    act_id: str
    item: TimelineItem


@dataclass
class _CommandLog:
    commands: list[RenderCommand]

    def run(
        self,
        args: list[str],
        runner: ProcessRunner,
        *,
        purpose: str,
    ) -> tuple[str, str]:
        try:
            command, stdout, stderr = run_render_command(args, runner, purpose=purpose)
        except KeyboardInterrupt:
            self.commands.append(
                RenderCommand(
                    purpose=purpose,
                    args=["ffmpeg", *args],
                    return_code=130,
                )
            )
            raise
        except InterviewEditError as exc:
            raw_args = exc.details.get("args")
            return_code = exc.details.get("returnCode")
            if isinstance(raw_args, list) and isinstance(return_code, int):
                self.commands.append(
                    RenderCommand(
                        purpose=purpose,
                        args=[str(value) for value in raw_args],
                        return_code=return_code,
                    )
                )
            raise
        self.commands.append(command)
        return stdout, stderr


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"render_{stamp}_{uuid.uuid4().hex[:10]}"


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _select_items(
    cutlist: CutList, act_id: str | None, item_id: str | None, context_items: int = 0
) -> list[_SelectedItem]:
    if context_items < 0 or context_items > 2 or (context_items and item_id is None):
        raise UsageError(
            "render_context_invalid", "Context requires --item and a count from 0 to 2."
        )
    acts = cutlist.acts
    if act_id is not None:
        acts = [act for act in acts if act.act_id == act_id]
        if not acts:
            raise UsageError(
                "act_unknown",
                f"Act is not present in the cut-list: {act_id}",
                details={"actId": act_id},
            )
    selected = [
        _SelectedItem(act.act_id, item)
        for act in acts
        for item in act.items
        if item_id is None or item.item_id == item_id
    ]
    if item_id is not None and not selected:
        raise UsageError(
            "item_unknown",
            f"Item is not present in the selected cut-list scope: {item_id}",
            details={"itemId": item_id, "actId": act_id},
        )
    if not selected:
        raise PreflightError("render_selection_empty", "The selected cut-list scope has no items.")
    if context_items:
        ordered = [_SelectedItem(act.act_id, item) for act in acts for item in act.items]
        position = next(i for i, value in enumerate(ordered) if value.item.item_id == item_id)
        return ordered[max(0, position - context_items) : position + context_items + 1]
    return selected


def _output_path(request: RenderRequest, profile_name: str) -> Path:
    if request.output is not None:
        candidate = request.output.expanduser()
        requested = request.project_root / candidate if not candidate.is_absolute() else candidate
        output = canonical(requested)
        if not is_within(output, request.config.artifact_root):
            raise PathSafetyError(
                "render_output_outside_artifacts",
                "Render output must remain inside the configured artifact root.",
                details={"path": str(output), "artifactRoot": str(request.config.artifact_root)},
            )
        output = validate_artifact_path(requested, request.config.artifact_root)
    else:
        suffixes = [request.cutlist_path.stem]
        if request.act_id:
            suffixes.append(request.act_id)
        if request.item_id:
            suffixes.append(request.item_id)
        if request.context_items:
            suffixes.append(f"context{request.context_items}")
        suffixes.append(profile_name)
        output = artifact_path(request.config.artifact_root, "renders", "-".join(suffixes) + ".mp4")
    if output.suffix.lower() != ".mp4":
        raise UsageError(
            "render_output_container_unsupported",
            "M4 render output must use the .mp4 container.",
            details={"path": str(output)},
        )
    internal_roots = (
        artifact_path(request.config.artifact_root, "renders", "cache"),
        artifact_path(request.config.artifact_root, "renders", "runs"),
    )
    if any(is_within(output, root) for root in internal_roots):
        raise PathSafetyError(
            "render_output_reserved",
            "Render output may not target an internal cache or run-manifest directory.",
            details={"path": str(output)},
        )
    return output


def _asset_path(config: ProjectConfig, asset: MediaAsset, profile_name: str) -> Path:
    if profile_name == "preview":
        return validated_video_proxy(config, asset)
    validate_source_revision(asset)
    return canonical(Path(asset.canonical_path))


def _resolved_path(cutlist_path: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return canonical(cutlist_path.parent / path if not path.is_absolute() else path)


def _font_path(
    config: ProjectConfig,
    cutlist_path: Path,
    *values: str | None,
) -> Path:
    selected = next((value for value in values if value), None)
    if selected is not None:
        return _resolved_path(cutlist_path, selected)
    if config.fonts:
        return canonical(config.fonts[0])
    raise PreflightError("font_required", "A local font is required for text rendering.")


def _text_raster(
    *,
    config: ProjectConfig,
    cutlist_path: Path,
    text: str,
    font_path: Path,
    profile: RenderProfile,
    placement: str,
    safe_area_percent: int,
    style: Literal["standard", "minimal"] = "standard",
) -> Path:
    font_hash = sha256_file(font_path)
    cache_key = _canonical_hash(
        {
            "schema": "text-raster-v3",
            "text": text,
            "fontSha256": font_hash,
            "width": profile.width,
            "height": profile.height,
            "placement": placement,
            "safeAreaPercent": safe_area_percent,
            "style": style,
        }
    )
    path = artifact_path(config.artifact_root, "renders", "cache", "text", f"{cache_key}.png")
    if not path.is_file():
        render_text_png(
            text=text,
            font_path=font_path,
            output_path=path,
            width=profile.width,
            height=profile.height,
            placement="subtitle" if placement == "subtitle" else "center",
            safe_area_percent=safe_area_percent,
            style=style,
        )
    return path


def _normal_video_filter(profile: RenderProfile) -> str:
    return (
        f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=decrease,"
        f"pad={profile.width}:{profile.height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={profile.frame_rate},format=yuv420p"
    )


def _add_media_input(args: list[str], path: Path, start_us: int, duration_us: int) -> int:
    index = sum(value == "-i" for value in args)
    args.extend(["-ss", seconds(start_us), "-t", seconds(duration_us), "-i", str(path)])
    return index


def _add_image_input(args: list[str], path: Path, duration_us: int) -> int:
    index = sum(value == "-i" for value in args)
    args.extend(["-loop", "1", "-t", seconds(duration_us), "-i", str(path)])
    return index


def _add_lavfi_input(args: list[str], expression: str, duration_us: int) -> int:
    index = sum(value == "-i" for value in args)
    args.extend(["-f", "lavfi", "-t", seconds(duration_us), "-i", expression])
    return index


def _overlay_filter(
    current: str,
    overlay_label: str,
    output_label: str,
    start_us: int,
    duration_us: int,
) -> str:
    return (
        f"[{current}][{overlay_label}]overlay=eof_action=pass:shortest=0:"
        f"enable='between(t,{seconds(start_us)},{seconds(start_us + duration_us)})'"
        f"[{output_label}]"
    )


def _item_input_fingerprints(
    *,
    config: ProjectConfig,
    cutlist_path: Path,
    item: TimelineItem,
    source: MediaAsset | None,
    assets: dict[str, MediaAsset],
    profile_name: str,
) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    referenced_ids = {value for value in (item.source_id, item.audio_source) if value}
    referenced_ids.update(
        overlay.source_id for overlay in item.overlays if overlay.source_id is not None
    )
    if source is not None and item.camera_cuts and source.take_id is not None:
        wanted = {cut.camera_id for cut in item.camera_cuts}
        if item.base_camera:
            wanted.add(item.base_camera)
        referenced_ids.update(
            asset.asset_id
            for asset in assets.values()
            if asset.take_id == source.take_id and asset.camera_id in wanted
        )
        sync_path = artifact_path(config.artifact_root, "sync", source.take_id, "sync.json")
        fingerprints[f"sync:{source.take_id}"] = sha256_file(sync_path)
    for asset_id in sorted(referenced_ids):
        asset = assets[asset_id]
        identity = asset.full_hash or asset.fingerprint
        fingerprints[f"source:{asset_id}"] = identity
        if profile_name == "preview":
            proxy = validated_video_proxy(config, asset)
            fingerprints[f"proxy:{asset_id}"] = sha256_file(proxy)
    local_paths: set[Path] = set()
    if item.image_path:
        local_paths.add(_resolved_path(cutlist_path, item.image_path))
    if item.font_path:
        local_paths.add(_resolved_path(cutlist_path, item.font_path))
    for overlay in item.overlays:
        if overlay.image_path:
            local_paths.add(_resolved_path(cutlist_path, overlay.image_path))
        if overlay.font_path:
            local_paths.add(_resolved_path(cutlist_path, overlay.font_path))
    for subtitle in item.subtitles:
        if subtitle.font_path:
            local_paths.add(_resolved_path(cutlist_path, subtitle.font_path))
    text_present = (
        item.kind is TimelineItemKind.TITLE
        or bool(item.subtitles)
        or any(overlay.kind is OverlayKind.TITLE for overlay in item.overlays)
    )
    if text_present:
        declared_fonts = [
            item.font_path,
            *(overlay.font_path for overlay in item.overlays if overlay.kind is OverlayKind.TITLE),
            *(subtitle.font_path for subtitle in item.subtitles),
        ]
        font = _font_path(config, cutlist_path, *declared_fonts)
        local_paths.add(font)
    for path in sorted(local_paths):
        fingerprints[f"file:{path}"] = sha256_file(path)
    return fingerprints


def _cache_manifest(path: Path, cache_key: str) -> RenderItemManifest | None:
    try:
        manifest = RenderItemManifest.model_validate_json(path.read_text(encoding="utf-8"))
        output = Path(manifest.output_path)
        if (
            manifest.cache_key != cache_key
            or not output.is_file()
            or output.stat().st_size != manifest.output_size
            or sha256_file(output) != manifest.output_sha256
        ):
            return None
        return manifest
    except (OSError, UnicodeError, ValidationError):
        return None


def _audio_asset(
    item: TimelineItem,
    source: MediaAsset | None,
    assets: dict[str, MediaAsset],
) -> MediaAsset | None:
    if item.audio_source is not None:
        return assets[item.audio_source]
    if source is not None and source.audio_streams:
        return source
    return None


def _build_item(
    *,
    request: RenderRequest,
    item: TimelineItem,
    index: MediaIndex,
    profile_name: str,
    profile: RenderProfile,
    encoder: str,
    cache_key: str,
    runner: ProcessRunner,
    command_log: _CommandLog,
) -> RenderItemManifest:
    assets = {asset.asset_id: asset for asset in index.assets}
    source = assets.get(item.source_id or "")
    cache_root = artifact_path(request.config.artifact_root, "renders", "cache", "items")
    output = cache_root / f"{cache_key}.mp4"
    manifest_path = cache_root / f"{cache_key}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{item.item_id}.", suffix=".mp4", dir=cache_root, delete=False
    ) as handle:
        temporary = Path(handle.name)
    local_commands_start = len(command_log.commands)
    try:
        args = ["-nostdin", "-hide_banner", "-loglevel", "error"]
        filters: list[str] = []
        video_labels: list[str] = []

        if item.kind in {TimelineItemKind.PRIMARY, TimelineItemKind.BROLL}:
            assert source is not None
            intervals = visual_intervals(request.config, index, item, source, assets)
            for position, interval in enumerate(intervals):
                path = _asset_path(request.config, interval.asset, profile_name)
                input_index = _add_media_input(
                    args, path, interval.source_start_us, interval.source_duration_us
                )
                label = f"base{position}"
                ratio = Fraction(interval.duration_us, interval.source_duration_us)
                filters.append(
                    f"[{input_index}:v:0]setpts=(PTS-STARTPTS)*{float(ratio):.12f},"
                    f"{_normal_video_filter(profile)},trim=duration={seconds(interval.duration_us)},"
                    f"setpts=PTS-STARTPTS[{label}]"
                )
                video_labels.append(label)
            if len(video_labels) == 1:
                current_video = video_labels[0]
            else:
                joined = "".join(f"[{label}]" for label in video_labels)
                filters.append(f"{joined}concat=n={len(video_labels)}:v=1:a=0[vbase]")
                current_video = "vbase"
        elif item.kind is TimelineItemKind.STILL:
            assert item.image_path is not None
            image = _resolved_path(request.cutlist_path, item.image_path)
            input_index = _add_image_input(args, image, item.timeline_duration_us)
            filters.append(
                f"[{input_index}:v:0]{_normal_video_filter(profile)},"
                f"trim=duration={seconds(item.timeline_duration_us)},setpts=PTS-STARTPTS[base0]"
            )
            current_video = "base0"
        elif item.kind is TimelineItemKind.TITLE:
            expression = (
                f"color=c=black:s={profile.width}x{profile.height}:"
                f"r={profile.frame_rate}:d={seconds(item.timeline_duration_us)}"
            )
            input_index = _add_lavfi_input(args, expression, item.timeline_duration_us)
            filters.append(f"[{input_index}:v:0]setpts=PTS-STARTPTS,format=yuv420p[base0]")
            current_video = "base0"
            assert item.title_text is not None
            font = _font_path(request.config, request.cutlist_path, item.font_path)
            raster = _text_raster(
                config=request.config,
                cutlist_path=request.cutlist_path,
                text=item.title_text,
                font_path=font,
                profile=profile,
                placement="center",
                safe_area_percent=request.cutlist.subtitle_policy.safe_area_percent,
            )
            title_input = _add_image_input(args, raster, item.timeline_duration_us)
            filters.append(f"[{title_input}:v:0]format=rgba,setpts=PTS-STARTPTS[title0]")
            filters.append(
                _overlay_filter(current_video, "title0", "titlebase", 0, item.timeline_duration_us)
            )
            current_video = "titlebase"
        else:
            raise PreflightError(
                "standalone_transition_unsupported",
                "Standalone transition items cannot be rendered in V1.",
            )

        for position, overlay in enumerate(item.overlays):
            overlay_label = f"overlay{position}"
            if overlay.kind is OverlayKind.BROLL:
                assert overlay.source_id is not None
                assert overlay.source_in_us is not None
                asset = assets[overlay.source_id]
                path = _asset_path(request.config, asset, profile_name)
                input_index = _add_media_input(
                    args, path, overlay.source_in_us, overlay.duration_us
                )
                filters.append(
                    f"[{input_index}:v:0]{_normal_video_filter(profile)},"
                    f"trim=duration={seconds(overlay.duration_us)},"
                    f"setpts=PTS-STARTPTS+{seconds(overlay.start_us)}/TB[{overlay_label}]"
                )
            elif overlay.kind is OverlayKind.STILL:
                assert overlay.image_path is not None
                path = _resolved_path(request.cutlist_path, overlay.image_path)
                input_index = _add_image_input(args, path, overlay.duration_us)
                filters.append(
                    f"[{input_index}:v:0]{_normal_video_filter(profile)},"
                    f"setpts=PTS-STARTPTS+{seconds(overlay.start_us)}/TB[{overlay_label}]"
                )
            else:
                assert overlay.text is not None
                font = _font_path(
                    request.config,
                    request.cutlist_path,
                    overlay.font_path,
                    item.font_path,
                )
                raster = _text_raster(
                    config=request.config,
                    cutlist_path=request.cutlist_path,
                    text=overlay.text,
                    font_path=font,
                    profile=profile,
                    placement="center",
                    safe_area_percent=request.cutlist.subtitle_policy.safe_area_percent,
                )
                input_index = _add_image_input(args, raster, overlay.duration_us)
                filters.append(
                    f"[{input_index}:v:0]format=rgba,"
                    f"setpts=PTS-STARTPTS+{seconds(overlay.start_us)}/TB[{overlay_label}]"
                )
            next_video = f"composite{position}"
            filters.append(
                _overlay_filter(
                    current_video,
                    overlay_label,
                    next_video,
                    overlay.start_us,
                    overlay.duration_us,
                )
            )
            current_video = next_video

        if request.cutlist.subtitle_policy.enabled:
            for position, subtitle in enumerate(item.subtitles):
                font = _font_path(
                    request.config,
                    request.cutlist_path,
                    subtitle.font_path,
                    item.font_path,
                )
                raster = _text_raster(
                    config=request.config,
                    cutlist_path=request.cutlist_path,
                    text=subtitle.text,
                    font_path=font,
                    profile=profile,
                    placement="subtitle",
                    safe_area_percent=request.cutlist.subtitle_policy.safe_area_percent,
                    style=request.cutlist.subtitle_policy.style,
                )
                input_index = _add_image_input(args, raster, subtitle.duration_us)
                label = f"subtitle{position}"
                filters.append(
                    f"[{input_index}:v:0]format=rgba,"
                    f"setpts=PTS-STARTPTS+{seconds(subtitle.start_us)}/TB[{label}]"
                )
                next_video = f"subtitled{position}"
                filters.append(
                    _overlay_filter(
                        current_video,
                        label,
                        next_video,
                        subtitle.start_us,
                        subtitle.duration_us,
                    )
                )
                current_video = next_video

        video_filters: list[str] = []
        if item.transition_in is not None:
            video_filters.append(f"fade=t=in:st=0:d={seconds(item.transition_in.duration_us)}")
        if item.transition_out is not None:
            start = item.timeline_duration_us - item.transition_out.duration_us
            video_filters.append(
                f"fade=t=out:st={seconds(start)}:d={seconds(item.transition_out.duration_us)}"
            )
        if video_filters:
            filters.append(f"[{current_video}]{','.join(video_filters)}[vfinal]")
        else:
            filters.append(f"[{current_video}]null[vfinal]")

        audio = _audio_asset(item, source, assets)
        if audio is not None and source is not None and item.source_in_us is not None:
            audio_start, audio_duration = map_source_range(
                config=request.config,
                index=index,
                source=source,
                target=audio,
                start_us=item.source_in_us,
                duration_us=item.timeline_duration_us,
            )
            audio_path = _asset_path(request.config, audio, profile_name)
            audio_input = _add_media_input(args, audio_path, audio_start, audio_duration)
            tempo = audio_duration / item.timeline_duration_us
            chain = [f"atempo={tempo:.12f}"] if abs(tempo - 1.0) > 0.000001 else []
            chain.extend(
                [
                    f"apad=whole_dur={seconds(item.timeline_duration_us)}",
                    f"atrim=duration={seconds(item.timeline_duration_us)}",
                    "asetpts=PTS-STARTPTS",
                    f"aresample={profile.audio_sample_rate}",
                ]
            )
            filters.append(f"[{audio_input}:a:0]{','.join(chain)}[abase]")
        else:
            layout = "mono" if profile.audio_channels == 1 else "stereo"
            audio_input = _add_lavfi_input(
                args,
                f"anullsrc=r={profile.audio_sample_rate}:cl={layout}",
                item.timeline_duration_us,
            )
            filters.append(f"[{audio_input}:a:0]asetpts=PTS-STARTPTS[abase]")

        audio_filters: list[str] = []
        if item.transition_in is not None:
            audio_filters.append(f"afade=t=in:st=0:d={seconds(item.transition_in.duration_us)}")
        if item.transition_out is not None:
            start = item.timeline_duration_us - item.transition_out.duration_us
            audio_filters.append(
                f"afade=t=out:st={seconds(start)}:d={seconds(item.transition_out.duration_us)}"
            )
        if audio_filters:
            filters.append(f"[abase]{','.join(audio_filters)}[afinal]")
        else:
            filters.append("[abase]anull[afinal]")

        args.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[vfinal]",
                "-map",
                "[afinal]",
                "-t",
                seconds(item.timeline_duration_us),
                *video_codec_args(profile, encoder),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                profile.audio_codec,
                "-ar",
                str(profile.audio_sample_rate),
                "-ac",
                str(profile.audio_channels),
                "-movflags",
                "+faststart",
                "-y",
                str(temporary),
            ]
        )
        command_log.run(args, runner, purpose=f"render item {item.item_id}")
        os.replace(temporary, output)
        item_manifest = RenderItemManifest(
            item_id=item.item_id,
            cache_key=cache_key,
            profile=profile_name,
            encoder=encoder,
            output_path=str(output),
            output_size=output.stat().st_size,
            output_sha256=sha256_file(output),
            commands=command_log.commands[local_commands_start:],
            completed_at=_utc_now(),
        )
        atomic_write_text(manifest_path, item_manifest.model_dump_json(indent=2) + "\n")
        return item_manifest
    finally:
        temporary.unlink(missing_ok=True)


def _loudnorm_values(stderr: str) -> dict[str, str]:
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start < 0 or end <= start:
        raise PreflightError(
            "loudness_measurement_missing",
            "FFmpeg did not return measurable loudness values for master output.",
        )
    try:
        payload = json.loads(stderr[start : end + 1])
        required = {
            "input_i": "measured_I",
            "input_tp": "measured_TP",
            "input_lra": "measured_LRA",
            "input_thresh": "measured_thresh",
            "target_offset": "offset",
        }
        return {target: str(payload[source]) for source, target in required.items()}
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PreflightError(
            "loudness_measurement_invalid",
            "FFmpeg returned invalid loudness measurement values.",
        ) from exc


def _write_run(path: Path, manifest: RenderRunManifest) -> None:
    atomic_write_text(path, manifest.model_dump_json(indent=2) + "\n")


def _environment(project_root: Path, runner: ProcessRunner) -> dict[str, str | None]:
    git = runner.run(["git", "rev-parse", "HEAD"], cwd=project_root, timeout_seconds=15)
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "gitCommit": git.stdout.strip() if git.return_code == 0 else None,
    }


def _publish_candidate(candidate: Path, output: Path, *, force: bool) -> RenderOutput:
    candidate_hash = sha256_file(candidate)
    if output.exists() and not force:
        if output.is_file() and sha256_file(output) == candidate_hash:
            candidate.unlink(missing_ok=True)
        else:
            raise PathSafetyError(
                "render_output_exists",
                "Render output already exists with different content; pass --force to replace it.",
                details={"path": str(output)},
            )
    else:
        os.replace(candidate, output)
    return RenderOutput(
        path=str(output),
        size=output.stat().st_size,
        sha256=sha256_file(output),
        duration_us=0,
    )


def render_cutlist(
    request: RenderRequest,
    *,
    runner: ProcessRunner | None = None,
    progress: Callable[[str], None] | None = None,
) -> RenderResult:
    active_runner = runner or SubprocessRunner()
    profile_name = request.profile_name or request.cutlist.render_profile
    report = validate_cutlist(
        request.config,
        request.cutlist,
        cutlist_path=request.cutlist_path,
        profile_name=profile_name,
    )
    if not report.ok:
        raise PreflightError(
            "cutlist_validation_failed",
            "Cut-list failed render preflight validation.",
            details={
                "issues": [
                    issue.model_dump(mode="json")
                    for issue in report.issues
                    if issue.severity == "error"
                ]
            },
        )
    if request.context_items and profile_name != "preview":
        raise UsageError("render_context_preview_only", "Context selection is only for previews.")
    selected = _select_items(
        request.cutlist, request.act_id, request.item_id, request.context_items
    )
    profile = request.config.render_profiles.get(profile_name)
    if profile is None:
        raise PreflightError("render_profile_unknown", f"Unknown render profile: {profile_name}")
    output_path = _output_path(request, profile_name)
    if request.dry_run:
        return RenderResult(
            run_id=None,
            output_path=output_path,
            output=None,
            manifest_path=None,
            cache=[
                RenderCacheEntry(
                    item_id=value.item.item_id,
                    cache_key="0" * 64,
                    state="planned",
                    path="",
                )
                for value in selected
            ],
            dry_run=True,
        )

    index = read_media_index(request.config)
    assert index is not None
    assets = {asset.asset_id: asset for asset in index.assets}
    ffmpeg_version = tool_version("ffmpeg", active_runner)
    encoder, probe_command = select_video_encoder(profile, active_runner)
    command_log = _CommandLog(commands=[])
    if probe_command is not None:
        command_log.commands.append(probe_command)
    run_id = _run_id()
    run_path = artifact_path(request.config.artifact_root, "renders", "runs", f"{run_id}.json")
    cutlist_hash = sha256_file(request.cutlist_path)
    config_hash = _canonical_hash(request.config.model_dump(mode="json"))
    input_fingerprints: dict[str, str] = {}
    for selected_item in selected:
        source = assets.get(selected_item.item.source_id or "")
        input_fingerprints.update(
            _item_input_fingerprints(
                config=request.config,
                cutlist_path=request.cutlist_path,
                item=selected_item.item,
                source=source,
                assets=assets,
                profile_name=profile_name,
            )
        )
    manifest = RenderRunManifest(
        run_id=run_id,
        state="running",
        project_id=request.config.project_id,
        cutlist_path=str(request.cutlist_path),
        cutlist_sha256=cutlist_hash,
        config_sha256=config_hash,
        profile=profile_name,
        selection={
            "actId": request.act_id,
            "itemId": request.item_id,
            "itemIds": [value.item.item_id for value in selected],
            **({"contextItems": request.context_items} if request.context_items else {}),
        },
        invocation={
            "resume": request.resume,
            "force": request.force,
            "output": str(output_path),
        },
        input_fingerprints=input_fingerprints,
        ffmpeg_version=ffmpeg_version,
        encoder=encoder,
        environment=_environment(request.project_root, active_runner),
        commands=list(command_log.commands),
        started_at=_utc_now(),
    )
    _write_run(run_path, manifest)
    cache_entries: list[RenderCacheEntry] = []
    candidate: Path | None = None
    assembled: Path | None = None
    try:
        item_outputs: list[Path] = []
        for selected_item in selected:
            item = selected_item.item
            if progress is not None:
                progress(f"Preparing item {item.item_id}")
            source = assets.get(item.source_id or "")
            item_fingerprints = _item_input_fingerprints(
                config=request.config,
                cutlist_path=request.cutlist_path,
                item=item,
                source=source,
                assets=assets,
                profile_name=profile_name,
            )
            cache_key = _canonical_hash(
                {
                    "schema": "render-item-v2",
                    "item": item.model_dump(mode="json"),
                    "subtitlePolicy": request.cutlist.subtitle_policy.model_dump(mode="json"),
                    "profile": profile.model_dump(mode="json"),
                    "encoder": encoder,
                    "inputs": item_fingerprints,
                }
            )
            cache_root = artifact_path(request.config.artifact_root, "renders", "cache", "items")
            cached = None
            if request.resume and not request.force:
                cached = _cache_manifest(cache_root / f"{cache_key}.json", cache_key)
            if cached is None:
                item_manifest = _build_item(
                    request=request,
                    item=item,
                    index=index,
                    profile_name=profile_name,
                    profile=profile,
                    encoder=encoder,
                    cache_key=cache_key,
                    runner=active_runner,
                    command_log=command_log,
                )
                state: Literal["built", "cached"] = "built"
            else:
                item_manifest = cached
                state = "cached"
            item_output = Path(item_manifest.output_path)
            item_outputs.append(item_output)
            cache_entries.append(
                RenderCacheEntry(
                    item_id=item.item_id,
                    cache_key=cache_key,
                    state=state,
                    path=str(item_output),
                    size=item_manifest.output_size,
                    sha256=item_manifest.output_sha256,
                )
            )
            manifest = manifest.model_copy(
                update={
                    "cache": list(cache_entries),
                    "commands": list(command_log.commands),
                }
            )
            _write_run(run_path, manifest)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=f".{output_path.stem}.",
            suffix=".assembled.mp4",
            dir=output_path.parent,
            delete=False,
        ) as handle:
            assembled = Path(handle.name)
        concat_list = output_path.parent / f".{run_id}.ffconcat"
        atomic_write_text(
            concat_list, "\n".join(concat_entry(path) for path in item_outputs) + "\n"
        )
        try:
            command_log.run(
                [
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_list),
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    "-y",
                    str(assembled),
                ],
                active_runner,
                purpose="assemble selected items",
            )
        finally:
            concat_list.unlink(missing_ok=True)

        with tempfile.NamedTemporaryFile(
            prefix=f".{output_path.stem}.",
            suffix=".candidate.mp4",
            dir=output_path.parent,
            delete=False,
        ) as handle:
            candidate = Path(handle.name)
        if profile_name == "master":
            targets = request.config.audio_targets
            _, analysis_stderr = command_log.run(
                [
                    "-nostdin",
                    "-hide_banner",
                    "-i",
                    str(assembled),
                    "-vn",
                    "-af",
                    (
                        f"loudnorm=I={targets.integrated_lufs}:TP={targets.true_peak_dbtp}:"
                        f"LRA={targets.loudness_range_lu}:print_format=json"
                    ),
                    "-f",
                    "null",
                    "-",
                ],
                active_runner,
                purpose="measure master loudness",
            )
            measured = _loudnorm_values(analysis_stderr)
            measured_options = ":".join(f"{key}={value}" for key, value in measured.items())
            command_log.run(
                [
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(assembled),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0",
                    "-c:v",
                    "copy",
                    "-af",
                    (
                        f"loudnorm=I={targets.integrated_lufs}:TP={targets.true_peak_dbtp}:"
                        f"LRA={targets.loudness_range_lu}:{measured_options}:linear=true"
                    ),
                    "-c:a",
                    profile.audio_codec,
                    "-ar",
                    str(profile.audio_sample_rate),
                    "-ac",
                    str(profile.audio_channels),
                    "-movflags",
                    "+faststart",
                    "-y",
                    str(candidate),
                ],
                active_runner,
                purpose="normalize master loudness",
            )
        else:
            os.replace(assembled, candidate)
            assembled = None

        for key in input_fingerprints:
            if key.startswith("source:"):
                validate_source_revision(assets[key.removeprefix("source:")])
        output = _publish_candidate(candidate, output_path, force=request.force)
        candidate = None
        output = output.model_copy(
            update={"duration_us": sum(value.item.timeline_duration_us for value in selected)}
        )
        manifest = manifest.model_copy(
            update={
                "state": "succeeded",
                "cache": cache_entries,
                "commands": list(command_log.commands),
                "output": output,
                "completed_at": _utc_now(),
            }
        )
        _write_run(run_path, manifest)
        return RenderResult(
            run_id=run_id,
            output_path=output_path,
            output=output,
            manifest_path=run_path,
            cache=cache_entries,
            dry_run=False,
        )
    except KeyboardInterrupt:
        manifest = manifest.model_copy(
            update={
                "state": "interrupted",
                "cache": cache_entries,
                "commands": list(command_log.commands),
                "completed_at": _utc_now(),
                "error": {"code": "interrupted", "message": "Render interrupted by user."},
            }
        )
        _write_run(run_path, manifest)
        raise
    except Exception as exc:
        if isinstance(exc, InterviewEditError):
            error = {"code": exc.code, "message": exc.message, "details": exc.details}
        else:
            error = {"code": "render_failed", "message": str(exc)}
        manifest = manifest.model_copy(
            update={
                "state": "failed",
                "cache": cache_entries,
                "commands": list(command_log.commands),
                "completed_at": _utc_now(),
                "error": error,
            }
        )
        _write_run(run_path, manifest)
        raise
    finally:
        if candidate is not None:
            candidate.unlink(missing_ok=True)
        if assembled is not None:
            assembled.unlink(missing_ok=True)
