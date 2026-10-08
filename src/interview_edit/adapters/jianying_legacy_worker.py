"""Optional Windows <=6 driver, isolated so the caller can impose a hard timeout."""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from interview_edit.adapters.jianying_app import inspect_jianying
from interview_edit.adapters.native_capabilities import legacy_supported
from interview_edit.project.layout import validate_artifact_path


class ExportPathBlocked(Exception):
    pass


class GuardControl:
    def __init__(self, control: Any, check: Callable[[], None]):
        self.control, self.check = control, check

    def __getattr__(self, name: str) -> Any:
        return getattr(self.control, name)

    def Click(self, *args: Any, **kwargs: Any) -> Any:
        if str(self.control.GetPropertyValue(30159)).lower() == "exportokbtn":
            self.check()
        return self.control.Click(*args, **kwargs)


class GuardWindow:
    def __init__(self, window: Any, check: Callable[[], None]):
        self.window, self.check = window, check

    def __getattr__(self, name: str) -> Any:
        return getattr(self.window, name)

    def TextControl(self, *args: Any, **kwargs: Any) -> GuardControl:
        return GuardControl(self.window.TextControl(*args, **kwargs), self.check)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--height", required=True, type=int)
    parser.add_argument("--fps", required=True, type=int)
    parser.add_argument("--timeout", required=True, type=int)
    args = parser.parse_args()
    if sys.platform != "win32" or not legacy_supported(inspect_jianying()):
        return 4
    try:
        sdk = importlib.import_module("pyJianYingDraft")
        resolution = getattr(sdk.ExportResolution, f"RES_{args.height}P")
        rate = getattr(sdk.ExportFramerate, f"FR_{args.fps}")
        controller = sdk.JianyingController()
        if controller.app_status != "home":
            return 5
        actual: Path | None = None
        target = Path(args.output).resolve()

        def check_path() -> None:
            nonlocal actual
            controls = importlib.import_module("pyJianYingDraft.jianying_controller")
            sibling = controller.app.TextControl(
                searchDepth=2, Compare=controls.ControlFinder.desc_matcher("ExportPath")
            )
            path_control = sibling.GetSiblingControl(lambda ctrl: True)
            if path_control is None:
                raise ExportPathBlocked()
            candidate = Path(str(path_control.GetPropertyValue(30159)))
            try:
                candidate = validate_artifact_path(candidate, target.parent)
            except Exception as exc:
                raise ExportPathBlocked() from exc
            if candidate.exists():
                raise ExportPathBlocked()
            actual = candidate

        original_get_window = controller.get_window

        def get_window() -> None:
            original_get_window()
            controller.app = GuardWindow(controller.app, check_path)

        controller.get_window = get_window
        controller.export_draft(
            args.name, None, resolution=resolution, framerate=rate, timeout=args.timeout
        )
        if actual is None or not actual.is_file() or actual.is_symlink():
            return 3
        if actual != target:
            if target.exists():
                return 6
            actual.rename(target)
        return 0
    except ExportPathBlocked:
        return 6
    except (ImportError, AttributeError):
        return 4
    except Exception:
        # Do not send potentially content-bearing SDK exceptions to machine stdout.
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
