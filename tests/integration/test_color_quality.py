from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from interview_edit.cli.app import app
from interview_edit.cutlist.editing import set_source_color
from interview_edit.cutlist.service import load_cutlist, serialize_cutlist
from interview_edit.errors import PreflightError
from interview_edit.export.jianying import export_jianying
from interview_edit.ingest.service import IngestRequest, ingest_media
from interview_edit.models.color import ColorReview
from interview_edit.models.cutlist import Act, ColorCorrection, CutList, TimelineItem
from interview_edit.project.service import InitRequest, initialize_project
from interview_edit.proxy.service import ProxyRequest, build_proxies
from interview_edit.render.service import RenderRequest, render_cutlist
from interview_edit.review.color import review_color
from tests.fixtures.media_factory import require_media_tools


@pytest.fixture
def project(tmp_path):
    ffmpeg, _ = require_media_tools()
    media = tmp_path / "media"
    media.mkdir()
    source = media / "dark.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "nullsrc=s=320x180:r=25:d=1.2,geq=lum='16+90*X/W':cb=128:cr=128",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    made = initialize_project(
        InitRequest(
            project=tmp_path / "project", name="Color tests", media_roots=[media], privacy="strict"
        )
    )
    index = ingest_media(IngestRequest(config=made.config)).index
    build_proxies(ProxyRequest(config=made.config, index=index))
    asset = index.assets[0]
    doc = CutList(
        project_id=made.config.project_id,
        acts=[
            Act(
                act_id="a",
                items=[
                    TimelineItem(
                        item_id="i",
                        kind="primary",
                        source_id=asset.asset_id,
                        source_in_us=100_000,
                        source_out_us=900_000,
                        timeline_duration_us=800_000,
                    )
                ],
            )
        ],
    )
    path = made.config.artifact_root.parent / "cutlists/revisions/color.yaml"
    path.write_text(serialize_cutlist(doc), encoding="utf-8")
    return made.config, path, doc, asset


def test_color_review_suggestions_are_local_bounded_and_do_not_modify_inputs(project):
    config, path, doc, asset = project
    original = path.read_bytes()
    dry = review_color(config, asset_id=asset.asset_id, dry_run=True)
    assert not dry.path.exists()
    reviewed = review_color(config, asset_id=asset.asset_id, samples=2)
    report = reviewed.report
    assert report.correction_status == "proposed" and not report.quality_verified
    assert 0 < report.correction.brightness <= 0.06
    assert report.after.mean_luma > report.before.mean_luma
    assert Path(report.image_path).is_file() and path.read_bytes() == original
    assert (
        ColorReview.model_validate_json((reviewed.path / "report.json").read_text(encoding="utf-8"))
        == report
    )


def test_color_cli_revision_render_cache_and_explicit_native_limit(project, tmp_path):
    config, path, doc, asset = project
    root = config.artifact_root.parent
    baseline = render_cutlist(
        RenderRequest(
            config=config,
            project_root=root,
            cutlist=doc,
            cutlist_path=path,
            profile_name="preview",
            output=config.artifact_root / "renders/plain.mp4",
        )
    )
    command = CliRunner().invoke(
        app,
        [
            "cutlist",
            "color",
            "--project",
            str(root),
            "--cutlist",
            str(path),
            "--asset",
            asset.asset_id,
            "--brightness",
            ".08",
            "--json",
        ],
    )
    assert command.exit_code == 0, command.output
    revised_path = Path(json.loads(command.stdout)["data"]["cutlistPath"])
    revised = load_cutlist(revised_path)
    corrected = render_cutlist(
        RenderRequest(
            config=config,
            project_root=root,
            cutlist=revised,
            cutlist_path=revised_path,
            profile_name="preview",
            output=config.artifact_root / "renders/graded.mp4",
        )
    )
    assert baseline.cache[0].cache_key != corrected.cache[0].cache_key
    assert baseline.output.duration_us == corrected.output.duration_us
    from interview_edit.adapters.color import color_frame, image_stats
    from interview_edit.adapters.process import SubprocessRunner
    from interview_edit.adapters.timeline import audio_window

    runner = SubprocessRunner()
    before, after = tmp_path / "before.jpg", tmp_path / "after.jpg"
    color_frame(Path(baseline.output.path), 400_000, before, ColorCorrection(), runner)
    color_frame(Path(corrected.output.path), 400_000, after, ColorCorrection(), runner)
    assert image_stats([after]).mean_luma > image_stats([before]).mean_luma + 0.04
    left = audio_window(Path(baseline.output.path), tmp_path / "left.wav", 0, 800_000, runner)
    right = audio_window(Path(corrected.output.path), tmp_path / "right.wav", 0, 800_000, runner)
    assert np.array_equal(left, right)
    with pytest.raises(PreflightError) as error:
        export_jianying(config, revised, revised_path, name="grade")
    assert error.value.code == "jianying_color_unsupported"
    reset = set_source_color(
        config, revised, revised_path, asset_id=asset.asset_id, values={}, reset=True
    )
    assert not load_cutlist(reset.output_path).color_policy.by_source
    assert export_jianying(
        config, load_cutlist(reset.output_path), reset.output_path, name="neutral"
    ).manifest


def test_missing_or_hdr_color_evidence_stops_before_creating_artifacts(project):
    config, path, doc, asset = project
    with pytest.raises(PreflightError):
        from interview_edit.models.media import MediaIndex

        index_path = config.artifact_root / "index/media-index.json"
        index = MediaIndex.model_validate_json(index_path.read_text(encoding="utf-8"))
        index.assets[0].video_stream.color_transfer = "smpte2084"
        index_path.write_text(index.model_dump_json(), encoding="utf-8")
        review_color(config, asset_id=asset.asset_id)
    assert not (config.artifact_root / "review").exists()
    result = CliRunner().invoke(
        app,
        [
            "cutlist",
            "color",
            "--project",
            str(config.artifact_root.parent),
            "--cutlist",
            str(path),
            "--asset",
            asset.asset_id,
            "--brightness",
            ".1",
            "--json",
        ],
    )
    assert result.exit_code == 3 and "color_hdr_unsupported" in result.stdout


def test_color_review_rejects_source_change_and_preserves_existing_evidence(project, monkeypatch):
    from interview_edit.review import color

    config, path, doc, asset = project
    old = review_color(config, asset_id=asset.asset_id, samples=2)
    real = color.color_contact

    def change(*args):
        real(*args)
        Path(asset.canonical_path).write_bytes(b"replaced")

    monkeypatch.setattr(color, "color_contact", change)
    with pytest.raises(PreflightError):
        review_color(config, asset_id=asset.asset_id, samples=2)
    assert list((config.artifact_root / "review").iterdir()) == [old.path]


def test_color_review_cli_reports_configured_parameters_without_media_text(project):
    config, path, doc, asset = project
    revised = set_source_color(config, doc, path, asset_id=asset.asset_id, values={"gamma": 1.1})
    result = CliRunner().invoke(
        app,
        [
            "review",
            "color",
            "--project",
            str(config.artifact_root.parent),
            "--asset",
            asset.asset_id,
            "--cutlist",
            str(revised.output_path),
            "--samples",
            "2",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["correctionStatus"] == "configured" and data["correction"]["gamma"] == 1.1
    assert not data["qualityVerified"]


def test_neutral_correction_keeps_cache_and_partial_edits_keep_prior_values(project):
    config, path, doc, asset = project
    root = config.artifact_root.parent
    baseline = render_cutlist(
        RenderRequest(
            config=config,
            project_root=root,
            cutlist=doc,
            cutlist_path=path,
            profile_name="preview",
            output=config.artifact_root / "renders/base.mp4",
        )
    )
    doc.color_policy.by_source[asset.asset_id] = ColorCorrection()
    path.write_text(serialize_cutlist(doc), encoding="utf-8")
    neutral = render_cutlist(
        RenderRequest(
            config=config,
            project_root=root,
            cutlist=doc,
            cutlist_path=path,
            profile_name="preview",
            resume=True,
            output=config.artifact_root / "renders/neutral.mp4",
        )
    )
    assert (
        neutral.cache[0].state == "cached"
        and neutral.cache[0].cache_key == baseline.cache[0].cache_key
    )
    one = set_source_color(config, doc, path, asset_id=asset.asset_id, values={"brightness": 0.03})
    two = set_source_color(
        config,
        load_cutlist(one.output_path),
        one.output_path,
        asset_id=asset.asset_id,
        values={"gamma": 1.1},
    )
    grade = load_cutlist(two.output_path).color_policy.by_source[asset.asset_id]
    assert grade.brightness == 0.03 and grade.gamma == 1.1


def test_color_applies_to_actual_camera_and_overlay_sources_and_reference_times(project, tmp_path):
    import yaml

    from interview_edit.adapters.color import color_frame, image_stats
    from interview_edit.adapters.process import SubprocessRunner
    from interview_edit.models.cutlist import CameraCut, Overlay
    from interview_edit.sync.service import ManualOffset, SyncRequest, sync_take

    config, path, doc, asset = project
    ffmpeg, _ = require_media_tools()
    second = config.media_roots[0] / "bright.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-i",
            asset.canonical_path,
            "-vf",
            "eq=brightness=0.1",
            "-c:v",
            "libx264",
            "-c:a",
            "copy",
            str(second),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    mapping = tmp_path / "cameras.yaml"
    mapping.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "rules": [
                    {"glob": "dark.mp4", "camera_id": "wide", "take_id": "take"},
                    {"glob": "bright.mp4", "camera_id": "close", "take_id": "take"},
                ],
            }
        ),
        encoding="utf-8",
    )
    index = ingest_media(IngestRequest(config=config, camera_map=mapping)).index
    build_proxies(ProxyRequest(config=config, index=index))
    close = next(a for a in index.assets if a.camera_id == "close")
    sync_take(
        SyncRequest(
            config=config,
            index=index,
            take_id="take",
            reference_camera_id="wide",
            manual_offsets=(ManualOffset(camera_id="close", offset_us=0, original_value="0ms"),),
        )
    )
    review = review_color(
        config,
        asset_id=asset.asset_id,
        reference_id=close.asset_id,
        start_us=100_000,
        end_us=900_000,
        samples=2,
    )
    assert review.report.reference.mean_luma > review.report.before.mean_luma
    assert review.report.correction.brightness > 0
    assert len(review.report.source_fingerprints) == 2
    item = doc.acts[0].items[0]
    item.base_camera = "wide"
    item.camera_cuts = [
        CameraCut(cut_id="close", camera_id="close", start_us=200_000, duration_us=400_000)
    ]
    path.write_text(serialize_cutlist(doc), encoding="utf-8")
    baseline = render_cutlist(
        RenderRequest(
            config=config,
            project_root=config.artifact_root.parent,
            cutlist=doc,
            cutlist_path=path,
            profile_name="preview",
            output=config.artifact_root / "renders/cam.mp4",
        )
    )
    revised = set_source_color(
        config, doc, path, asset_id=close.asset_id, values={"brightness": -0.08}
    )
    graded = load_cutlist(revised.output_path)
    result = render_cutlist(
        RenderRequest(
            config=config,
            project_root=config.artifact_root.parent,
            cutlist=graded,
            cutlist_path=revised.output_path,
            profile_name="preview",
            output=config.artifact_root / "renders/cam-grade.mp4",
        )
    )
    runner = SubprocessRunner()
    before, after = tmp_path / "cam-before.jpg", tmp_path / "cam-after.jpg"
    color_frame(Path(baseline.output.path), 400_000, before, ColorCorrection(), runner)
    color_frame(Path(result.output.path), 400_000, after, ColorCorrection(), runner)
    assert image_stats([before]).mean_luma > image_stats([after]).mean_luma + 0.04
    graded.acts[0].items[0].camera_cuts = []
    graded.acts[0].items[0].overlays = [
        Overlay(
            overlay_id="b",
            kind="broll",
            start_us=200_000,
            duration_us=400_000,
            source_id=close.asset_id,
            source_in_us=0,
            source_out_us=400_000,
        )
    ]
    overlay_path = revised.output_path.parent / "overlay.yaml"
    overlay_path.write_text(serialize_cutlist(graded), encoding="utf-8")
    over = render_cutlist(
        RenderRequest(
            config=config,
            project_root=config.artifact_root.parent,
            cutlist=graded,
            cutlist_path=overlay_path,
            profile_name="preview",
            output=config.artifact_root / "renders/overlay.mp4",
        )
    )
    color_frame(
        Path(over.output.path), 400_000, tmp_path / "overlay.jpg", ColorCorrection(), runner
    )
    assert (
        image_stats([tmp_path / "overlay.jpg"]).mean_luma < image_stats([before]).mean_luma - 0.04
    )


def test_subtitle_pixels_stay_white_when_source_color_changes(project, tmp_path):
    from interview_edit.adapters.color import color_frame
    from interview_edit.adapters.process import SubprocessRunner
    from interview_edit.models.cutlist import Subtitle
    from tests.unit.test_text_quality import font_path

    config, path, doc, asset = project
    config.fonts = [font_path()]
    doc.acts[0].items[0].subtitles = [
        Subtitle(subtitle_id="s", start_us=0, duration_us=800_000, text="Keep white text")
    ]
    path.write_text(serialize_cutlist(doc), encoding="utf-8")
    plain = render_cutlist(
        RenderRequest(
            config=config,
            project_root=config.artifact_root.parent,
            cutlist=doc,
            cutlist_path=path,
            profile_name="preview",
            output=config.artifact_root / "renders/caption.mp4",
        )
    )
    revised = set_source_color(
        config, doc, path, asset_id=asset.asset_id, values={"brightness": 0.08, "saturation": 0.8}
    )
    changed = render_cutlist(
        RenderRequest(
            config=config,
            project_root=config.artifact_root.parent,
            cutlist=load_cutlist(revised.output_path),
            cutlist_path=revised.output_path,
            profile_name="preview",
            output=config.artifact_root / "renders/caption-grade.mp4",
        )
    )
    paths = [tmp_path / "text-before.jpg", tmp_path / "text-after.jpg"]
    for output, dest in zip([plain.output.path, changed.output.path], paths, strict=True):
        color_frame(Path(output), 400_000, dest, ColorCorrection(), SubprocessRunner())
    with Image.open(paths[0]) as p, Image.open(paths[1]) as q:
        left, right = np.asarray(p.convert("RGB")), np.asarray(q.convert("RGB"))
    mask = np.all(left > 240, axis=2)
    assert mask.sum() > 20
    assert np.mean(np.abs(left[mask].astype(float) - right[mask].astype(float))) < 8


def test_original_container_offset_uses_normalized_source_clock(project, tmp_path):
    config, path, doc, asset = project
    ffmpeg, _ = require_media_tools()
    shifted = config.media_roots[0] / "shifted.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-i",
            asset.canonical_path,
            "-c",
            "copy",
            "-output_ts_offset",
            "5",
            str(shifted),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    index = ingest_media(IngestRequest(config=config)).index
    new = next(a for a in index.assets if a.relative_path == "shifted.mp4")
    assert new.video_stream.start_time_us == 5_000_000
    assert new.start_time_us > 4_900_000
    result = review_color(config, asset_id=new.asset_id, samples=2)
    assert result.report.end_us <= 1_300_000
    assert all(0 <= sample.time_us < 1_300_000 for sample in result.report.samples)
    assert all(Path(sample.original_path).is_file() for sample in result.report.samples)
