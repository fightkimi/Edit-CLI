"""Independent checks for the native timeline we claim to support."""

from __future__ import annotations

import json
import math
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any

from interview_edit.cutlist.color import correction_filter
from interview_edit.errors import PreflightError
from interview_edit.export.native_color import native_color_values
from interview_edit.models.cutlist import ColorCorrection, CutList
from interview_edit.models.jianying import JianyingManifest
from interview_edit.models.motion import MotionManifest, MotionSpec


def require(condition: bool, path: str, message: str) -> None:
    if not condition:
        raise PreflightError("jianying_semantics_invalid", message, details={"path": path})


def integer(value: Any, path: str, minimum: int = 0) -> int:
    require(type(value) is int and value >= minimum, path, "Expected an integer time or dimension.")
    return int(value)


def number(value: Any, path: str, minimum: float = 0) -> float:
    require(
        type(value) in {int, float} and math.isfinite(value) and value >= minimum,
        path,
        "Expected a finite numeric value.",
    )
    return float(value)


def span(value: Any, path: str) -> tuple[int, int]:
    require(isinstance(value, dict), path, "Missing native time range.")
    return integer(value.get("start"), path + ".start"), integer(
        value.get("duration"), path + ".duration", 1
    )


def validate_native(
    content: dict[str, Any],
    meta: dict[str, Any],
    manifest: JianyingManifest,
    snapshot: CutList,
    *,
    package_root: Path | None = None,
) -> None:
    require(
        isinstance(content, dict) and isinstance(meta, dict),
        "root",
        "Native documents must be objects.",
    )
    require(
        not manifest.native_effects
        or all(v.gamma == 1 for v in snapshot.color_policy.by_source.values()),
        "color_policy",
        "Native gamma is unsupported.",
    )
    require(
        manifest.native_effects
        or not any(correction_filter(v) for v in snapshot.color_policy.by_source.values()),
        "color_policy",
        "Unmapped native color policy cannot be accepted.",
    )
    ids: set[str] = set()

    def identifier(value: Any, path: str) -> str:
        require(
            isinstance(value, str) and bool(value) and value not in ids,
            path,
            "Missing or duplicate native ID.",
        )
        ids.add(value)
        return str(value)

    require(
        content.get("id") == manifest.export_id,
        "id",
        "Native project ID differs from the manifest.",
    )
    duration = integer(content.get("duration"), "duration", 1)
    require(
        duration == manifest.duration_us, "duration", "Native duration differs from the manifest."
    )
    canvas = content.get("canvas_config", {})
    integer(canvas.get("width"), "canvas.width", 2)
    integer(canvas.get("height"), "canvas.height", 2)
    require(number(content.get("fps"), "fps") > 0, "fps", "Frame rate must be positive.")
    require(
        canvas["width"] == snapshot.timeline.width
        and canvas["height"] == snapshot.timeline.height
        and math.isclose(content["fps"], float(Fraction(snapshot.timeline.frame_rate))),
        "canvas",
        "Canvas differs from the input snapshot.",
    )
    require(
        meta.get("draft_id") == manifest.export_id,
        "meta.draft_id",
        "Metadata belongs to another draft.",
    )
    require(meta.get("tm_duration") == duration, "meta.tm_duration", "Metadata duration differs.")
    groups = content.get("materials")
    require(isinstance(groups, dict), "materials", "Missing native material groups.")
    assert isinstance(groups, dict)
    materials: dict[str, tuple[str, dict[str, Any]]] = {}
    for category, values in groups.items():
        require(
            isinstance(values, list), "materials." + category, "Material group must be an array."
        )
        require(
            not values or category in {"videos", "audios", "texts", "speeds"},
            "materials." + category,
            "Unsupported material group cannot be silently accepted.",
        )
        for i, material in enumerate(values):
            path = f"materials.{category}[{i}]"
            require(isinstance(material, dict), path, "Material must be an object.")
            mid = identifier(material.get("id"), path + ".id")
            materials[mid] = (category, material)
            if category in {"videos", "audios"}:
                integer(material.get("duration"), path + ".duration", 1)
                require(
                    isinstance(material.get("path"), str) and bool(material["path"]),
                    path + ".path",
                    "Media path is missing.",
                )
                if category == "videos":
                    require(
                        material.get("type") in {"video", "photo"},
                        path + ".type",
                        "Invalid visual material type.",
                    )
                    integer(material.get("width"), path + ".width", 1)
                    integer(material.get("height"), path + ".height", 1)
            elif category == "speeds":
                require(
                    number(material.get("speed"), path + ".speed") > 0,
                    path,
                    "Playback speed must be positive.",
                )
            else:
                rich = json.loads(material["content"])
                text = rich.get("text")
                require(
                    isinstance(text, str) and bool(text), path + ".text", "Text content is missing."
                )
                length = len(text.encode("utf-16-le")) // 2
                styles = rich.get("styles")
                require(
                    isinstance(styles, list) and bool(styles),
                    path + ".styles",
                    "Text style ranges are missing.",
                )
                cursor = 0
                for style in styles:
                    bounds = style.get("range")
                    require(
                        isinstance(bounds, list) and len(bounds) == 2,
                        path + ".range",
                        "Invalid text range.",
                    )
                    start = integer(bounds[0], path + ".range.start")
                    end = integer(bounds[1], path + ".range.end", 1)
                    require(
                        start == cursor and start < end <= length,
                        path + ".range",
                        "Text style coverage is invalid.",
                    )
                    cursor = end
                require(
                    cursor == length,
                    path + ".styles",
                    "Text styles must cover all UTF-16 code units.",
                )

    tracks = content.get("tracks")
    require(
        isinstance(tracks, list) and bool(tracks), "tracks", "A draft must contain nonempty tracks."
    )
    native_segments: dict[str, tuple[str, dict[str, Any]]] = {}
    assert isinstance(tracks, list)
    maximum = 0
    for i, track in enumerate(tracks):
        path = f"tracks[{i}]"
        require(isinstance(track, dict), path, "Track must be an object.")
        tid = identifier(track.get("id"), path + ".id")
        kind = track.get("type")
        require(kind in {"video", "audio", "text"}, path + ".type", "Unsupported track type.")
        segments = track.get("segments")
        require(
            isinstance(segments, list) and bool(segments),
            path + ".segments",
            "Empty track is not supported.",
        )
        last_end = 0
        for j, segment in enumerate(segments):
            here = f"{path}.segments[{j}]"
            require(isinstance(segment, dict), here, "Segment must be an object.")
            sid = identifier(segment.get("id"), here + ".id")
            native_segments[sid] = (tid, segment)
            start, length = span(segment.get("target_timerange"), here + ".target")
            require(
                start >= last_end and start + length <= duration,
                here,
                "Overlapping or out-of-bounds target range.",
            )
            last_end = start + length
            maximum = max(maximum, last_end)
            material_id = segment.get("material_id")
            require(
                material_id in materials,
                here + ".material_id",
                "Segment refers to a missing material.",
            )
            category, material = materials[material_id]
            require(
                category == {"video": "videos", "audio": "audios", "text": "texts"}[kind],
                here,
                "Track/material types do not match.",
            )
            speed = number(segment.get("speed"), here + ".speed")
            require(speed > 0, here, "Playback speed must be positive.")
            if kind == "text":
                require(
                    segment.get("source_timerange") is None,
                    here,
                    "Text must not have a source media range.",
                )
            else:
                begin, source_length = span(segment.get("source_timerange"), here + ".source")
                require(
                    begin + source_length <= material["duration"],
                    here,
                    "Source range exceeds its material.",
                )
                require(
                    math.isclose(speed, source_length / length, rel_tol=1e-9),
                    here,
                    "Speed and time ranges disagree.",
                )
            refs = segment.get("extra_material_refs", [])
            require(
                isinstance(refs, list) and len(refs) == len(set(refs)),
                here,
                "Invalid auxiliary references.",
            )
            for ref in refs:
                require(
                    ref in materials and materials[ref][0] == "speeds",
                    here,
                    "Unresolved auxiliary material.",
                )
                require(
                    math.isclose(materials[ref][1]["speed"], speed, rel_tol=1e-9),
                    here,
                    "Auxiliary speed differs.",
                )
            seen_props: set[str] = set()
            for keyframes in segment.get("common_keyframes", []):
                identifier(keyframes.get("id"), here + ".keyframes.id")
                prop = keyframes.get("property_type")
                color_prop = (
                    manifest.native_effects
                    and kind == "video"
                    and prop in {"KFTypeBrightness", "KFTypeContrast", "KFTypeSaturation"}
                )
                require(
                    (color_prop or prop == ("KFTypeVolume" if kind == "audio" else "KFTypeAlpha"))
                    and prop not in seen_props,
                    here,
                    "Unsupported keyframe property.",
                )
                seen_props.add(prop)
                previous = -1
                for point in keyframes.get("keyframe_list", []):
                    identifier(point.get("id"), here + ".keyframe.id")
                    offset = integer(point.get("time_offset"), here + ".keyframe.time")
                    require(
                        previous < offset <= length,
                        here,
                        "Keyframe time is unordered or outside the segment.",
                    )
                    previous = offset
                    values = point.get("values")
                    require(
                        isinstance(values, list) and len(values) == 1,
                        here,
                        "Invalid keyframe values.",
                    )
                    require(
                        number(values[0], here, -1 if color_prop else 0) <= 1,
                        here,
                        "Fade value must be between zero and one.",
                    )
    require(maximum == duration, "duration", "Timeline end does not match project duration.")

    media_ids = {
        mid
        for mid, (kind, value) in materials.items()
        if kind == "audios" or (kind == "videos" and value["type"] != "photo")
    }
    require(
        set(manifest.material_sources) == media_ids,
        "material_sources",
        "Media provenance is incomplete.",
    )
    for mid, aid in manifest.material_sources.items():
        require(aid in manifest.source_assets, "material_sources", "Media source is missing.")
        source = manifest.source_assets[aid]
        material = materials[mid][1]
        require(
            material["duration"] == source.duration_us,
            "source_assets",
            "Indexed source duration differs.",
        )
        require(
            manifest.source_fingerprints.get(source.source_path) == source.sha256,
            "source_assets",
            "Source digest differs.",
        )
        if manifest.bundled_media:
            record = next(
                (r for r in manifest.files if r.relative_path == source.resource_path), None
            )
            require(
                record is not None and record.sha256 == source.sha256,
                "source_assets",
                "Bundled source does not match its input digest.",
            )
            require(
                material["path"].endswith("/" + source.resource_path),
                "source_assets",
                "Source resource differs.",
            )
        else:
            require(
                material["path"] == source.source_path,
                "source_assets",
                "Referenced source differs.",
            )

    item_ranges = {}
    expected_motion: dict[tuple[str, int, int], str] = {}
    expected_text: Counter[tuple[str, int, int, str]] = Counter()
    cursor = 0
    for act in snapshot.acts:
        for item in act.items:
            item_ranges[item.item_id] = (cursor, cursor + item.timeline_duration_us)
            if item.kind == "title":
                expected_text[
                    (item.item_id, cursor, item.timeline_duration_us, item.title_text or "")
                ] += 1
            for overlay in item.overlays:
                if overlay.kind == "motion":
                    roots = [
                        aid
                        for aid, m in manifest.motion_assets.items()
                        if m.inputs.get(overlay.overlay_id) == overlay.motion_path
                    ]
                    require(len(roots) == 1, "motion_assets", "Motion input provenance is missing.")
                    expected_motion[
                        (item.item_id, cursor + overlay.start_us, overlay.duration_us)
                    ] = roots[0]
                if overlay.kind == "title":
                    expected_text[
                        (
                            item.item_id,
                            cursor + overlay.start_us,
                            overlay.duration_us,
                            overlay.text or "",
                        )
                    ] += 1
            if snapshot.subtitle_policy.enabled:
                for cue in item.subtitles:
                    expected_text[
                        (item.item_id, cursor + cue.start_us, cue.duration_us, cue.text)
                    ] += 1
            cursor += item.timeline_duration_us
    actual_text: Counter[tuple[str, int, int, str]] = Counter()
    actual_motion: dict[tuple[str, int, int], str] = {}
    mapped = set()
    for row in manifest.source_map:
        mapping_id = row.get("segmentId")
        require(
            isinstance(mapping_id, str)
            and mapping_id in native_segments
            and mapping_id not in mapped,
            "source_map",
            "Missing or duplicate segment mapping.",
        )
        assert isinstance(mapping_id, str)
        mapped.add(mapping_id)
        tid, segment = native_segments[mapping_id]
        require(row.get("trackId") == tid, "source_map", "Track mapping differs.")
        start, length = span(segment["target_timerange"], "source_map.target")
        item_id = row.get("itemId")
        require(item_id in item_ranges, "source_map.itemId", "Unknown input item.")
        assert isinstance(item_id, str)
        begin, end = item_ranges[item_id]
        require(
            begin <= start and start + length <= end,
            "source_map",
            "Segment is outside its input item.",
        )
        category, material = materials[segment["material_id"]]
        if category == "texts":
            actual_text[(item_id, start, length, json.loads(material["content"])["text"])] += 1
        row_source = row.get("sourceId")
        if isinstance(row_source, str) and row_source in manifest.motion_assets:
            key = (item_id, start, length)
            require(key not in actual_motion, "motion_assets", "Duplicate motion segment.")
            actual_motion[key] = row_source
            spec = manifest.motion_assets[row_source].spec
            require(
                (material["width"], material["height"]) == (spec.width, spec.height),
                "motion_assets",
                "Motion canvas dimensions differ from source.",
            )
            require(
                segment.get("source_timerange", {}).get("start") == 0,
                "motion_assets",
                "Motion source start changed.",
            )
        expected_color = (
            native_color_values(
                snapshot.color_policy.by_source.get(row_source or "", ColorCorrection())
            )
            if manifest.native_effects and category == "videos"
            else {}
        )
        actual_color = {}
        for group in segment.get("common_keyframes", []):
            prop = group["property_type"]
            if prop in {"KFTypeBrightness", "KFTypeContrast", "KFTypeSaturation"}:
                points = group["keyframe_list"]
                require(
                    [p["time_offset"] for p in points] == [0, length]
                    and len(points) == 2
                    and points[0]["values"] == points[1]["values"],
                    "color_policy",
                    "Native color must retain constant input settings.",
                )
                actual_color[prop] = points[0]["values"][0]
        require(
            actual_color == expected_color,
            "color_policy",
            "Native color differs from input policy.",
        )
        require(
            row.get("sourceId") == manifest.material_sources.get(segment["material_id"]),
            "source_map.sourceId",
            "Segment source identity differs.",
        )
        require(
            row.get("targetStartUs") == start and row.get("durationUs") == length,
            "source_map",
            "Target mapping differs.",
        )
        if segment.get("source_timerange") is not None:
            start, length = span(segment["source_timerange"], "source_map.source")
            require(
                row.get("sourceStartUs") == start and row.get("sourceDurationUs") == length,
                "source_map",
                "Source mapping differs.",
            )
    require(
        mapped == set(native_segments), "source_map", "Some native segments have no input mapping."
    )
    require(
        actual_text == expected_text,
        "texts",
        "Native text or timing differs from the input snapshot.",
    )
    require(
        actual_motion == expected_motion,
        "motion_assets",
        "Motion timing or identity differs from input.",
    )
    for aid, motion in manifest.motion_assets.items():
        spec_file = next((f for f in motion.manifest.files if f.relative_path == "spec.json"), None)
        require(
            spec_file is not None and spec_file.sha256 == motion.manifest.spec_sha256,
            "motion_assets",
            "Motion source digest differs.",
        )
        count = math.ceil(
            Fraction(motion.spec.duration_us) * Fraction(motion.spec.frame_rate) / 1_000_000
        )
        require(
            count == motion.manifest.frame_count
            and abs(
                motion.manifest.duration_us
                - round(Fraction(count * 1_000_000) / Fraction(motion.spec.frame_rate))
            )
            <= 1,
            "motion_assets",
            "Motion frame timing differs.",
        )
        require(
            aid == motion.manifest.asset_id and motion.manifest.project_id == manifest.project_id,
            "motion_assets",
            "Motion identity differs.",
        )
        require(
            set(motion.resources)
            == {"spec.json", "manifest.json", "render.mov", "poster.png", "font"},
            "motion_assets",
            "Motion source inventory differs.",
        )
        for name, relative in motion.resources.items():
            record = next((f for f in manifest.files if f.relative_path == relative), None)
            require(
                record is not None and relative.startswith("Resources/"),
                "motion_assets",
                "Motion resource missing.",
            )
            assert record is not None
            if name == "font":
                require(
                    record.sha256 == motion.manifest.font_sha256,
                    "motion_assets",
                    "Motion font differs.",
                )
            elif name in {"render.mov", "poster.png", "spec.json"}:
                original = next((f for f in motion.manifest.files if f.relative_path == name), None)
                require(
                    original is not None
                    and record.sha256 == original.sha256
                    and record.size == original.size,
                    "motion_assets",
                    "Motion payload differs.",
                )
            if package_root is not None and name == "spec.json":
                require(
                    MotionSpec.model_validate_json(
                        (package_root / relative).read_text(encoding="utf-8")
                    )
                    == motion.spec,
                    "motion_assets",
                    "Retained motion source differs.",
                )
            if package_root is not None and name == "manifest.json":
                require(
                    MotionManifest.model_validate_json(
                        (package_root / relative).read_text(encoding="utf-8")
                    )
                    == motion.manifest,
                    "motion_assets",
                    "Retained motion manifest differs.",
                )
    records = meta.get("draft_materials", [])
    registry: list[dict[str, Any]] = next(
        (r.get("value", []) for r in records if r.get("type") == 0), []
    )
    registered = {(r.get("file_Path"), r.get("metetype"), r.get("duration")) for r in registry}
    expected = {
        (m["path"], "music" if c == "audios" else m["type"], m["duration"])
        for c, m in materials.values()
        if c in {"videos", "audios"}
    }
    require(
        registered == expected,
        "meta.draft_materials",
        "Native media registration is incomplete or inconsistent.",
    )
