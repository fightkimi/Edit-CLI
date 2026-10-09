from __future__ import annotations

import importlib.util
import re


def legacy_supported(client: dict[str, object]) -> bool:
    version = str(client.get("appVersion") or "")
    match = re.fullmatch(r"(\d+)\.\d+(?:\.\d+)*", version)
    return (
        client.get("installed") is True
        and client.get("platform") == "windows"
        and bool(match and 5 <= int(match[1]) <= 6)
    )


def export_backends(client: dict[str, object]) -> dict[str, dict[str, bool | str]]:
    eligible = legacy_supported(client)
    dependency = importlib.util.find_spec("pyJianYingDraft") is not None if eligible else False
    return {
        "manual": {"available": True, "automated": False},
        "windows-legacy": {
            "available": eligible and dependency,
            "eligible": eligible,
            "dependencyInstalled": dependency,
            "nativeValidation": "not_run",
        },
    }
