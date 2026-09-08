from __future__ import annotations

import json
import plistlib
import sys
from pathlib import Path

import pytest

from interview_edit.adapters import jianying_app as native
from interview_edit.errors import DependencyError, ProcessingError


def test_detect_macos_bundle_and_explicit_library(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "host_platform", lambda: "macos")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    app = tmp_path / "Applications/剪映专业版.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(
        plistlib.dumps(
            {"CFBundleIdentifier": "com.lemon.lvpro", "CFBundleShortVersionString": "99.1.2"}
        )
    )
    root = tmp_path / "custom drafts"
    root.mkdir()
    result = native.inspect_jianying(draft_root=root)
    assert result["appPath"] == str(app)
    assert result["appVersion"] == "99.1.2"
    assert result["draftRoot"] == str(root)
    assert result["compatibility"] == "unverified"
    assert result["nativeValidation"] == "not_run"


def test_detect_latest_windows_candidate_without_guessing_version(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "host_platform", lambda: "windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for version in ["9.0.0", "10.0.0"]:
        exe = tmp_path / "JianyingPro" / version / "JianyingPro.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"not a real executable")
    result = native.inspect_jianying()
    assert "10.0.0" in result["appPath"]
    assert result["appVersion"] is None
    assert result["compatibility"] == "unverified"


def test_launch_missing_client_is_explicit(monkeypatch):
    monkeypatch.setattr(native, "inspect_jianying", lambda **kw: {"installed": False})
    with pytest.raises(DependencyError):
        native.launch_jianying()


def test_launch_dry_run_has_no_side_effects(monkeypatch, tmp_path):
    monkeypatch.setattr(
        native,
        "inspect_jianying",
        lambda **kw: {
            "installed": True,
            "appPath": str(tmp_path),
            "platform": "macos",
            "nativeValidation": "not_run",
        },
    )
    monkeypatch.setattr(native, "start_application", lambda *a: pytest.fail("must not launch"))
    result = native.launch_jianying(dry_run=True)
    assert result["launchRequested"] is False
    assert result["nativeValidation"] == "not_run"
    assert json.dumps(result)


def test_launch_error_does_not_claim_success(monkeypatch, tmp_path):
    monkeypatch.setattr(
        native,
        "inspect_jianying",
        lambda **kw: {"installed": True, "appPath": str(tmp_path), "platform": "macos"},
    )

    def fail(*args):
        raise OSError("cannot launch")

    monkeypatch.setattr(native, "start_application", fail)
    with pytest.raises(ProcessingError):
        native.launch_jianying()


@pytest.mark.skipif(sys.platform != "win32", reason="Real Windows version API")
def test_windows_version_api_on_python_executable():
    version = native.windows_file_version(Path(sys.executable))
    assert version is not None and version.startswith(
        f"{sys.version_info.major}.{sys.version_info.minor}."
    )
