from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from interview_edit.adapters.process import SubprocessRunner
from interview_edit.cli.app import app
from interview_edit.config.loader import load_project_config
from interview_edit.cutlist.service import serialize_cutlist
from interview_edit.exit_codes import ExitCode
from interview_edit.ingest.service import IngestRequest, ingest_media
from interview_edit.models.cutlist import Act, CutList, TimelineItem
from interview_edit.project.service import InitRequest, initialize_project
from interview_edit.render.service import RenderRequest, render_cutlist
from interview_edit.status.service import read_project_status
from tests.fixtures.media_factory import make_video, require_media_tools

runner = CliRunner()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_problem_video(path: Path) -> None:
    ffmpeg, _ = require_media_tools()
    path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:r=25:d=3.4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=0.4",
            "-filter_complex",
            "[1:a]apad=whole_dur=3.4,atrim=duration=3.4[a]",
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-y",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        pytest.skip(f"local FFmpeg cannot create QC fixture: {completed.stderr}")


def _master_project(tmp_path: Path, *, problem: bool = False) -> tuple[Path, Path, Path, str]:
    require_media_tools()
    media = tmp_path / "media"
    source = media / "release source.mp4"
    if problem:
        _make_problem_video(source)
    else:
        make_video(source, color="blue", frequency=440, duration_seconds=3.4)
    initialized = initialize_project(
        InitRequest(
            project=tmp_path / "project",
            name="M5 release",
            media_roots=[media],
            privacy="strict",
        )
    )
    indexed = ingest_media(IngestRequest(config=initialized.config), runner=SubprocessRunner())
    asset = indexed.index.assets[0]
    document = CutList(
        project_id=initialized.config.project_id,
        acts=[
            Act(
                act_id="act_001",
                items=[
                    TimelineItem(
                        item_id="item_001",
                        kind="primary",
                        source_id=asset.asset_id,
                        source_in_us=0,
                        source_out_us=1_500_000,
                        timeline_duration_us=1_500_000,
                        audio_source=asset.asset_id,
                    ),
                    TimelineItem(
                        item_id="item_002",
                        kind="primary",
                        source_id=asset.asset_id,
                        source_in_us=1_500_000,
                        source_out_us=3_000_000,
                        timeline_duration_us=1_500_000,
                        audio_source=asset.asset_id,
                    ),
                ],
            )
        ],
    )
    project = initialized.config.artifact_root.parent
    cutlist_path = project / "cutlists" / "revisions" / "release.yaml"
    cutlist_path.write_text(serialize_cutlist(document), encoding="utf-8")
    rendered = render_cutlist(
        RenderRequest(
            config=initialized.config,
            project_root=project,
            cutlist=document,
            cutlist_path=cutlist_path,
            profile_name="master",
        ),
        runner=SubprocessRunner(),
    )
    assert rendered.run_id is not None
    return project, cutlist_path, source, rendered.run_id


def test_release_qc_measures_master_and_writes_cut_evidence(tmp_path: Path) -> None:
    project, _, source, run_id = _master_project(tmp_path)
    source_sha = _sha256(source)

    dry_run = runner.invoke(
        app,
        [
            "--dry-run",
            "qc",
            "--project",
            str(project),
            "--run",
            run_id,
            "--policy",
            "release",
            "--json",
        ],
    )
    assert dry_run.exit_code == ExitCode.SUCCESS, dry_run.output
    assert json.loads(dry_run.stdout)["data"]["dryRun"] is True
    assert not list((project / "artifacts" / "qc").glob("qc_*/report.json"))

    result = runner.invoke(
        app,
        [
            "qc",
            "--project",
            str(project),
            "--run",
            run_id,
            "--policy",
            "release",
            "--json",
        ],
    )

    assert result.exit_code == ExitCode.SUCCESS, result.output
    payload = json.loads(result.stdout)
    report = payload["data"]["report"]
    assert report["state"] == "passed"
    assert report["policy"] == "release"
    assert report["measurements"]["loudness"]["integrated_lufs"] is not None
    assert {command["purpose"] for command in report["commands"]} >= {
        "probe render output",
        "detect black intervals",
        "detect silent intervals",
        "measure output loudness",
        "extract QC frame at 1400000 us",
        "extract QC frame at 1600000 us",
    }
    assert [evidence["kind"] for evidence in report["evidence"]] == [
        "cut_before",
        "cut_after",
    ]
    assert all(Path(evidence["path"]).is_file() for evidence in report["evidence"])
    assert Path(payload["data"]["reportPath"]).is_file()
    assert _sha256(source) == source_sha


def test_preview_warns_but_release_fails_for_unplanned_black_and_silence(
    tmp_path: Path,
) -> None:
    project, _, _, run_id = _master_project(tmp_path, problem=True)

    preview = runner.invoke(
        app,
        [
            "qc",
            "--project",
            str(project),
            "--run",
            run_id,
            "--policy",
            "preview",
            "--json",
        ],
    )
    release = runner.invoke(
        app,
        [
            "qc",
            "--project",
            str(project),
            "--run",
            run_id,
            "--policy",
            "release",
            "--json",
        ],
    )

    assert preview.exit_code == ExitCode.SUCCESS, preview.output
    preview_findings = json.loads(preview.stdout)["data"]["report"]["findings"]
    preview_by_code = {finding["code"]: finding for finding in preview_findings}
    assert preview_by_code["black_interval"]["severity"] == "warning"
    assert preview_by_code["silence_interval"]["severity"] == "warning"
    assert release.exit_code == ExitCode.PREFLIGHT_FAILED, release.output
    release_payload = json.loads(release.stdout)
    release_by_code = {
        finding["code"]: finding for finding in release_payload["data"]["report"]["findings"]
    }
    assert release_by_code["black_interval"]["severity"] == "error"
    assert release_by_code["silence_interval"]["severity"] == "error"
    assert release_payload["error"]["code"] == "qc_failed"


def test_freeze_requires_separate_approval_and_verify_detects_tampering(
    tmp_path: Path,
) -> None:
    project, _, source, run_id = _master_project(tmp_path)
    source_sha = _sha256(source)
    qc_result = runner.invoke(
        app,
        [
            "qc",
            "--project",
            str(project),
            "--run",
            run_id,
            "--policy",
            "release",
            "--json",
        ],
    )
    assert qc_result.exit_code == ExitCode.SUCCESS, qc_result.output

    unapproved = runner.invoke(
        app,
        [
            "version",
            "freeze",
            "--project",
            str(project),
            "--run",
            run_id,
            "--json",
        ],
    )
    assert unapproved.exit_code == ExitCode.USAGE_ERROR, unapproved.output
    assert json.loads(unapproved.stdout)["error"]["code"] == "freeze_approval_required"

    frozen = runner.invoke(
        app,
        [
            "version",
            "freeze",
            "--project",
            str(project),
            "--run",
            run_id,
            "--approve",
            "--note",
            "release candidate",
            "--json",
        ],
    )
    assert frozen.exit_code == ExitCode.SUCCESS, frozen.output
    frozen_payload = json.loads(frozen.stdout)
    assert frozen_payload["data"]["version"]["version_id"] == "v0001"
    version_path = Path(frozen_payload["data"]["versionPath"])
    assert version_path.is_dir()
    roles = {entry["role"] for entry in frozen_payload["data"]["version"]["files"]}
    assert roles == {
        "output",
        "render_run",
        "release_qc",
        "qc_checksum",
        "qc_evidence",
        "config",
        "cutlist",
    }
    frozen_qc_root = version_path / "evidence" / "release-qc"
    assert (frozen_qc_root / "report.json").is_file()
    assert (frozen_qc_root / "report.sha256").is_file()
    assert len(list((frozen_qc_root / "evidence").glob("*.jpg"))) == 2

    listed = runner.invoke(app, ["version", "list", "--project", str(project), "--json"])
    shown = runner.invoke(app, ["version", "show", "v0001", "--project", str(project), "--json"])
    verified = runner.invoke(
        app, ["version", "verify", "v0001", "--project", str(project), "--json"]
    )
    assert listed.exit_code == ExitCode.SUCCESS, listed.output
    assert json.loads(listed.stdout)["data"]["versions"][0]["version_id"] == "v0001"
    assert shown.exit_code == ExitCode.SUCCESS, shown.output
    assert json.loads(shown.stdout)["data"]["version"]["note"] == "release candidate"
    assert verified.exit_code == ExitCode.SUCCESS, verified.output
    assert json.loads(verified.stdout)["data"]["verification"]["state"] == "passed"
    current_status = read_project_status(
        load_project_config(project, environ={"INTERVIEW_EDIT_USER_CONFIG": ""}),
        project_root=project,
    )
    assert current_status.stages["render"]["validity"] == "current"
    assert current_status.stages["qc"]["validity"] == "current"
    assert current_status.stages["version"]["validity"] == "current"

    output_entry = next(
        entry for entry in frozen_payload["data"]["version"]["files"] if entry["role"] == "output"
    )
    frozen_output = version_path / output_entry["relative_path"]
    frozen_output.write_bytes(frozen_output.read_bytes() + b"tampered")
    tampered = runner.invoke(
        app, ["version", "verify", "v0001", "--project", str(project), "--json"]
    )
    assert tampered.exit_code == ExitCode.PREFLIGHT_FAILED, tampered.output
    tampered_payload = json.loads(tampered.stdout)
    assert tampered_payload["error"]["code"] == "version_verification_failed"
    assert {issue["code"] for issue in tampered_payload["data"]["verification"]["issues"]} >= {
        "frozen_file_modified"
    }
    tampered_status = read_project_status(
        load_project_config(project, environ={"INTERVIEW_EDIT_USER_CONFIG": ""}),
        project_root=project,
    )
    assert tampered_status.stages["version"]["validity"] == "invalid"

    config_entry = next(
        entry for entry in frozen_payload["data"]["version"]["files"] if entry["role"] == "config"
    )
    cutlist_entry = next(
        entry for entry in frozen_payload["data"]["version"]["files"] if entry["role"] == "cutlist"
    )
    frozen_config = version_path / config_entry["relative_path"]
    frozen_config.unlink()
    frozen_config.symlink_to(version_path / cutlist_entry["relative_path"])
    symlinked = runner.invoke(
        app, ["version", "verify", "v0001", "--project", str(project), "--json"]
    )
    assert symlinked.exit_code == ExitCode.PREFLIGHT_FAILED, symlinked.output
    symlink_issues = json.loads(symlinked.stdout)["data"]["verification"]["issues"]
    assert "frozen_file_symlink" in {issue["code"] for issue in symlink_issues}
    assert _sha256(source) == source_sha


def test_failed_release_qc_cannot_freeze(tmp_path: Path) -> None:
    project, _, _, run_id = _master_project(tmp_path, problem=True)
    qc_result = runner.invoke(
        app,
        [
            "qc",
            "--project",
            str(project),
            "--run",
            run_id,
            "--policy",
            "release",
            "--json",
        ],
    )
    assert qc_result.exit_code == ExitCode.PREFLIGHT_FAILED, qc_result.output

    frozen = runner.invoke(
        app,
        [
            "version",
            "freeze",
            "--project",
            str(project),
            "--run",
            run_id,
            "--approve",
            "--json",
        ],
    )

    assert frozen.exit_code == ExitCode.PREFLIGHT_FAILED, frozen.output
    assert json.loads(frozen.stdout)["error"]["code"] == "release_qc_required"
    assert not list((project / "artifacts" / "versions").glob("v*"))


def test_qc_rejects_render_with_wrong_stream_parameters(tmp_path: Path) -> None:
    project, _, _, run_id = _master_project(tmp_path)
    run_path = project / "artifacts" / "renders" / "runs" / f"{run_id}.json"
    manifest = json.loads(run_path.read_text(encoding="utf-8"))
    output = Path(manifest["output"]["path"])
    wrong = tmp_path / "wrong-parameters.mp4"
    make_video(wrong, color="red", frequency=880, duration_seconds=3.0)
    output.write_bytes(wrong.read_bytes())
    manifest["output"]["size"] = output.stat().st_size
    manifest["output"]["sha256"] = _sha256(output)
    run_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "qc",
            "--project",
            str(project),
            "--run",
            run_id,
            "--policy",
            "preview",
            "--json",
        ],
    )

    assert result.exit_code == ExitCode.PREFLIGHT_FAILED, result.output
    payload = json.loads(result.stdout)
    codes = {finding["code"] for finding in payload["data"]["report"]["findings"]}
    assert {"video_width_mismatch", "video_height_mismatch", "audio_channels_mismatch"} <= codes


def test_modified_release_report_cannot_freeze(tmp_path: Path) -> None:
    project, _, _, run_id = _master_project(tmp_path)
    qc_result = runner.invoke(
        app,
        [
            "qc",
            "--project",
            str(project),
            "--run",
            run_id,
            "--policy",
            "release",
            "--json",
        ],
    )
    assert qc_result.exit_code == ExitCode.SUCCESS, qc_result.output
    report_path = Path(json.loads(qc_result.stdout)["data"]["reportPath"])
    report_path.write_text(report_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    frozen = runner.invoke(
        app,
        [
            "version",
            "freeze",
            "--project",
            str(project),
            "--run",
            run_id,
            "--approve",
            "--json",
        ],
    )

    assert frozen.exit_code == ExitCode.PREFLIGHT_FAILED, frozen.output
    assert json.loads(frozen.stdout)["error"]["code"] == "release_qc_modified"
