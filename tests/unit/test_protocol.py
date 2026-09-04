from __future__ import annotations

import json

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
