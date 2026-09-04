from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from interview_edit.adapters.process import SubprocessRunner
from interview_edit.adapters.transcription import MockTranscriber
from interview_edit.cli.app import app
from interview_edit.exit_codes import ExitCode
from interview_edit.ingest.service import IngestRequest, ingest_media
from interview_edit.project.service import InitRequest, initialize_project
from interview_edit.proxy.service import ProxyRequest, build_proxies
from interview_edit.transcribe.service import TranscribeRequest, transcribe_assets
from tests.fixtures.media_factory import make_video, require_media_tools

runner = CliRunner()


def _project(tmp_path: Path) -> Path:
    media = tmp_path / "media"
    media.mkdir()
    result = initialize_project(
        InitRequest(
            project=tmp_path / "project",
            name="M4 test",
            media_roots=[media],
            privacy="strict",
        )
    )
    return result.config.artifact_root.parent


def test_cli_scaffold_and_privacy_safe_inspect(tmp_path: Path) -> None:
    project = _project(tmp_path)

    scaffold = runner.invoke(app, ["cutlist", "scaffold", "--project", str(project), "--json"])

    assert scaffold.exit_code == ExitCode.SUCCESS, scaffold.output
    payload = json.loads(scaffold.stdout)
    cutlist_path = Path(payload["data"]["cutlistPath"])
    assert cutlist_path.is_file()
    assert payload["data"]["itemCount"] == 0

    document = yaml.safe_load(cutlist_path.read_text(encoding="utf-8"))
    document["acts"][0]["title"] = "private act title"
    cutlist_path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    inspect = runner.invoke(
        app,
        ["cutlist", "inspect", "--project", str(project), "--cutlist", str(cutlist_path), "--json"],
    )

    assert inspect.exit_code == ExitCode.SUCCESS, inspect.output
    assert "private act title" not in inspect.stdout
    assert len(inspect.stdout.strip().splitlines()) == 1


def test_cli_validate_schema_error_is_exit_three_and_no_render(tmp_path: Path) -> None:
    project = _project(tmp_path)
    cutlist_path = project / "cutlists" / "revisions" / "bad.yaml"
    cutlist_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "project_id": "prj_example01",
                "timeline": {"frame_rate": "25/1", "width": 1920, "height": 1080},
                "acts": [
                    {
                        "act_id": "act_001",
                        "items": [
                            {
                                "item_id": "item_001",
                                "kind": "primary",
                                "source_id": "asset_0123456789abcdef01234567",
                                "source_in_us": 0,
                                "source_out_us": 1_000_000,
                                "timeline_duration_us": 500_000,
                            }
                        ],
                    }
                ],
                "subtitle_policy": {"enabled": True, "language": "zh"},
                "render_profile": "preview",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
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

    assert result.exit_code == ExitCode.PREFLIGHT_FAILED, result.output
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "cutlist_invalid"
    assert list((project / "artifacts" / "renders").iterdir()) == []


def test_cli_validate_rejects_existing_but_invalid_still_image(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    initialized = initialize_project(
        InitRequest(
            project=tmp_path / "project",
            name="M4 invalid image",
            media_roots=[media],
            privacy="strict",
        )
    )
    project = initialized.config.artifact_root.parent
    image = project / "cutlists" / "revisions" / "not-an-image.png"
    image.write_text("this is not a PNG", encoding="utf-8")
    cutlist_path = project / "cutlists" / "revisions" / "invalid-still.yaml"
    cutlist_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "project_id": initialized.config.project_id,
                "timeline": {"frame_rate": "25/1", "width": 1920, "height": 1080},
                "acts": [
                    {
                        "act_id": "act_001",
                        "items": [
                            {
                                "item_id": "item_001",
                                "kind": "still",
                                "image_path": image.name,
                                "timeline_duration_us": 1_000_000,
                            }
                        ],
                    }
                ],
                "render_profile": "preview",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
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

    assert result.exit_code == ExitCode.PREFLIGHT_FAILED, result.output
    payload = json.loads(result.stdout)
    issue_codes = {issue["code"] for issue in payload["data"]["issues"]}
    assert "image_asset_invalid" in issue_codes


def test_cli_scaffold_uses_only_checksum_valid_corrected_transcript(tmp_path: Path) -> None:
    require_media_tools()
    media = tmp_path / "media"
    make_video(media / "spoken.mp4", duration_seconds=1.2)
    initialized = initialize_project(
        InitRequest(
            project=tmp_path / "project",
            name="M4 transcript scaffold",
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
    transcribe_assets(
        TranscribeRequest(
            config=initialized.config,
            project_root=initialized.config.artifact_root.parent,
            index=indexed.index,
        ),
        transcriber=MockTranscriber(),
        runner=SubprocessRunner(),
    )
    project = initialized.config.artifact_root.parent
    output = project / "cutlists" / "revisions" / "transcript.yaml"

    result = runner.invoke(
        app,
        [
            "cutlist",
            "scaffold",
            "--project",
            str(project),
            "--asset",
            asset.asset_id,
            "--output",
            str(output),
            "--json",
        ],
    )

    assert result.exit_code == ExitCode.SUCCESS, result.output
    payload = json.loads(result.stdout)
    assert payload["data"]["fromTranscript"] is True
    assert payload["data"]["itemCount"] == 1
    cutlist = yaml.safe_load(output.read_text(encoding="utf-8"))
    item = cutlist["acts"][0]["items"][0]
    assert isinstance(item["source_in_us"], int)
    assert item["source_out_us"] - item["source_in_us"] == item["timeline_duration_us"]
    assert item["subtitles"][0]["text"] == "[mock transcript]"

    corrected = (
        initialized.config.artifact_root / "transcripts" / asset.asset_id / "corrected.jsonl"
    )
    corrected.write_text(corrected.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    stale = runner.invoke(
        app,
        [
            "cutlist",
            "scaffold",
            "--project",
            str(project),
            "--asset",
            asset.asset_id,
            "--output",
            str(output),
            "--force",
            "--json",
        ],
    )
    assert stale.exit_code == ExitCode.PREFLIGHT_FAILED
    assert json.loads(stale.stdout)["error"]["code"] == "corrected_transcript_required"
