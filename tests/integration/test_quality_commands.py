from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from interview_edit.cli.app import app
from interview_edit.config.loader import load_project_config
from interview_edit.cutlist.service import load_cutlist, serialize_cutlist
from interview_edit.models.cutlist import Subtitle
from tests.integration.test_render import _render_project
from tests.unit.test_text_quality import font_path

runner = CliRunner()


@pytest.fixture
def project_cut(tmp_path: Path) -> tuple[Path, Path]:
    project, path = _render_project(tmp_path)
    config_path = project / "interview-edit.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["fonts"] = [str(font_path())]
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True))
    return project, path


def invoke(project: Path, path: Path, *args: str):
    return runner.invoke(app, [*args, "--project", str(project), "--cutlist", str(path), "--json"])


def test_range_revision_dry_run_and_protected_output(project_cut: tuple[Path, Path]) -> None:
    project, path = project_cut
    before = path.read_bytes()
    item = load_cutlist(path).acts[0].items[0]
    args = (
        "cutlist",
        "set-range",
        "--item",
        item.item_id,
        "--in-us",
        "200000",
        "--out-us",
        "800000",
        "--output",
        "changed.yaml",
    )
    dry = invoke(project, path, "--dry-run", *args)
    assert dry.exit_code == 0, dry.output
    data = json.loads(dry.stdout)
    assert data["artifacts"] == []
    output = Path(data["data"]["cutlistPath"])
    assert not output.exists()
    result = invoke(project, path, *args)
    assert result.exit_code == 0, result.output
    assert output.is_file()
    assert path.read_bytes() == before
    assert load_cutlist(output).acts[0].items[0].timeline_duration_us == 600_000
    retry = invoke(project, path, *args)
    assert retry.exit_code == 5
    unsafe = invoke(project, path, *args[:-2], "--output", str(path))
    assert unsafe.exit_code == 5
    assert path.read_bytes() == before


def test_invalid_revision_does_not_write(project_cut: tuple[Path, Path]) -> None:
    project, path = project_cut
    item = load_cutlist(path).acts[0].items[0]
    result = invoke(
        project,
        path,
        "cutlist",
        "set-range",
        "--item",
        item.item_id,
        "--in-us",
        "0",
        "--out-us",
        "999999999",
        "--output",
        "bad.yaml",
    )
    assert result.exit_code == 3, result.output
    assert not (load_project_config(project).artifact_root / "cutlists/revisions/bad.yaml").exists()


def test_caption_revision_and_render_preserve_text(project_cut: tuple[Path, Path]) -> None:
    project, path = project_cut
    document = load_cutlist(path)
    text = "预算1.25万元，不能超支。接下来检查结果。"
    document.acts[0].items[0].subtitles = [
        Subtitle(subtitle_id="caption", start_us=0, duration_us=800_000, text=text)
    ]
    path.write_text(serialize_cutlist(document))
    result = invoke(project, path, "cutlist", "captions", "--max-chars", "10", "--style", "minimal")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert text not in result.stdout
    output = Path(payload["data"]["cutlistPath"])
    revised = load_cutlist(output)
    assert revised.subtitle_policy.style == "minimal"
    assert "".join(s.text for s in revised.acts[0].items[0].subtitles) == text
    assert payload["warnings"][0]["code"] == "subtitle_timing_estimated"
    preview = invoke(project, output, "render", "--profile", "preview")
    assert preview.exit_code == 0, preview.output


def test_speech_check_marks_missing_timing_unverified(project_cut: tuple[Path, Path]) -> None:
    project, path = project_cut
    before = sorted(str(p) for p in project.rglob("*"))
    result = invoke(project, path, "cutlist", "speech-check")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["checkedItemCount"] == 0
    assert data["unverifiedItemIds"]
    assert not data["listeningVerified"]
    assert before == sorted(str(p) for p in project.rglob("*"))


def test_overlong_text_is_blocked_before_render(project_cut: tuple[Path, Path]) -> None:
    project, path = project_cut
    document = load_cutlist(path)
    document.acts[0].items[0].subtitles = [
        Subtitle(subtitle_id="caption", start_us=0, duration_us=800_000, text="不可丢弃。" * 100)
    ]
    path.write_text(serialize_cutlist(document))
    validation = invoke(project, path, "cutlist", "validate")
    assert validation.exit_code == 3, validation.output
    assert "text_layout_overflow" in validation.stdout
    result = invoke(project, path, "render")
    assert result.exit_code == 3, result.output
    assert not list((project / "artifacts/renders/runs").glob("*.json"))


def test_context_preview_manifest_contains_neighbors(project_cut: tuple[Path, Path]) -> None:
    project, path = project_cut
    document = load_cutlist(path)
    original = document.acts[0].items[0]
    document.acts[0].items = [
        original.model_copy(update={"item_id": f"item_{i}"}) for i in range(3)
    ]
    path.write_text(serialize_cutlist(document))
    result = invoke(project, path, "render", "--item", "item_1", "--context-items", "1")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    manifest_path = next(a["path"] for a in payload["artifacts"] if a["kind"] == "render-run")
    manifest = json.loads(Path(manifest_path).read_text())
    assert manifest["selection"]["itemIds"] == ["item_0", "item_1", "item_2"]
    assert manifest["output"]["duration_us"] == 2_400_000
    invalid = invoke(project, path, "render", "--context-items", "1")
    assert invalid.exit_code == 2


def test_revision_preserves_relative_image_reference(project_cut: tuple[Path, Path]) -> None:
    from PIL import Image

    from interview_edit.models.cutlist import Overlay

    project, path = project_cut
    image = path.parent / "image.png"
    Image.new("RGB", (20, 20), "blue").save(image)
    document = load_cutlist(path)
    item = document.acts[0].items[0]
    item.overlays = [
        Overlay(
            overlay_id="still",
            kind="still",
            image_path="image.png",
            start_us=0,
            duration_us=800_000,
        )
    ]
    path.write_text(serialize_cutlist(document))
    result = invoke(
        project,
        path,
        "cutlist",
        "set-range",
        "--item",
        item.item_id,
        "--in-us",
        "200000",
        "--out-us",
        "800000",
    )
    assert result.exit_code == 0, result.output
    output = Path(json.loads(result.stdout)["data"]["cutlistPath"])
    assert load_cutlist(output).acts[0].items[0].overlays[0].image_path == str(image)


def test_revision_rejects_symlink_output_directory(
    project_cut: tuple[Path, Path], tmp_path: Path
) -> None:
    project, path = project_cut
    root = load_project_config(project).artifact_root / "cutlists/revisions"
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    result = invoke(project, path, "cutlist", "captions", "--output", "escape/new.yaml")
    assert result.exit_code == 5, result.output
    assert list(outside.iterdir()) == []


def test_speech_check_and_range_revision_use_current_transcript(
    project_cut: tuple[Path, Path],
) -> None:
    from interview_edit.ingest.service import read_media_index
    from interview_edit.transcribe.service import TranscribeRequest, transcribe_assets
    from tests.fixtures.transcription import MockTranscriber

    project, path = project_cut
    config = load_project_config(project)
    index = read_media_index(config, required=True)
    assert index is not None
    transcribe_assets(
        TranscribeRequest(config=config, project_root=project, index=index),
        transcriber=MockTranscriber(),
    )
    checked = invoke(project, path, "cutlist", "speech-check")
    assert checked.exit_code == 3, checked.output
    assert "[mock transcript]" not in checked.stdout
    data = json.loads(checked.stdout)["data"]
    assert data["findings"][0]["suggestedUs"] == 0
    item = load_cutlist(path).acts[0].items[0]
    blocked = invoke(
        project,
        path,
        "cutlist",
        "set-range",
        "--item",
        item.item_id,
        "--in-us",
        "300000",
        "--out-us",
        "700000",
        "--output",
        "unsafe.yaml",
    )
    assert blocked.exit_code == 3
    assert not (config.artifact_root / "cutlists/revisions/unsafe.yaml").exists()
    corrected = config.artifact_root / "transcripts" / index.assets[0].asset_id / "corrected.jsonl"
    corrected.write_text(corrected.read_text() + "\n")
    stale = invoke(project, path, "cutlist", "speech-check")
    assert stale.exit_code == 3
    assert "corrected_transcript_required" in stale.stdout


def test_caption_generated_ids_do_not_collide(project_cut: tuple[Path, Path]) -> None:
    project, path = project_cut
    document = load_cutlist(path)
    document.acts[0].items[0].subtitles = [
        Subtitle(subtitle_id="s", start_us=0, duration_us=400_000, text="第一句。第二句。"),
        Subtitle(subtitle_id="s.1", start_us=400_000, duration_us=400_000, text="第三句。"),
    ]
    path.write_text(serialize_cutlist(document))
    result = invoke(project, path, "cutlist", "captions", "--max-chars", "4")
    assert result.exit_code == 0, result.output
    output = Path(json.loads(result.stdout)["data"]["cutlistPath"])
    cues = load_cutlist(output).acts[0].items[0].subtitles
    assert len({s.subtitle_id for s in cues}) == len(cues)
    assert "".join(s.text for s in cues) == "第一句。第二句。第三句。"
