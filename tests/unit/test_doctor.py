from __future__ import annotations

from pathlib import Path

import pytest

from interview_edit.adapters.process import ProcessResult
from interview_edit.config.models import PrivacyMode, ProjectConfig
from interview_edit.doctor import service
from interview_edit.exit_codes import ExitCode


class FakeRunner:
    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: float = 30,
    ) -> ProcessResult:
        del cwd, timeout_seconds
        if "-version" in args:
            return ProcessResult(tuple(args), 0, f"{Path(args[0]).name} version test\n", "")
        if "-encoders" in args:
            return ProcessResult(tuple(args), 0, "libx264 h264_videotoolbox\naac\n", "")
        if "-filters" in args:
            return ProcessResult(
                tuple(args),
                0,
                "overlay fade loudnorm concat blackdetect silencedetect select\n",
                "",
            )
        if "h264_videotoolbox" in args:
            return ProcessResult(tuple(args), 1, "", "sandbox denied encoder")
        return ProcessResult(tuple(args), 0, "", "")


class FallbackRunner(FakeRunner):
    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: float = 30,
    ) -> ProcessResult:
        if args[-2:] == ["-c", "import mlx_whisper"]:
            return ProcessResult(tuple(args), 1, "", "Metal unavailable")
        return super().run(args, cwd=cwd, timeout_seconds=timeout_seconds)


class MissingPillowRunner(FakeRunner):
    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: float = 30,
    ) -> ProcessResult:
        if args[-2:] == ["-c", "import PIL"]:
            return ProcessResult(tuple(args), 1, "", "PIL unavailable")
        return super().run(args, cwd=cwd, timeout_seconds=timeout_seconds)


def test_doctor_accepts_portable_codecs_and_warns_on_hardware_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(service, "_module_available", lambda name: name == "mlx_whisper")
    report = service.run_doctor(
        runner=FakeRunner(),
        which=lambda name: f"/fake/{name}",
    )

    assert report.ok
    assert report.status == "degraded"
    assert any(
        check.name == "video_toolbox" and check.status == "warning" for check in report.checks
    )
    assert any(
        check.name == "transcription_backend" and "mlx-whisper" in check.message
        for check in report.checks
    )


def test_doctor_returns_dependency_exit_when_media_tools_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "_module_available", lambda _name: False)
    report = service.run_doctor(
        runner=FakeRunner(),
        which=lambda _name: None,
        probe_hardware=False,
    )

    assert not report.ok
    assert report.exit_code == ExitCode.DEPENDENCY_MISSING


def test_auto_transcription_falls_back_when_preferred_backend_is_unusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(service, "_module_available", lambda _name: True)

    report = service.run_doctor(
        runner=FallbackRunner(),
        which=lambda name: f"/fake/{name}",
    )

    assert report.ok
    assert any(check.name == "transcription_fallback" for check in report.checks)
    assert any(
        check.name == "transcription_backend" and check.details["selected"] == "faster-whisper"
        for check in report.checks
    )


def test_doctor_rejects_configured_media_artifact_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    config = ProjectConfig(
        project_id="prj_doctor_test",
        name="Doctor test",
        media_roots=[media],
        artifact_root=media / "generated",
        privacy_mode=PrivacyMode.STRICT,
    )
    monkeypatch.setattr(service, "_module_available", lambda name: name == "mlx_whisper")

    report = service.run_doctor(
        config,
        runner=FakeRunner(),
        which=lambda name: f"/fake/{name}",
    )

    assert not report.ok
    assert report.exit_code == ExitCode.PATH_ERROR
    assert any(check.name == "path_boundaries" for check in report.checks)


def test_doctor_requires_local_text_rasterizer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_module_available", lambda name: name == "mlx_whisper")

    report = service.run_doctor(
        runner=MissingPillowRunner(),
        which=lambda name: f"/fake/{name}",
        probe_hardware=False,
    )

    check = next(value for value in report.checks if value.name == "text_rasterizer")
    assert check.status == "fail"
    assert report.exit_code == ExitCode.DEPENDENCY_MISSING
