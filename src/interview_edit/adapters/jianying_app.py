from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path
from typing import Any, Literal

from interview_edit.errors import DependencyError


def host_platform() -> Literal["macos", "windows"]:
    if sys.platform not in {"win32", "darwin"}:
        raise DependencyError(
            "jianying_host_unsupported", "Native client detection requires Mac or Windows."
        )
    return "windows" if sys.platform == "win32" else "macos"


def inspect_jianying() -> dict[str, Any]:
    user_root = Path.home()
    selected = host_platform()
    version: str | None = None
    app: Path | None = None
    if selected == "macos":
        draft_root = user_root / "Movies/JianyingPro/User Data/Projects/com.lveditor.draft"
        for base in (Path("/Applications"), user_root / "Applications"):
            for candidate in sorted(base.glob("*.app")):
                try:
                    info = plistlib.loads((candidate / "Contents/Info.plist").read_bytes())
                except (OSError, ValueError):
                    continue
                if info.get("CFBundleIdentifier") in {"com.lemon.lvpro", "com.lemon.lv"}:
                    app = candidate
                    version = str(info.get("CFBundleShortVersionString", "unknown"))
                    break
    else:
        local_root = Path(os.environ.get("LOCALAPPDATA", str(user_root / "AppData/Local")))
        base = local_root / "JianyingPro"
        draft_root = base / "User Data/Projects/com.lveditor.draft"
        candidates = [base / "JianyingPro.exe", *sorted(base.glob("*/JianyingPro.exe"))]
        app = next((p for p in candidates if p.is_file()), None)
    return {
        "platform": selected,
        "appPath": str(app) if app else None,
        "appVersion": version,
        "installed": app is not None,
        "draftRoot": str(draft_root),
        "draftRootExists": draft_root.is_dir(),
        "nativeValidation": "not_run",
    }
