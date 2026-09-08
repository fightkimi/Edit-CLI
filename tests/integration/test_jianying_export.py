from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from interview_edit.cli.app import app
from interview_edit.cutlist.service import load_cutlist, serialize_cutlist
from interview_edit.errors import PathSafetyError, PreflightError
from interview_edit.export.jianying import verify_draft
from interview_edit.export.jianying_install import install_draft
from interview_edit.models.cutlist import Overlay, Subtitle, Transition
from tests.integration.test_render import _render_project
from tests.unit.test_text_quality import font_path


@pytest.fixture
def project_cut(tmp_path):
    project, path = _render_project(tmp_path)
    config_path = project / "interview-edit.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["fonts"] = [str(font_path())]
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True))
    return project, path


runner = CliRunner()


def export(project: Path, cutlist: Path, *extra: str):
    return runner.invoke(
        app,
        [
            "export",
            "jianying",
            "--project",
            str(project),
            "--cutlist",
            str(cutlist),
            "--name",
            "可编辑样片",
            "--json",
            *extra,
        ],
    )


def test_native_export_keeps_editable_tracks_and_portable_media(project_cut):
    project, path = project_cut
    document = load_cutlist(path)
    item = document.acts[0].items[0]
    item.subtitles = [
        Subtitle(subtitle_id="s1", start_us=0, duration_us=700_000, text="可修改😀字幕")
    ]
    item.overlays = [
        Overlay(
            overlay_id="b1",
            kind="broll",
            start_us=200_000,
            duration_us=300_000,
            source_id=item.source_id,
            source_in_us=300_000,
            source_out_us=600_000,
        )
    ]
    path.write_text(serialize_cutlist(document))
    before = path.read_bytes()
    result = export(project, path, "--platform", "both", "--bundle-media")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    bundle = Path(payload["data"]["draftPath"])
    mac = json.loads((bundle / "draft_info.json").read_text())
    windows = json.loads((bundle / "draft_content.json").read_text())
    assert mac["platform"]["os"] == "mac"
    assert windows["platform"]["os"] == "windows"
    assert mac["tracks"] == windows["tracks"]
    assert {t["type"] for t in mac["tracks"]} == {"video", "audio", "text"}
    text = json.loads(mac["materials"]["texts"][0]["content"])
    assert text["text"] == "可修改😀字幕"
    assert text["styles"][0]["range"] == [0, 7]
    video_tracks = [t for t in mac["tracks"] if t["type"] == "video"]
    assert len(video_tracks) == 2
    assert all(s["volume"] == 0 for t in video_tracks for s in t["segments"])
    audio = next(t for t in mac["tracks"] if t["type"] == "audio")["segments"]
    assert audio[0]["target_timerange"] == {"start": 0, "duration": 800_000}
    assert audio[0]["source_timerange"]["start"] == 100_000
    assert payload["data"]["nativeValidation"] == "not_run"
    assert all(not mac["platform"][k] for k in ["device_id", "hard_disk_id", "mac_address"])
    assert path.read_bytes() == before
    assert (bundle / "export-manifest.json").is_file()
    assert len(list((bundle / "Resources").rglob("*.mp4"))) == 1
    meta = json.loads((bundle / "draft_meta_info.json").read_text())
    assert meta["draft_materials"][0]["value"]
    assert "可修改" not in result.stdout


def test_export_dry_run_and_native_fades(project_cut):
    project, path = project_cut
    dry = runner.invoke(
        app,
        [
            "--dry-run",
            "export",
            "jianying",
            "--project",
            str(project),
            "--cutlist",
            str(path),
            "--name",
            "dry",
            "--json",
        ],
    )
    assert dry.exit_code == 0, dry.output
    assert json.loads(dry.stdout)["artifacts"] == []
    assert not (project / "artifacts/exports").exists()

    doc = load_cutlist(path)
    first = doc.acts[0].items[0]
    first.transition_out = Transition(duration_us=50_000)
    second = first.model_copy(
        deep=True,
        update={"item_id": "second", "transition_out": None, "transition_in": first.transition_out},
    )
    doc.acts[0].items.append(second)
    path.write_text(serialize_cutlist(doc))
    result = export(project, path)
    assert result.exit_code == 0, result.output
    package = Path(json.loads(result.stdout)["data"]["draftPath"])
    content = json.loads((package / "draft_info.json").read_text())
    properties = {
        k["property_type"]
        for t in content["tracks"]
        for s in t["segments"]
        for k in s["common_keyframes"]
    }
    assert properties == {"KFTypeAlpha", "KFTypeVolume"}
    audio = next(t for t in content["tracks"] if t["type"] == "audio")["segments"]
    assert audio[0]["common_keyframes"][0]["keyframe_list"][-1]["values"] == [0.0]
    assert audio[1]["common_keyframes"][0]["keyframe_list"][0]["values"] == [0.0]


@pytest.mark.parametrize("target", ["macos", "windows"])
def test_install_rebases_paths_and_preserves_existing_library(project_cut, tmp_path, target):
    project, path = project_cut
    result = export(project, path)
    assert result.exit_code == 0, result.output
    package = Path(json.loads(result.stdout)["data"]["draftPath"])
    library = tmp_path / "native-library"
    library.mkdir()
    registry = library / "root_meta_info.json"
    registry.write_text('{"existing":"do not touch"}')
    planned = install_draft(package, library, target, dry_run=True)
    assert not planned.exists()
    installed = install_draft(package, library, target)
    assert registry.read_text() == '{"existing":"do not touch"}'
    assert verify_draft(installed).platform == target
    assert verify_draft(package).platform == "both"
    filename = "draft_info.json" if target == "macos" else "draft_content.json"
    content = json.loads((installed / filename).read_text())
    for category in ["videos", "audios"]:
        for material in content["materials"][category]:
            assert Path(material["path"]).is_file()
            assert Path(material["path"]).is_relative_to(installed)
    with pytest.raises(PathSafetyError):
        install_draft(package, library, target)


def test_modified_or_symlink_package_cannot_install(project_cut, tmp_path):
    project, path = project_cut
    result = export(project, path)
    package = Path(json.loads(result.stdout)["data"]["draftPath"])
    library = tmp_path / "library"
    library.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(package, target_is_directory=True)
    with pytest.raises(PathSafetyError):
        install_draft(alias, library, "macos")
    (package / "draft_info.json").write_text("{}")
    with pytest.raises(PreflightError):
        install_draft(package, library, "macos")
    assert list(library.iterdir()) == []


@pytest.mark.parametrize("name", ["../escape", "CON", "bad/name", "bad\\name", "trailing."])
def test_export_rejects_nonportable_names(project_cut, name):
    project, path = project_cut
    result = runner.invoke(
        app,
        [
            "export",
            "jianying",
            "--project",
            str(project),
            "--cutlist",
            str(path),
            "--name",
            name,
            "--json",
        ],
    )
    assert result.exit_code == 2, result.output
    assert not (project / "artifacts/exports").exists()


def test_export_native_titles_stills_and_overlay_title_remain_separate(project_cut):
    from PIL import Image

    from interview_edit.models.cutlist import TimelineItem

    project, path = project_cut
    image = path.parent / "card.png"
    Image.new("RGB", (300, 180), "green").save(image)
    doc = load_cutlist(path)
    doc.acts[0].items.append(
        TimelineItem(
            item_id="title",
            kind="title",
            timeline_duration_us=400_000,
            title_text="可修改标题",
            overlays=[
                Overlay(
                    overlay_id="overlay-title",
                    kind="title",
                    start_us=0,
                    duration_us=300_000,
                    text="可修改角标",
                )
            ],
        )
    )
    doc.acts[0].items.append(
        TimelineItem(
            item_id="image", kind="still", timeline_duration_us=400_000, image_path="card.png"
        )
    )
    path.write_text(serialize_cutlist(doc))
    result = export(project, path)
    assert result.exit_code == 0, result.output
    package = Path(json.loads(result.stdout)["data"]["draftPath"])
    draft = json.loads((package / "draft_info.json").read_text())
    assert len([t for t in draft["tracks"] if t["type"] == "text"]) == 2
    assert any(m["type"] == "photo" for m in draft["materials"]["videos"])


def test_missing_jianying_is_explicit_and_read_only(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "interview_edit.cli.app.inspect_jianying",
        lambda: {"installed": False, "draftRoot": str(tmp_path), "nativeValidation": "not_run"},
    )
    result = runner.invoke(app, ["jianying", "doctor", "--json"])
    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "jianying_missing"
    assert not list(tmp_path.iterdir())


def test_multicam_export_reuses_sync_mapping_and_keeps_one_audio_spine(project_cut, tmp_path):
    from interview_edit.config.loader import load_project_config
    from interview_edit.ingest.service import IngestRequest, ingest_media, read_media_index
    from interview_edit.models.cutlist import CameraCut
    from interview_edit.proxy.service import ProxyRequest, build_proxies
    from interview_edit.sync.service import ManualOffset, SyncRequest, sync_take
    from tests.fixtures.media_factory import make_video

    project, path = project_cut
    config = load_project_config(project)
    original = read_media_index(config, required=True).assets[0]
    media = config.media_roots[0]
    make_video(media / "close.mp4", duration_seconds=1.4, frequency=660, color="red")
    camera_map = tmp_path / "cameras.yaml"
    camera_map.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "rules": [
                    {
                        "glob": Path(original.canonical_path).name,
                        "camera_id": "wide",
                        "take_id": "take",
                    },
                    {"glob": "close.mp4", "camera_id": "close", "take_id": "take"},
                ],
            }
        )
    )
    indexed = ingest_media(IngestRequest(config=config, camera_map=camera_map))
    build_proxies(ProxyRequest(config=config, index=indexed.index))
    sync_take(
        SyncRequest(
            config=config,
            index=indexed.index,
            take_id="take",
            reference_camera_id="wide",
            manual_offsets=(
                ManualOffset(camera_id="close", offset_us=100_000, original_value="100ms"),
            ),
        )
    )
    document = load_cutlist(path)
    item = document.acts[0].items[0]
    item.base_camera = "wide"
    item.camera_cuts = [
        CameraCut(cut_id="close-cut", camera_id="close", start_us=200_000, duration_us=300_000)
    ]
    path.write_text(serialize_cutlist(document))
    result = export(project, path)
    assert result.exit_code == 0, result.output
    package = Path(json.loads(result.stdout)["data"]["draftPath"])
    draft = json.loads((package / "draft_info.json").read_text())
    videos = next(t for t in draft["tracks"] if t["type"] == "video")["segments"]
    audio = next(t for t in draft["tracks"] if t["type"] == "audio")["segments"]
    assert len(videos) == 3 and len(audio) == 1
    assert videos[1]["source_timerange"] == {"start": 400_000, "duration": 300_000}
    assert videos[1]["target_timerange"] == {"start": 200_000, "duration": 300_000}
    assert audio[0]["target_timerange"] == {"start": 0, "duration": 800_000}


def test_invalid_cutlist_stops_export_before_writes(project_cut):
    project, path = project_cut
    doc = load_cutlist(path)
    item = doc.acts[0].items[0]
    item.source_out_us = 999_000_000
    item.timeline_duration_us = 998_900_000
    path.write_text(serialize_cutlist(doc))
    result = export(project, path)
    assert result.exit_code == 3, result.output
    assert not (project / "artifacts/exports").exists()
