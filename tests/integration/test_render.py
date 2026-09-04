from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml
from PIL import Image
from typer.testing import CliRunner

from interview_edit.adapters.process import ProcessResult, SubprocessRunner
from interview_edit.cli.app import app
from interview_edit.config.loader import load_project_config
from interview_edit.cutlist.service import load_cutlist, serialize_cutlist
from interview_edit.exit_codes import ExitCode
from interview_edit.ingest.service import IngestRequest, ingest_media
from interview_edit.models.cutlist import (
    Act,
    CameraCut,
    CutList,
    Overlay,
    TimelineItem,
    Transition,
)
from interview_edit.models.sync import SyncCamera, SyncReport
from interview_edit.project.service import InitRequest, initialize_project
from interview_edit.proxy.service import ProxyRequest, build_proxies
from interview_edit.render.service import RenderRequest, render_cutlist
from tests.fixtures.media_factory import make_video, require_media_tools

runner = CliRunner()


class InterruptItemRunner:
    def __init__(self) -> None:
        self.delegate = SubprocessRunner()

    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: float = 30,
    ) -> ProcessResult:
        if args and args[0] == "ffmpeg" and "-filter_complex" in args:
            raise KeyboardInterrupt
        return self.delegate.run(args, cwd=cwd, timeout_seconds=timeout_seconds)


def _rgb_average(path: Path, timestamp: str) -> tuple[float, float, float]:
    ffmpeg, _ = require_media_tools()
    completed = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            timestamp,
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    pixels = completed.stdout
    count = len(pixels) // 3
    return tuple(sum(pixels[channel::3]) / count for channel in range(3))


def _duration_seconds(path: Path) -> float:
    _, ffprobe = require_media_tools()
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return float(completed.stdout.strip())


def _render_project(tmp_path: Path) -> tuple[Path, Path]:
    require_media_tools()
    media = tmp_path / "media"
    make_video(media / "source.mp4", duration_seconds=1.2)
    initialized = initialize_project(
        InitRequest(
            project=tmp_path / "project",
            name="M4 render",
            media_roots=[media],
            privacy="strict",
        )
    )
    indexed = ingest_media(
        IngestRequest(config=initialized.config),
        runner=SubprocessRunner(),
    )
    build_proxies(
        ProxyRequest(config=initialized.config, index=indexed.index),
        runner=SubprocessRunner(),
    )
    asset = indexed.index.assets[0]
    document = CutList(
        project_id=initialized.config.project_id,
        timeline=initialized.config.timeline,
        acts=[
            Act(
                act_id="act_001",
                items=[
                    TimelineItem(
                        item_id="item_001",
                        kind="primary",
                        content_role="tutorial",
                        source_id=asset.asset_id,
                        source_in_us=100_000,
                        source_out_us=900_000,
                        timeline_duration_us=800_000,
                        audio_source=asset.asset_id,
                    )
                ],
            )
        ],
    )
    cutlist_path = initialized.config.artifact_root.parent / "cutlists" / "revisions" / "m4.yaml"
    cutlist_path.write_text(serialize_cutlist(document), encoding="utf-8")
    return initialized.config.artifact_root.parent, cutlist_path


def test_preview_render_is_atomic_recorded_and_resumable(tmp_path: Path) -> None:
    project, cutlist_path = _render_project(tmp_path)
    validation = runner.invoke(
        app,
        [
            "cutlist",
            "validate",
            "--project",
            str(project),
            "--cutlist",
            str(cutlist_path),
            "--json",
        ],
    )
    assert validation.exit_code == ExitCode.SUCCESS, validation.output
    dry_run = runner.invoke(
        app,
        [
            "--dry-run",
            "render",
            "--project",
            str(project),
            "--cutlist",
            str(cutlist_path),
            "--json",
        ],
    )
    assert dry_run.exit_code == ExitCode.SUCCESS, dry_run.output
    assert json.loads(dry_run.stdout)["data"]["dryRun"] is True
    assert not list((project / "artifacts" / "renders" / "runs").glob("*.json"))
    args = [
        "render",
        "--project",
        str(project),
        "--cutlist",
        str(cutlist_path),
        "--resume",
        "--json",
    ]

    first = runner.invoke(app, args)

    assert first.exit_code == ExitCode.SUCCESS, first.output
    first_payload = json.loads(first.stdout)
    output = Path(first_payload["data"]["outputPath"])
    manifest_path = Path(first_payload["data"]["manifestPath"])
    assert output.read_bytes()[4:8] == b"ftyp"
    assert _duration_seconds(output) == pytest.approx(0.8, abs=0.08)
    assert first_payload["data"]["cache"][0]["state"] == "built"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["state"] == "succeeded"
    assert manifest["output"]["sha256"] == first_payload["data"]["output"]["sha256"]
    assert any(command["purpose"] == "render item item_001" for command in manifest["commands"])

    second = runner.invoke(app, args)

    assert second.exit_code == ExitCode.SUCCESS, second.output
    second_payload = json.loads(second.stdout)
    assert second_payload["data"]["cache"][0]["state"] == "cached"
    assert second_payload["data"]["output"]["sha256"] == first_payload["data"]["output"]["sha256"]


def test_editing_one_item_rebuilds_only_that_item_cache(tmp_path: Path) -> None:
    project, cutlist_path = _render_project(tmp_path)
    document = yaml.safe_load(cutlist_path.read_text(encoding="utf-8"))
    source_id = document["acts"][0]["items"][0]["source_id"]
    document["acts"][0]["items"] = [
        {
            "item_id": "item_001",
            "kind": "primary",
            "source_id": source_id,
            "source_in_us": 0,
            "source_out_us": 400_000,
            "timeline_duration_us": 400_000,
            "audio_source": source_id,
        },
        {
            "item_id": "item_002",
            "kind": "primary",
            "source_id": source_id,
            "source_in_us": 400_000,
            "source_out_us": 800_000,
            "timeline_duration_us": 400_000,
            "audio_source": source_id,
        },
    ]
    cutlist_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    common = [
        "render",
        "--project",
        str(project),
        "--cutlist",
        str(cutlist_path),
        "--resume",
        "--json",
    ]

    first = runner.invoke(
        app,
        [*common, "--output", str(project / "artifacts" / "renders" / "before.mp4")],
    )
    assert first.exit_code == ExitCode.SUCCESS, first.output
    assert [entry["state"] for entry in json.loads(first.stdout)["data"]["cache"]] == [
        "built",
        "built",
    ]

    document["acts"][0]["items"][1].update({"source_in_us": 500_000, "source_out_us": 900_000})
    cutlist_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    second = runner.invoke(
        app,
        [*common, "--output", str(project / "artifacts" / "renders" / "after.mp4")],
    )

    assert second.exit_code == ExitCode.SUCCESS, second.output
    assert [entry["state"] for entry in json.loads(second.stdout)["data"]["cache"]] == [
        "cached",
        "built",
    ]


def test_master_render_records_measured_two_pass_loudness(tmp_path: Path) -> None:
    project, cutlist_path = _render_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "render",
            "--project",
            str(project),
            "--cutlist",
            str(cutlist_path),
            "--profile",
            "master",
            "--json",
        ],
    )

    assert result.exit_code == ExitCode.SUCCESS, result.output
    payload = json.loads(result.stdout)
    manifest = json.loads(Path(payload["data"]["manifestPath"]).read_text(encoding="utf-8"))
    purposes = [command["purpose"] for command in manifest["commands"]]
    assert "measure master loudness" in purposes
    assert "normalize master loudness" in purposes
    assert Path(payload["data"]["outputPath"]).read_bytes()[4:8] == b"ftyp"


def test_interrupted_render_records_terminal_state_without_output(tmp_path: Path) -> None:
    project, cutlist_path = _render_project(tmp_path)
    config = load_project_config(project)

    with pytest.raises(KeyboardInterrupt):
        render_cutlist(
            RenderRequest(
                config=config,
                project_root=project,
                cutlist=load_cutlist(cutlist_path),
                cutlist_path=cutlist_path,
            ),
            runner=InterruptItemRunner(),
        )

    manifests = sorted((config.artifact_root / "renders" / "runs").glob("*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["state"] == "interrupted"
    assert manifest["output"] is None
    interrupted = next(command for command in manifest["commands"] if command["return_code"] == 130)
    assert interrupted["purpose"] == "render item item_001"
    assert not list((config.artifact_root / "renders").glob("*.mp4"))


def test_interrupted_forced_replacement_preserves_previous_successful_output(
    tmp_path: Path,
) -> None:
    project, cutlist_path = _render_project(tmp_path)
    config = load_project_config(project)
    original = render_cutlist(
        RenderRequest(
            config=config,
            project_root=project,
            cutlist=load_cutlist(cutlist_path),
            cutlist_path=cutlist_path,
        ),
        runner=SubprocessRunner(),
    )
    before = original.output_path.read_bytes()
    document = yaml.safe_load(cutlist_path.read_text(encoding="utf-8"))
    document["acts"][0]["items"][0].update({"source_in_us": 200_000, "source_out_us": 1_000_000})
    cutlist_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    with pytest.raises(KeyboardInterrupt):
        render_cutlist(
            RenderRequest(
                config=config,
                project_root=project,
                cutlist=load_cutlist(cutlist_path),
                cutlist_path=cutlist_path,
                force=True,
            ),
            runner=InterruptItemRunner(),
        )

    assert original.output_path.read_bytes() == before
    manifests = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (config.artifact_root / "renders" / "runs").glob("*.json")
    ]
    assert {manifest["state"] for manifest in manifests} == {"succeeded", "interrupted"}


def test_domain_invalid_cutlist_starts_no_ffmpeg_run_or_output(tmp_path: Path) -> None:
    project, cutlist_path = _render_project(tmp_path)
    document = yaml.safe_load(cutlist_path.read_text(encoding="utf-8"))
    item = document["acts"][0]["items"][0]
    item["overlays"] = [
        {
            "overlay_id": "overlay_001",
            "kind": "broll",
            "start_us": 700_000,
            "duration_us": 200_000,
            "source_id": item["source_id"],
            "source_in_us": 0,
            "source_out_us": 200_000,
        }
    ]
    cutlist_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "render",
            "--project",
            str(project),
            "--cutlist",
            str(cutlist_path),
            "--json",
        ],
    )

    assert result.exit_code == ExitCode.PREFLIGHT_FAILED, result.output
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "cutlist_validation_failed"
    renders = project / "artifacts" / "renders"
    assert not list(renders.glob("*.mp4"))
    assert not list((renders / "runs").glob("*.json"))


def test_chinese_subtitle_and_title_render_through_local_png_rasters(tmp_path: Path) -> None:
    project, cutlist_path = _render_project(tmp_path)
    config_path = project / "interview-edit.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["fonts"] = [
        os.environ.get(
            "INTERVIEW_EDIT_TEST_FONT",
            "/System/Library/Fonts/STHeiti Medium.ttc",
        )
    ]
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    still_path = project / "graphic.png"
    Image.new("RGB", (640, 360), "yellow").save(still_path, format="PNG")
    document = yaml.safe_load(cutlist_path.read_text(encoding="utf-8"))
    primary = document["acts"][0]["items"][0]
    primary["subtitles"] = [
        {
            "subtitle_id": "subtitle_001",
            "start_us": 100_000,
            "duration_us": 500_000,
            "text": "中文字幕本地渲染",
        }
    ]
    document["acts"][0]["items"].append(
        {
            "item_id": "item_002",
            "kind": "title",
            "timeline_duration_us": 500_000,
            "title_text": "章节标题",
        }
    )
    document["acts"][0]["items"].append(
        {
            "item_id": "item_003",
            "kind": "still",
            "timeline_duration_us": 300_000,
            "image_path": str(still_path),
        }
    )
    cutlist_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "render",
            "--project",
            str(project),
            "--cutlist",
            str(cutlist_path),
            "--resume",
            "--json",
        ],
    )

    assert result.exit_code == ExitCode.SUCCESS, result.output
    payload = json.loads(result.stdout)
    output = Path(payload["data"]["outputPath"])
    assert _duration_seconds(output) == pytest.approx(1.6, abs=0.1)
    assert [entry["state"] for entry in payload["data"]["cache"]] == [
        "built",
        "built",
        "built",
    ]
    text_cache = project / "artifacts" / "renders" / "cache" / "text"
    rasters = sorted(text_cache.glob("*.png"))
    assert len(rasters) == 2
    for raster in rasters:
        with Image.open(raster) as image:
            assert image.size == (1280, 720)
            assert image.mode == "RGBA"
            bounds = image.getchannel("A").getbbox()
            assert bounds is not None
            assert bounds[0] >= 64
            assert bounds[1] >= 36
            assert bounds[2] <= 1216
            assert bounds[3] <= 684

    resumed = runner.invoke(
        app,
        [
            "render",
            "--project",
            str(project),
            "--cutlist",
            str(cutlist_path),
            "--resume",
            "--json",
        ],
    )
    assert resumed.exit_code == ExitCode.SUCCESS, resumed.output
    assert [entry["state"] for entry in json.loads(resumed.stdout)["data"]["cache"]] == [
        "cached",
        "cached",
        "cached",
    ]


def test_failed_replacement_preserves_previous_successful_output(tmp_path: Path) -> None:
    project, cutlist_path = _render_project(tmp_path)
    args = [
        "render",
        "--project",
        str(project),
        "--cutlist",
        str(cutlist_path),
        "--json",
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == ExitCode.SUCCESS, first.output
    first_payload = json.loads(first.stdout)
    output = Path(first_payload["data"]["outputPath"])
    previous = output.read_bytes()

    document = yaml.safe_load(cutlist_path.read_text(encoding="utf-8"))
    item = document["acts"][0]["items"][0]
    item["source_in_us"] = 200_000
    item["source_out_us"] = 1_000_000
    cutlist_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    replacement = runner.invoke(app, args)

    assert replacement.exit_code == ExitCode.PATH_ERROR, replacement.output
    assert json.loads(replacement.stdout)["error"]["code"] == "render_output_exists"
    assert output.read_bytes() == previous
    run_manifests = sorted((project / "artifacts" / "renders" / "runs").glob("*.json"))
    failed = next(
        payload
        for path in run_manifests
        if (payload := json.loads(path.read_text(encoding="utf-8")))["state"] == "failed"
    )
    assert failed["state"] == "failed"
    assert failed["output"] is None


def test_camera_broll_and_paired_fade_are_rendered_with_primary_audio(tmp_path: Path) -> None:
    require_media_tools()
    media = tmp_path / "media"
    make_video(media / "wide.mp4", color="blue", frequency=440, duration_seconds=1.4)
    make_video(media / "close.mp4", color="red", frequency=660, duration_seconds=1.4)
    make_video(media / "broll.mp4", color="green", frequency=880, duration_seconds=1.4)
    initialized = initialize_project(
        InitRequest(
            project=tmp_path / "project",
            name="M4 composition",
            media_roots=[media],
            privacy="strict",
        )
    )
    camera_map = tmp_path / "camera-map.yaml"
    camera_map.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "rules": [
                    {"glob": "wide.mp4", "camera_id": "wide", "take_id": "take-01"},
                    {"glob": "close.mp4", "camera_id": "close", "take_id": "take-01"},
                ],
            }
        ),
        encoding="utf-8",
    )
    indexed = ingest_media(
        IngestRequest(config=initialized.config, camera_map=camera_map),
        runner=SubprocessRunner(),
    )
    build_proxies(
        ProxyRequest(config=initialized.config, index=indexed.index),
        runner=SubprocessRunner(),
    )
    assets = {Path(asset.canonical_path).name: asset for asset in indexed.index.assets}
    sync = SyncReport(
        take_id="take-01",
        reference_camera_id="wide",
        cache_key="0" * 64,
        analysis={"fixture": True},
        cameras=[
            SyncCamera(
                camera_id="wide",
                asset_id=assets["wide.mp4"].asset_id,
                status="reference",
                offset_us=0,
                drift_us_per_hour=0,
                drift_ppm=0,
                confidence=1,
                provenance="reference",
            ),
            SyncCamera(
                camera_id="close",
                asset_id=assets["close.mp4"].asset_id,
                status="manual",
                offset_us=0,
                drift_us_per_hour=0,
                drift_ppm=0,
                confidence=1,
                provenance="manual_override",
                manual_value="0us",
            ),
        ],
        completed_at="2026-09-03T00:00:00Z",
    )
    sync_path = initialized.config.artifact_root / "sync" / "take-01" / "sync.json"
    sync_path.parent.mkdir(parents=True)
    sync_path.write_text(sync.model_dump_json(indent=2) + "\n", encoding="utf-8")
    transition = Transition(duration_us=100_000)
    wide = assets["wide.mp4"]
    document = CutList(
        project_id=initialized.config.project_id,
        acts=[
            Act(
                act_id="act_001",
                items=[
                    TimelineItem(
                        item_id="item_001",
                        kind="primary",
                        source_id=wide.asset_id,
                        source_in_us=0,
                        source_out_us=1_000_000,
                        timeline_duration_us=1_000_000,
                        audio_source=wide.asset_id,
                        base_camera="wide",
                        camera_cuts=[
                            CameraCut(
                                cut_id="cut_001",
                                camera_id="close",
                                start_us=200_000,
                                duration_us=300_000,
                            )
                        ],
                        overlays=[
                            Overlay(
                                overlay_id="overlay_001",
                                kind="broll",
                                start_us=600_000,
                                duration_us=200_000,
                                source_id=assets["broll.mp4"].asset_id,
                                source_in_us=100_000,
                                source_out_us=300_000,
                            )
                        ],
                        transition_out=transition,
                    ),
                    TimelineItem(
                        item_id="item_002",
                        kind="primary",
                        source_id=wide.asset_id,
                        source_in_us=200_000,
                        source_out_us=1_000_000,
                        timeline_duration_us=800_000,
                        audio_source=wide.asset_id,
                        transition_in=transition,
                    ),
                ],
            )
        ],
    )
    project = initialized.config.artifact_root.parent
    cutlist_path = project / "cutlists" / "revisions" / "composition.yaml"
    cutlist_path.write_text(serialize_cutlist(document), encoding="utf-8")
    source_hashes = {
        path.name: path.read_bytes()
        for path in (media / "wide.mp4", media / "close.mp4", media / "broll.mp4")
    }

    result = runner.invoke(
        app,
        [
            "render",
            "--project",
            str(project),
            "--cutlist",
            str(cutlist_path),
            "--json",
        ],
    )

    assert result.exit_code == ExitCode.SUCCESS, result.output
    payload = json.loads(result.stdout)
    output = Path(payload["data"]["outputPath"])
    base_rgb = _rgb_average(output, "0.10")
    close_rgb = _rgb_average(output, "0.35")
    broll_rgb = _rgb_average(output, "0.70")
    assert base_rgb[2] > base_rgb[0] + 40
    assert close_rgb[0] > close_rgb[2] + 40
    assert broll_rgb[1] > broll_rgb[0] + 20
    manifest = json.loads(Path(payload["data"]["manifestPath"]).read_text(encoding="utf-8"))
    item_commands = [
        command for command in manifest["commands"] if command["purpose"].startswith("render item")
    ]
    filters = " ".join(" ".join(command["args"]) for command in item_commands)
    assert "fade=t=out" in filters
    assert "fade=t=in" in filters
    assert "overlay=" in filters
    assert all(path.read_bytes() == source_hashes[path.name] for path in media.glob("*.mp4"))

    selected_result = runner.invoke(
        app,
        [
            "render",
            "--project",
            str(project),
            "--cutlist",
            str(cutlist_path),
            "--act",
            "act_001",
            "--item",
            "item_002",
            "--json",
        ],
    )

    assert selected_result.exit_code == ExitCode.SUCCESS, selected_result.output
    selected_payload = json.loads(selected_result.stdout)
    selected_output = Path(selected_payload["data"]["outputPath"])
    assert selected_output.name == "composition-act_001-item_002-preview.mp4"
    assert _duration_seconds(selected_output) == pytest.approx(0.8, abs=0.08)
    selected_manifest = json.loads(
        Path(selected_payload["data"]["manifestPath"]).read_text(encoding="utf-8")
    )
    assert selected_manifest["selection"] == {
        "actId": "act_001",
        "itemId": "item_002",
        "itemIds": ["item_002"],
    }
