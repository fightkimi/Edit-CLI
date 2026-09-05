from __future__ import annotations

import json

import pytest

from interview_edit.cli.output import emit_expected_error
from interview_edit.errors import DependencyError
from interview_edit.models.protocol import JsonEnvelope


def test_json_envelope_uses_stable_camel_case_aliases() -> None:
    envelope = JsonEnvelope(ok=True, command="status")

    payload = json.loads(envelope.model_dump_json(by_alias=True, exclude_none=True))

    assert payload == {
        "schemaVersion": "1",
        "ok": True,
        "command": "status",
        "data": {},
        "warnings": [],
        "artifacts": [],
        "next": [],
    }


def test_expected_error_promotes_operation_run_id_to_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_expected_error(
        DependencyError(
            "ffmpeg_missing",
            "FFmpeg is missing.",
            details={"runId": "proxy_20260904T000000Z_0123456789", "runManifestPath": "/log"},
        ),
        command="proxy build",
        json_output=True,
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["runId"] == "proxy_20260904T000000Z_0123456789"
    assert "runId" not in payload["error"]["details"]
    assert payload["error"]["details"]["runManifestPath"] == "/log"
