from __future__ import annotations

import ctypes
import os
import plistlib
import re
import sys
from pathlib import Path
from typing import Any, Literal

from interview_edit.adapters.process import SubprocessRunner
from interview_edit.errors import DependencyError, ProcessingError


def host_platform() -> Literal["macos", "windows"]:
    if sys.platform not in {"win32", "darwin"}:
        raise DependencyError(
            "jianying_host_unsupported", "Native client detection requires Mac or Windows."
        )
    return "windows" if sys.platform == "win32" else "macos"


def inspect_jianying(*, draft_root: Path | None = None) -> dict[str, Any]:
    override = draft_root or os.environ.get("INTERVIEW_EDIT_JIANYING_DRAFT_ROOT")
    user_root = Path.home()
    selected = host_platform()
    version: str | None = None
    app: Path | None = None
    if selected == "macos":
        draft_root = user_root / "Movies/JianyingPro/User Data/Projects/com.lveditor.draft"
        for base in (user_root / "Applications", Path("/Applications")):
            for candidate in sorted(base.glob("*.app")):
                try:
                    info = plistlib.loads((candidate / "Contents/Info.plist").read_bytes())
                except (OSError, ValueError):
                    continue
                if info.get("CFBundleIdentifier") in {"com.lemon.lvpro", "com.lemon.lv"}:
                    app = candidate
                    version = str(info.get("CFBundleShortVersionString", "unknown"))
                    break
            if app is not None:
                break
    else:
        local_root = Path(os.environ.get("LOCALAPPDATA", str(user_root / "AppData/Local")))
        base = local_root / "JianyingPro"
        draft_root = base / "User Data/Projects/com.lveditor.draft"
        candidates = [
            base / "JianyingPro.exe",
            *sorted(
                base.glob("*/JianyingPro.exe"),
                key=lambda p: tuple(int(v) for v in re.findall(r"\d+", p.parent.name)),
                reverse=True,
            ),
        ]
        app = next((p for p in candidates if p.is_file()), None)
        if app is not None:
            version = windows_file_version(app)
    if override:
        draft_root = Path(override).expanduser().resolve()
    return {
        "platform": selected,
        "appPath": str(app) if app else None,
        "appVersion": version,
        "installed": app is not None,
        "draftRoot": str(draft_root),
        "draftRootExists": draft_root.is_dir(),
        "nativeValidation": "not_run",
        "compatibility": "unverified",
        "draftRootSource": "explicit" if override else "default",
        "automatedExport": False,
    }


def windows_file_version(path: Path) -> str | None:
    """Read PE version metadata without running the candidate executable."""
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    dll = ctypes.WinDLL("version", use_last_error=True)
    dll.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    dll.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    dll.GetFileVersionInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    dll.GetFileVersionInfoW.restype = wintypes.BOOL
    dll.VerQueryValueW.argtypes = [
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.UINT),
    ]
    dll.VerQueryValueW.restype = wintypes.BOOL
    size = dll.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    buffer = ctypes.create_string_buffer(size)
    if not dll.GetFileVersionInfoW(str(path), 0, size, buffer):
        return None
    pointer = ctypes.c_void_p()
    length = wintypes.UINT()
    if (
        not dll.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length))
        or length.value < 16
    ):
        return None
    values = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
    if values[0] != 0xFEEF04BD:
        return None
    major, minor = values[2], values[3]
    return f"{major >> 16}.{major & 0xFFFF}.{minor >> 16}.{minor & 0xFFFF}"


def start_application(path: Path, selected: str) -> None:
    if selected == "windows":
        if sys.platform == "win32":
            os.startfile(str(path))
        else:
            raise DependencyError("jianying_host_unsupported", "Windows launch requires Windows.")
    else:
        result = SubprocessRunner().run(["/usr/bin/open", "-a", str(path)])
        if result.return_code != 0:
            raise ProcessingError(
                "jianying_launch_failed", "The operating system could not launch Jianying."
            )


def launch_jianying(*, dry_run: bool = False) -> dict[str, Any]:
    client = inspect_jianying()
    if not client["installed"]:
        raise DependencyError("jianying_missing", "Install Jianying before launching it.")
    if not dry_run:
        try:
            start_application(Path(client["appPath"]), client["platform"])
        except OSError as exc:
            raise ProcessingError(
                "jianying_launch_failed", "The operating system could not launch Jianying."
            ) from exc
    return {
        **client,
        "launchRequested": not dry_run,
        "dryRun": dry_run,
        "nativeValidation": "not_run",
    }
