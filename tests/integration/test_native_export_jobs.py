from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from interview_edit.adapters.process import ProcessResult
from interview_edit.cli.app import app
from interview_edit.cutlist.service import serialize_cutlist
from interview_edit.errors import DependencyError, PreflightError, UsageError
from interview_edit.export import native_jobs
from interview_edit.export.jianying import export_jianying
from interview_edit.export.jianying_install import install_draft
from interview_edit.export.native_jobs import (
    create_job,
    finish_job,
    load_job,
    operation,
    run_legacy_job,
)
from interview_edit.render.service import RenderRequest, render_cutlist
from tests.fixtures.media_factory import make_video
from tests.integration.test_jianying_output import setup


def fixture(tmp_path):
    config, path, doc = setup(tmp_path)
    package = export_jianying(config, doc, path, name="Jobs").draft_path
    video = tmp_path / "reported-native.mp4"
    make_video(video)
    return config, package, video


def test_manual_job_checks_publish_idempotence_and_immutable_sources(tmp_path):
    config, package, video = fixture(tmp_path)
    raw = video.read_bytes()
    planned, job = create_job(config, package, dry_run=True)
    assert not planned.exists()
    root, job = create_job(config, package)
    _, completed = finish_job(config, job.job_id, video)
    assert completed.state == "succeeded" and completed.native_validation == "not_run"
    assert (root / "result/video.mp4").read_bytes() == raw == video.read_bytes()
    assert finish_job(config, job.job_id, video)[1].output_sha256 == completed.output_sha256
    (root / "result/output-check.json").write_text("{}")
    with pytest.raises(PreflightError) as corrupt:
        load_job(config, job.job_id)
    assert corrupt.value.code == "jianying_job_output_changed"


def test_failed_partial_job_can_finish_later_and_never_publishes_partial(tmp_path):
    config, package, video = fixture(tmp_path)
    root, job = create_job(config, package)
    partial = root / "incoming.mp4"
    partial.write_bytes(b"partial")
    with pytest.raises(PreflightError):
        finish_job(config, job.job_id, partial)
    assert load_job(config, job.job_id)[1].state == "failed"
    assert not (root / "result").exists() and partial.read_bytes() == b"partial"
    assert finish_job(config, job.job_id, video)[1].state == "succeeded"


def test_job_recovers_atomic_result_after_status_write_interruption(tmp_path, monkeypatch):
    config, package, video = fixture(tmp_path)
    root, job = create_job(config, package)
    original = native_jobs.save_job

    def interrupted(path, value):
        if value.state == "succeeded":
            raise OSError("interrupted")
        original(path, value)

    monkeypatch.setattr(native_jobs, "save_job", interrupted)
    with pytest.raises(OSError):
        finish_job(config, job.job_id, video)
    assert json.loads((root / "job.json").read_text())["state"] == "planned"
    assert load_job(config, job.job_id)[1].state == "succeeded"


def test_job_rejects_concurrent_completion_and_changed_package(tmp_path):
    config, package, video = fixture(tmp_path)
    root, job = create_job(config, package)
    with operation(root), pytest.raises(PreflightError) as busy:
        finish_job(config, job.job_id, video)
    assert busy.value.code == "jianying_job_busy"
    control = package / "export-manifest.json"
    data = json.loads(control.read_text())
    data["created_at"] = "changed"
    control.write_text(json.dumps(data))
    with pytest.raises(PreflightError) as changed:
        finish_job(config, job.job_id, video)
    assert changed.value.code == "jianying_job_input_changed"


def legacy_fixture(tmp_path, monkeypatch):
    config, path, doc = setup(tmp_path)
    doc.timeline.width = 1280
    doc.timeline.height = 720
    path.write_text(serialize_cutlist(doc))
    package = export_jianying(config, doc, path, name="Unique legacy").draft_path
    library = tmp_path / "library"
    library.mkdir()
    installed = install_draft(package, library, "windows")
    video = render_cutlist(
        RenderRequest(
            config=config,
            project_root=path.parents[2],
            cutlist=doc,
            cutlist_path=path,
            profile_name="preview",
        )
    ).output.path
    monkeypatch.setattr(
        native_jobs,
        "inspect_jianying",
        lambda: {
            "platform": "windows",
            "appVersion": "5.9.0",
            "installed": True,
            "draftRoot": str(library),
        },
    )
    return config, package, installed, Path(video)


def test_legacy_export_is_approved_bounded_and_input_bound_without_real_gui(tmp_path, monkeypatch):
    config, package, installed, video = legacy_fixture(tmp_path, monkeypatch)
    root, job = create_job(config, package, backend="windows-legacy", installed=installed)

    class Driver:
        def run(self, args, **kwargs):
            assert kwargs["timeout_seconds"] == 45
            assert args[1:3] == ["-m", "interview_edit.adapters.jianying_legacy_worker"]
            shutil.copyfile(video, args[args.index("--output") + 1])
            return ProcessResult(tuple(args), 0, "private SDK output", "")

    with pytest.raises(UsageError):
        run_legacy_job(config, job.job_id, runner=Driver())
    assert (
        run_legacy_job(config, job.job_id, approved=True, timeout_seconds=30, runner=Driver())[
            1
        ].state
        == "succeeded"
    )
    assert (root / "result/video.mp4").exists()


def test_legacy_timeout_keeps_partial_and_changed_installed_draft_blocks_finish(
    tmp_path, monkeypatch
):
    config, package, installed, video = legacy_fixture(tmp_path, monkeypatch)
    root, job = create_job(config, package, backend="windows-legacy", installed=installed)

    class Timeout:
        def run(self, args, **kwargs):
            Path(args[args.index("--output") + 1]).write_bytes(b"partial")
            return ProcessResult(tuple(args), 124, "", "timeout")

    with pytest.raises(PreflightError):
        run_legacy_job(config, job.job_id, approved=True, runner=Timeout())
    assert load_job(config, job.job_id)[1].state == "failed"
    assert (root / "incoming.mp4").read_bytes() == b"partial"
    entry = installed / "draft_content.json"
    value = json.loads(entry.read_text())
    value["duration"] += 1
    entry.write_text(json.dumps(value))
    with pytest.raises(PreflightError) as changed:
        finish_job(config, job.job_id, video)
    assert changed.value.code == "jianying_job_input_changed"
    assert not (root / "result").exists()


def test_modern_client_rejected_before_job_and_cli_manual_flow(tmp_path, monkeypatch):
    config, package, video = fixture(tmp_path)
    monkeypatch.setattr(
        native_jobs,
        "inspect_jianying",
        lambda: {"platform": "windows", "appVersion": "11.5.0", "installed": True},
    )
    with pytest.raises(DependencyError):
        create_job(config, package, backend="windows-legacy")
    assert not (config.artifact_root / "native-exports").exists()
    runner = CliRunner()
    project = package.parents[2]
    project = config.artifact_root.parent
    result = runner.invoke(
        app,
        ["jianying", "export-video", "--project", str(project), "--draft", str(package), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    data = json.loads(result.stdout)["data"]
    assert data["outputPath"] is None and data["state"] == "planned"
    result = runner.invoke(
        app,
        [
            "jianying",
            "finish-export",
            "--project",
            str(project),
            "--job",
            data["jobId"],
            "--video",
            str(video),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["data"]["state"] == "succeeded"
