"""Native editable draft serialization; no GUI or media processing at import time."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from PIL import Image

from interview_edit.adapters.filesystem import quick_fingerprint
from interview_edit.config.models import ProjectConfig
from interview_edit.cutlist.timing import map_source_range, visual_intervals
from interview_edit.errors import PreflightError
from interview_edit.models.cutlist import CutList, TimelineItem
from interview_edit.models.media import MediaAsset, MediaIndex
from interview_edit.project.layout import canonical

DRAFT_PATH = "##_draftpath_placeholder_0E685133-18CE-45ED-8CB8-2904A212EC80_##"
Target = Literal["macos", "windows", "both"]


@lru_cache(maxsize=8)
def _template(name: str) -> dict[str, Any]:
    path = Path(__file__).with_name("jianying_templates") / f"{name}.json"
    value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return value


def template(name: str) -> dict[str, Any]:
    return deepcopy(_template(name))


def new_id() -> str:
    return str(uuid4()).upper()


def time_range(start: int, duration: int) -> dict[str, int]:
    return {"start": start, "duration": duration}


@dataclass
class DraftBuilder:
    config: ProjectConfig
    document: CutList
    cutlist_path: Path
    index: MediaIndex
    bundle_media: bool
    materials: dict[str, Any] = field(default_factory=lambda: template("project")["materials"])
    tracks: dict[str, dict[str, Any]] = field(default_factory=dict)
    resources: dict[Path, str] = field(default_factory=dict)
    resource_revisions: dict[Path, str] = field(default_factory=dict)
    media_ids: dict[tuple[str, str], str] = field(default_factory=dict)
    source_map: list[dict[str, Any]] = field(default_factory=list)
    active_item: TimelineItem | None = None
    item_start_us: int = 0

    def fade_keyframes(self, start: int, duration: int, *, audio: bool) -> list[dict[str, Any]]:
        item = self.active_item
        if item is None or not (item.transition_in or item.transition_out):
            return []
        local_start = start - self.item_start_us
        fade_in = item.transition_in.duration_us if item.transition_in else 0
        fade_out = item.transition_out.duration_us if item.transition_out else 0
        positions = {0, duration}
        for edge in (fade_in, item.timeline_duration_us - fade_out):
            if local_start < edge < local_start + duration:
                positions.add(edge - local_start)
        points = []
        for position in sorted(positions):
            local_time = local_start + position
            value = 1.0
            if fade_in:
                value = min(value, max(0.0, local_time / fade_in))
            if fade_out:
                value = min(value, max(0.0, (item.timeline_duration_us - local_time) / fade_out))
            points.append(
                {
                    "id": new_id(),
                    "curveType": "Line",
                    "graphID": "",
                    "left_control": {"x": 0.0, "y": 0.0},
                    "right_control": {"x": 0.0, "y": 0.0},
                    "time_offset": position,
                    "values": [value],
                }
            )
        if all(point["values"] == [1.0] for point in points):
            return []
        return [
            {
                "id": new_id(),
                "material_id": "",
                "property_type": "KFTypeVolume" if audio else "KFTypeAlpha",
                "keyframe_list": points,
            }
        ]

    def resource(self, path: Path) -> str:
        path = canonical(path)
        if path not in self.resources:
            self.resource_revisions[path] = quick_fingerprint(path)
            suffix = path.suffix.lower()
            if len(suffix) > 12 or not suffix[1:].isalnum():
                raise PreflightError(
                    "jianying_resource_extension", "Unsupported resource extension."
                )
            self.resources[path] = f"Resources/{new_id()}{suffix}"
        return f"{DRAFT_PATH}/{self.resources[path]}" if self.bundle_media else str(path)

    def asset_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        return canonical(path if path.is_absolute() else self.cutlist_path.parent / path)

    def media(self, asset: MediaAsset, *, audio: bool = False) -> str:
        key = (asset.asset_id, "audio" if audio else "video")
        if key in self.media_ids:
            return self.media_ids[key]
        identifier = new_id()
        data = template("audio" if audio else "video")
        data.update(
            id=identifier,
            local_material_id=identifier,
            duration=asset.duration_us,
            path=self.resource(Path(asset.canonical_path)),
        )
        if audio:
            data.update(music_id=identifier, name=Path(asset.relative_path).name)
        else:
            assert asset.video_stream is not None
            if not asset.video_stream.width or not asset.video_stream.height:
                raise PreflightError("jianying_dimensions_missing", "Video dimensions are unknown.")
            data.update(
                material_id=identifier,
                material_name=Path(asset.relative_path).name,
                width=asset.video_stream.width,
                height=asset.video_stream.height,
                has_audio=bool(asset.audio_streams),
            )
        self.materials["audios" if audio else "videos"].append(data)
        self.media_ids[key] = identifier
        return identifier

    def still(self, value: str, duration: int) -> str:
        path = self.asset_path(value)
        resource = self.resource(path)
        identifier = new_id()
        with Image.open(path) as image:
            width, height = image.size
        data = template("video")
        data.update(
            id=identifier,
            material_id=identifier,
            local_material_id=identifier,
            material_name=path.name,
            type="photo",
            path=resource,
            duration=duration,
            width=width,
            height=height,
            has_audio=False,
        )
        self.materials["videos"].append(data)
        return identifier

    def segment(
        self,
        track_name: str,
        kind: str,
        material_id: str,
        start: int,
        duration: int,
        *,
        source_start: int = 0,
        source_duration: int | None = None,
        layer: int = 0,
        item_id: str,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        track = self.tracks.setdefault(
            track_name,
            {
                "id": new_id(),
                "type": kind,
                "name": track_name,
                "attribute": 0,
                "flag": 0,
                "segments": [],
                "is_default_name": False,
            },
        )
        data = template("segment")
        source_duration = duration if source_duration is None else source_duration
        speed = source_duration / duration
        data.update(
            id=new_id(),
            material_id=material_id,
            target_timerange=time_range(start, duration),
            source_timerange=time_range(source_start, source_duration) if kind != "text" else None,
            volume=1.0 if kind == "audio" else 0.0,
            speed=speed,
            render_index=layer,
            track_render_index=layer,
            common_keyframes=self.fade_keyframes(start, duration, audio=kind == "audio"),
        )
        if kind == "audio":
            data["clip"] = None
        if kind != "text":
            speed_id = new_id()
            self.materials["speeds"].append(
                {"id": speed_id, "type": "speed", "mode": 0, "speed": speed, "curve_speed": None}
            )
            data["extra_material_refs"] = [speed_id]
        track["segments"].append(data)
        self.source_map.append(
            {
                "itemId": item_id,
                "segmentId": data["id"],
                "trackId": track["id"],
                "sourceId": source_id,
                "targetStartUs": start,
                "durationUs": duration,
                "sourceStartUs": source_start,
                "sourceDurationUs": source_duration,
            }
        )
        return data

    def text(
        self,
        value: str,
        start: int,
        duration: int,
        *,
        font_value: str | None,
        subtitle: bool,
        item_id: str,
        overlay: bool = False,
    ) -> None:
        if font_value:
            font = self.asset_path(font_value)
        elif self.config.fonts:
            font = self.config.fonts[0]
        else:
            raise PreflightError("font_required", "Editable text requires a declared local font.")
        font_path = self.resource(font)
        rich = template("text_style")
        rich["text"] = value
        # Native text ranges use UTF-16 units, including surrogate pairs for emoji.
        rich["styles"][0].update(
            range=[0, len(value.encode("utf-16-le")) // 2],
            size=7.0 if subtitle else 12.0,
            font={"id": "", "path": font_path},
        )
        data = template("text")
        identifier = new_id()
        data.update(
            id=identifier,
            content=json.dumps(rich, ensure_ascii=False),
            font_path=font_path,
            font_name=font.stem,
            type="subtitle" if subtitle else "text",
            language=self.document.subtitle_policy.language,
            font_size=rich["styles"][0]["size"],
        )
        if subtitle and self.document.subtitle_policy.style == "standard":
            data.update(background_style=1, background_color="#000000", background_alpha=0.7)
        self.materials["texts"].append(data)
        segment = self.segment(
            "字幕" if subtitle else ("覆盖标题" if overlay else "标题"),
            "text",
            identifier,
            start,
            duration,
            layer=30 if subtitle else (20 if overlay else 0),
            item_id=item_id,
        )
        if subtitle:
            segment["clip"]["transform"]["y"] = (
                -0.8 + self.document.subtitle_policy.safe_area_percent / 100
            )

    def build(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        assets = {a.asset_id: a for a in self.index.assets}
        cursor = 0
        for act in self.document.acts:
            for item in act.items:
                self.active_item = item
                self.item_start_us = cursor
                source = assets.get(item.source_id or "")
                if source is not None:
                    for interval in visual_intervals(self.config, self.index, item, source, assets):
                        self.segment(
                            "主画面",
                            "video",
                            self.media(interval.asset),
                            cursor + interval.local_start_us,
                            interval.duration_us,
                            source_start=interval.source_start_us,
                            source_duration=interval.source_duration_us,
                            item_id=item.item_id,
                            source_id=interval.asset.asset_id,
                        )
                    audio = assets.get(item.audio_source or "") if item.audio_source else source
                    if audio is not None and audio.audio_streams:
                        assert item.source_in_us is not None
                        begin, length = map_source_range(
                            config=self.config,
                            index=self.index,
                            source=source,
                            target=audio,
                            start_us=item.source_in_us,
                            duration_us=item.timeline_duration_us,
                        )
                        self.segment(
                            "主音轨",
                            "audio",
                            self.media(audio, audio=True),
                            cursor,
                            item.timeline_duration_us,
                            source_start=begin,
                            source_duration=length,
                            item_id=item.item_id,
                            source_id=audio.asset_id,
                        )
                elif item.kind == "still" and item.image_path:
                    self.segment(
                        "主画面",
                        "video",
                        self.still(item.image_path, item.timeline_duration_us),
                        cursor,
                        item.timeline_duration_us,
                        item_id=item.item_id,
                    )
                elif item.kind == "title" and item.title_text:
                    self.text(
                        item.title_text,
                        cursor,
                        item.timeline_duration_us,
                        font_value=item.font_path,
                        subtitle=False,
                        item_id=item.item_id,
                    )
                else:
                    raise PreflightError(
                        "jianying_item_unsupported", "Unsupported native item kind."
                    )
                for overlay in item.overlays:
                    if overlay.kind == "title" and overlay.text:
                        self.text(
                            overlay.text,
                            cursor + overlay.start_us,
                            overlay.duration_us,
                            font_value=overlay.font_path or item.font_path,
                            subtitle=False,
                            overlay=True,
                            item_id=item.item_id,
                        )
                    else:
                        if overlay.kind == "broll":
                            asset = assets[overlay.source_id or ""]
                            identifier = self.media(asset)
                        else:
                            identifier = self.still(overlay.image_path or "", overlay.duration_us)
                        self.segment(
                            "B-roll 与图片",
                            "video",
                            identifier,
                            cursor + overlay.start_us,
                            overlay.duration_us,
                            source_start=overlay.source_in_us or 0,
                            layer=10,
                            item_id=item.item_id,
                            source_id=overlay.source_id,
                        )
                if self.document.subtitle_policy.enabled:
                    for cue in item.subtitles:
                        self.text(
                            cue.text,
                            cursor + cue.start_us,
                            cue.duration_us,
                            font_value=cue.font_path or item.font_path,
                            subtitle=True,
                            item_id=item.item_id,
                        )
                cursor += item.timeline_duration_us
        data = template("project")
        data.update(
            id=new_id(),
            duration=cursor,
            fps=float(Fraction(self.document.timeline.frame_rate)),
            canvas_config={
                "width": self.document.timeline.width,
                "height": self.document.timeline.height,
                "ratio": "original",
            },
            materials=self.materials,
            tracks=list(self.tracks.values()),
        )
        records = []
        for category in ("videos", "audios"):
            for material in self.materials[category]:
                record = template("meta_material")
                record.update(
                    id=new_id(),
                    file_Path=material["path"],
                    duration=material["duration"],
                    width=material.get("width", 0),
                    height=material.get("height", 0),
                    metetype="music" if category == "audios" else material["type"],
                    extra_info=material.get("material_name", material.get("name", "")),
                )
                records.append(record)
        return data, records
