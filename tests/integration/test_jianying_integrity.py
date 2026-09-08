from __future__ import annotations

import json
from pathlib import Path

import pytest

from interview_edit.adapters.filesystem import sha256_file
from interview_edit.adapters.jianying import DraftBuilder
from interview_edit.config.loader import load_project_config
from interview_edit.cutlist.service import load_cutlist, serialize_cutlist
from interview_edit.errors import PreflightError
from interview_edit.export.jianying import export_jianying, verify_draft
from interview_edit.export.jianying_install import install_draft
from interview_edit.ingest.service import read_media_index
from tests.fixtures.media_factory import make_video
from tests.integration.test_render import _render_project


def setup(tmp_path):
    project, path = _render_project(tmp_path)
    return load_project_config(project), path, load_cutlist(path)


def test_reject_stale_passed_document_before_export(tmp_path):
    config, path, old = setup(tmp_path)
    changed = old.model_copy(deep=True)
    changed.acts[0].items[0].source_out_us -= 100_000
    changed.acts[0].items[0].timeline_duration_us -= 100_000
    path.write_text(serialize_cutlist(changed))
    with pytest.raises(PreflightError):
        export_jianying(config, old, path, name="stale")
    assert not list((config.artifact_root / "exports").glob("stale-*"))


def test_reject_cutlist_change_after_serialization(tmp_path, monkeypatch):
    config, path, document = setup(tmp_path)
    real = DraftBuilder.build

    def update(builder):
        result = real(builder)
        revised = load_cutlist(path)
        revised.acts[0].items[0].source_out_us -= 100_000
        revised.acts[0].items[0].timeline_duration_us -= 100_000
        path.write_text(serialize_cutlist(revised))
        return result

    monkeypatch.setattr(DraftBuilder, "build", update)
    with pytest.raises(PreflightError):
        export_jianying(config, document, path, name="raced")
    assert not list((config.artifact_root / "exports").glob("raced-*"))


def test_reject_media_replaced_after_initial_preflight(tmp_path, monkeypatch):
    config, path, document = setup(tmp_path)
    source = Path(read_media_index(config, required=True).assets[0].canonical_path)
    real = DraftBuilder.build

    def update(builder):
        result = real(builder)
        make_video(source, duration_seconds=0.4, color="red")
        return result

    monkeypatch.setattr(DraftBuilder, "build", update)
    with pytest.raises(PreflightError):
        export_jianying(config, document, path, name="raced")
    assert not list((config.artifact_root / "exports").glob("raced-*"))


@pytest.mark.parametrize(
    "defect",
    ["orphan", "empty", "negative", "duplicate", "overflow", "wrong_type", "speed", "keyframe"],
)
def test_native_semantics_rejected_even_when_hashes_match(tmp_path, defect):
    config, path, document = setup(tmp_path)
    result = export_jianying(config, document, path, name="test")
    package = result.draft_path
    entry = package / "draft_info.json"
    data = json.loads(entry.read_text())
    segment = data["tracks"][0]["segments"][0]
    if defect == "orphan":
        segment["material_id"] = "NONEXISTENT"
    elif defect == "empty":
        data["tracks"] = []
    elif defect == "negative":
        segment["target_timerange"]["start"] = -1
    elif defect == "duplicate":
        data["tracks"][1]["id"] = data["tracks"][0]["id"]
    elif defect == "overflow":
        segment["source_timerange"]["duration"] = 999999999
    elif defect == "wrong_type":
        data["tracks"][0]["type"] = "text"
    elif defect == "speed":
        segment["speed"] = 5.0
    else:
        segment["common_keyframes"] = [
            {
                "id": "kf",
                "property_type": "KFTypeAlpha",
                "keyframe_list": [{"id": "p", "time_offset": 999999999, "values": [1.0]}],
            }
        ]
    entry.write_text(json.dumps(data))
    manifest = package / "export-manifest.json"
    value = json.loads(manifest.read_text())
    record = next(r for r in value["files"] if r["relative_path"] == entry.name)
    record.update(size=entry.stat().st_size, sha256=sha256_file(entry))
    manifest.write_text(json.dumps(value))
    with pytest.raises(PreflightError):
        verify_draft(package)
    library = (tmp_path / "native").resolve()
    library.mkdir()
    with pytest.raises(PreflightError):
        install_draft(package, library, "macos")
    assert not list(library.iterdir())


def test_resume_reuses_verified_resources_and_repairs_corrupt_cache(tmp_path):
    config, path, document = setup(tmp_path)
    first = export_jianying(config, document, path, name="first", resume=True)
    second = export_jianying(config, document, path, name="second", resume=True)
    assert first.cached_resources == 0
    assert second.cached_resources == 1
    cache = next((config.artifact_root / "exports/.media-cache").iterdir())
    cache.write_bytes(b"broken")
    repaired = export_jianying(config, document, path, name="repaired", resume=True)
    assert repaired.cached_resources == 0
    assert verify_draft(first.draft_path)
    assert verify_draft(second.draft_path)
    assert verify_draft(repaired.draft_path)
    assert cache.name == sha256_file(cache)


def test_source_changes_during_copy_prevent_publication(tmp_path, monkeypatch):
    from interview_edit.export import jianying

    config, path, document = setup(tmp_path)
    real = jianying.copy_verified

    def change_after_copy(source, destination, expected, progress):
        real(source, destination, expected, progress)
        source.write_bytes(b"replaced during export")

    monkeypatch.setattr(jianying, "copy_verified", change_after_copy)
    with pytest.raises(PreflightError):
        export_jianying(config, document, path, name="changed")
    assert not list((config.artifact_root / "exports").iterdir())


@pytest.mark.parametrize(
    "defect", ["text", "utf16", "provenance", "registration", "malformed", "platform"]
)
def test_rehashed_semantic_corruption_is_rejected(tmp_path, defect):
    from interview_edit.models.cutlist import Subtitle
    from tests.unit.test_text_quality import font_path

    config, path, document = setup(tmp_path)
    config.fonts = [font_path()]
    document.acts[0].items[0].subtitles = [
        Subtitle(subtitle_id="caption", start_us=0, duration_us=700_000, text="字幕😀")
    ]
    path.write_text(serialize_cutlist(document))
    package = export_jianying(config, document, path, name="test").draft_path
    entry = package / "draft_info.json"
    content = json.loads(entry.read_text())
    manifest_path = package / "export-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if defect in {"text", "utf16"}:
        rich = json.loads(content["materials"]["texts"][0]["content"])
        if defect == "text":
            rich["text"] = "错误😀"
        else:
            rich["styles"][0]["range"] = [0, 3]
        content["materials"]["texts"][0]["content"] = json.dumps(rich)
    elif defect == "provenance":
        next(iter(manifest["source_assets"].values()))["sha256"] = "0" * 64
    elif defect == "registration":
        entry = package / "draft_meta_info.json"
        content = json.loads(entry.read_text())
        content["draft_materials"][0]["value"] = []
    elif defect == "malformed":
        content["tracks"][0]["segments"][0]["common_keyframes"] = [None]
    else:
        content["materials"]["videos"][0]["width"] += 1
    entry.write_text(json.dumps(content))
    record = next(r for r in manifest["files"] if r["relative_path"] == entry.name)
    record.update(size=entry.stat().st_size, sha256=sha256_file(entry))
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(PreflightError):
        verify_draft(package)


def test_still_changed_after_dimensions_were_read_is_rejected(tmp_path, monkeypatch):
    from PIL import Image

    from interview_edit.models.cutlist import TimelineItem

    config, path, document = setup(tmp_path)
    still = path.parent / "still.png"
    Image.new("RGB", (320, 180), "blue").save(still)
    document.acts[0].items.append(
        TimelineItem(
            item_id="image", kind="still", image_path=str(still), timeline_duration_us=400_000
        )
    )
    path.write_text(serialize_cutlist(document))
    real = DraftBuilder.build

    def replace(builder):
        result = real(builder)
        Image.new("RGB", (180, 320), "red").save(still)
        return result

    monkeypatch.setattr(DraftBuilder, "build", replace)
    with pytest.raises(PreflightError):
        export_jianying(config, document, path, name="stale-image")
    assert not list((config.artifact_root / "exports").glob("stale-image-*"))
