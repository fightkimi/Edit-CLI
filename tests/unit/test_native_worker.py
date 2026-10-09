from __future__ import annotations

from types import SimpleNamespace

import pytest

from interview_edit.adapters import jianying_legacy_worker as worker
from interview_edit.adapters.native_capabilities import legacy_supported


@pytest.mark.parametrize(
    "version,expected",
    [("5.9.0", True), ("6.8", True), ("7.0", False), ("11.5.0", False), ("unknown", False)],
)
def test_legacy_capability_is_version_bounded(version, expected):
    assert (
        legacy_supported({"platform": "windows", "installed": True, "appVersion": version})
        is expected
    )
    assert not legacy_supported({"platform": "macos", "installed": True, "appVersion": version})


@pytest.mark.parametrize(
    "outside,existing,expected", [(False, False, 0), (True, False, 6), (False, True, 6)]
)
def test_worker_checks_native_path_before_export_click(
    tmp_path, monkeypatch, outside, existing, expected
):
    job = tmp_path / "job"
    job.mkdir()
    target = job / "incoming.mp4"
    native = (tmp_path if outside else job) / "native.mp4"
    if existing:
        native.write_bytes(b"previous")
    clicked = []

    class Control:
        def __init__(self, desc):
            self.desc = desc

        def GetPropertyValue(self, prop):
            return self.desc

        def GetSiblingControl(self, predicate):
            return Control(str(native))

        def Click(self, *args, **kwargs):
            clicked.append(self.desc)

    class Window:
        def TextControl(self, **kwargs):
            return Control(kwargs["Compare"])

    class Controller:
        app_status = "home"

        def __init__(self):
            self.app = Window()

        def get_window(self):
            self.app = Window()

        def export_draft(self, name, output, **kwargs):
            assert output is None
            self.get_window()
            self.app.TextControl(Compare="ExportOkBtn").Click()
            native.write_bytes(b"completed")

    sdk = SimpleNamespace(
        ExportResolution=SimpleNamespace(RES_1080P="1080P"),
        ExportFramerate=SimpleNamespace(FR_25="25fps"),
        JianyingController=Controller,
    )
    module = SimpleNamespace(ControlFinder=SimpleNamespace(desc_matcher=lambda name: name))
    monkeypatch.setattr(worker.sys, "platform", "win32")
    monkeypatch.setattr(
        worker,
        "inspect_jianying",
        lambda: {"platform": "windows", "installed": True, "appVersion": "5.9.0"},
    )
    monkeypatch.setattr(
        worker.importlib, "import_module", lambda name: sdk if name == "pyJianYingDraft" else module
    )
    monkeypatch.setattr(
        worker.sys,
        "argv",
        [
            "worker",
            "--name",
            "Example",
            "--output",
            str(target),
            "--height",
            "1080",
            "--fps",
            "25",
            "--timeout",
            "30",
        ],
    )
    assert worker.main() == expected
    if expected == 0:
        assert target.read_bytes() == b"completed" and clicked == ["ExportOkBtn"]
    else:
        assert not target.exists() and not clicked
        assert native.read_bytes() == b"previous" if existing else not native.exists()
