from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_user_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERVIEW_EDIT_USER_CONFIG", "")
