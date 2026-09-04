from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from interview_edit.cli.app import app
from interview_edit.exit_codes import ExitCode

runner = CliRunner()


def test_help_and_version_are_available() -> None:
    help_result = runner.invoke(app, ["--help"])
    version_result = runner.invoke(app, ["--version"])

    assert help_result.exit_code == ExitCode.SUCCESS
    assert "init" in help_result.stdout
    assert "doctor" in help_result.stdout
    assert "status" in help_result.stdout
    assert version_result.exit_code == ExitCode.SUCCESS
    assert version_result.stdout.strip() == "0.6.0"


def test_init_and_status_emit_parseable_json_with_unicode_paths(tmp_path: Path) -> None:
    media = tmp_path / "原始 素材"
    media.mkdir()
    (media / "只读.txt").write_text("unchanged", encoding="utf-8")
    project = tmp_path / "项目 空间"

    init_result = runner.invoke(
        app,
        [
            "init",
            "--project",
            str(project),
            "--name",
            "自媒体测试",
            "--media-root",
            str(media),
            "--privacy",
            "assisted",
            "--json",
        ],
    )

    assert init_result.exit_code == ExitCode.SUCCESS, init_result.output
    init_payload = json.loads(init_result.stdout)
    assert init_payload["ok"] is True
    assert init_payload["data"]["privacyMode"] == "assisted"
    assert "\u001b" not in init_result.stdout

    status_result = runner.invoke(app, ["status", "--project", str(project), "--json"])
    assert status_result.exit_code == ExitCode.SUCCESS, status_result.output
    status_payload = json.loads(status_result.stdout)
    assert status_payload["schemaVersion"] == "1"
    assert status_payload["data"]["stages"]["ingest"]["state"] == "missing"
    assert status_payload["next"] == [
        f"interview-edit doctor --project '{project}'",
        f"interview-edit ingest --project '{project}'",
    ]
    assert (media / "只读.txt").read_text(encoding="utf-8") == "unchanged"


def test_init_validation_error_uses_json_envelope(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()

    result = runner.invoke(
        app,
        [
            "init",
            "--project",
            str(tmp_path / "project"),
            "--name",
            "Test",
            "--media-root",
            str(media),
            "--privacy",
            "hidden-default",
            "--json",
        ],
    )

    assert result.exit_code == ExitCode.USAGE_ERROR
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "privacy_required"


def test_status_missing_project_is_exit_two_with_json() -> None:
    result = runner.invoke(app, ["status", "--json"])

    assert result.exit_code == ExitCode.USAGE_ERROR
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "project_required"
