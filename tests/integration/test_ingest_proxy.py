from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from interview_edit.adapters.process import ProcessResult, SubprocessRunner
from interview_edit.cli.app import app
from interview_edit.errors import DependencyError, PathSafetyError, PreflightError
from interview_edit.exit_codes import ExitCode
from interview_edit.ingest.service import IngestRequest, ingest_media
from interview_edit.project.service import InitRequest, InitResult, initialize_project
from interview_edit.proxy.service import ProxyRequest, build_proxies
from interview_edit.status.service import read_project_status
from tests.fixtures.media_factory import make_video, require_media_tools

runner = CliRunner()


class InterruptAfterFirstAssetRunner:
    def __init__(self) -> None:
        self.delegate = SubprocessRunner()
        self.ffmpeg_jobs = 0

    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: float = 30,
    ) -> ProcessResult:
        if args[:1] == ["ffmpeg"] and args[1:2] != ["-version"]:
            self.ffmpeg_jobs += 1
            if self.ffmpeg_jobs == 4:
                raise KeyboardInterrupt
        return self.delegate.run(args, cwd=cwd, timeout_seconds=timeout_seconds)


class MissingToolsRunner:
    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: float = 30,
    ) -> ProcessResult:
        del cwd, timeout_seconds
        return ProcessResult(tuple(args), 127, "", "tool unavailable")


def _project(tmp_path: Path, media: Path) -> InitResult:
    return initialize_project(
        InitRequest(
            project=tmp_path / "编辑 项目",
            name="M2 creator test",
            media_roots=[media],
            privacy="assisted",
        )
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_ingest_is_idempotent_maps_camera_and_preserves_source(tmp_path: Path) -> None:
    require_media_tools()
    media = tmp_path / "原始 素材"
    source = media / "wide" / "中文 镜头 01.mp4"
    make_video(source)
    source_before = _sha256(source)
    project = _project(tmp_path, media)
    camera_map = tmp_path / "camera-map.yaml"
    camera_map.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "rules": [{"glob": "wide/**", "camera_id": "wide", "take_id": "take-01"}],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    first = ingest_media(
        IngestRequest(config=project.config, camera_map=camera_map, full_hash=True),
        runner=SubprocessRunner(),
    )
    second = ingest_media(
        IngestRequest(config=project.config, camera_map=camera_map, full_hash=True),
        runner=SubprocessRunner(),
    )

    assert len(first.index.assets) == 1
    assert first.index.assets[0].asset_id == second.index.assets[0].asset_id
    assert first.index.assets[0].camera_id == "wide"
    assert first.index.assets[0].take_id == "take-01"
    assert first.index.assets[0].full_hash is not None
    assert second.index.changes.unchanged == [first.index.assets[0].asset_id]
    assert second.index.changes.added == []
    assert _sha256(source) == source_before


def test_failed_probe_preserves_previous_index(tmp_path: Path) -> None:
    require_media_tools()
    media = tmp_path / "media"
    source = media / "valid.mp4"
    make_video(source)
    project = _project(tmp_path, media)
    ingest_media(IngestRequest(config=project.config), runner=SubprocessRunner())
    index_path = project.config.artifact_root / "index" / "media-index.json"
    before = index_path.read_bytes()
    (media / "broken.mp4").write_text("not media", encoding="utf-8")

    try:
        ingest_media(IngestRequest(config=project.config), runner=SubprocessRunner())
    except Exception as error:
        assert getattr(error, "code", None) == "media_probe_failed"
    else:
        raise AssertionError("broken media should fail ingest")

    assert index_path.read_bytes() == before


def test_proxy_build_caches_and_rebuilds_only_changed_asset(tmp_path: Path) -> None:
    require_media_tools()
    media = tmp_path / "media"
    first_source = media / "camera a" / "first.mp4"
    second_source = media / "camera b" / "second.mp4"
    make_video(first_source, color="red", frequency=440)
    make_video(second_source, color="green", frequency=660)
    project = _project(tmp_path, media)
    indexed = ingest_media(IngestRequest(config=project.config), runner=SubprocessRunner())

    first_build = build_proxies(
        ProxyRequest(config=project.config, index=indexed.index, resume=True),
        runner=SubprocessRunner(),
    )
    cached_build = build_proxies(
        ProxyRequest(config=project.config, index=indexed.index, resume=True),
        runner=SubprocessRunner(),
    )

    assert len(first_build.built) == 2
    assert len(cached_build.cached) == 2
    with pytest.raises(DependencyError) as failed_retry:
        build_proxies(
            ProxyRequest(config=project.config, index=indexed.index, resume=True),
            runner=MissingToolsRunner(),
        )
    assert isinstance(failed_retry.value.details["runId"], str)
    assert Path(failed_retry.value.details["runManifestPath"]).is_file()
    failed_retry_status = read_project_status(
        project.config, project_root=project.config.artifact_root.parent
    )
    assert failed_retry_status.stages["proxy"]["validity"] == "current"
    assert failed_retry_status.stages["proxy"]["latestRun"]["state"] == "failed"
    assert failed_retry_status.stages["proxy"]["latestRun"]["errorCode"] == "ffmpeg_missing"
    changed_config = project.config.model_copy(
        update={"proxy": project.config.proxy.model_copy(update={"crf": 29})}
    )
    changed_status = read_project_status(
        changed_config, project_root=project.config.artifact_root.parent
    )
    assert changed_status.stages["proxy"]["validity"] == "partial"
    assert changed_status.stages["proxy"]["reasonCodes"] == ["proxy_evidence_invalid"]
    for asset in indexed.index.assets:
        assert (project.config.artifact_root / "proxies" / f"{asset.asset_id}.mp4").is_file()
        assert (project.config.artifact_root / "audio" / f"{asset.asset_id}.wav").is_file()
        assert (project.config.artifact_root / "proxies" / f"{asset.asset_id}.jpg").is_file()
        time_map = project.config.artifact_root / "proxies" / f"{asset.asset_id}.time-map.json"
        assert time_map.is_file()
    sheet_manifest = json.loads(
        (project.config.artifact_root / "contact-sheets" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(sheet_manifest["sheets"]) == 1
    sheet_path = Path(sheet_manifest["sheets"][0]["path"])
    assert sheet_path.is_file()
    assert sheet_path.suffix == ".jpg"
    assert sheet_path.read_bytes().startswith(b"\xff\xd8")
    assert len(sheet_manifest["sheets"][0]["cells"]) == 2

    repair_id = indexed.index.assets[0].asset_id
    repair_thumbnail = project.config.artifact_root / "proxies" / f"{repair_id}.jpg"
    repair_thumbnail.write_bytes(b"tampered")
    damaged_status = read_project_status(
        project.config, project_root=project.config.artifact_root.parent
    )
    assert damaged_status.stages["proxy"]["validity"] == "partial"
    assert damaged_status.stages["proxy"]["reasonCodes"] == ["proxy_evidence_invalid"]
    repaired = build_proxies(
        ProxyRequest(
            config=project.config,
            index=indexed.index,
            asset_ids=[repair_id],
            resume=True,
        ),
        runner=SubprocessRunner(),
    )
    assert repaired.built == [repair_id]

    changed_id = next(
        item.asset_id for item in indexed.index.assets if item.canonical_path == str(first_source)
    )
    unchanged_id = next(
        item.asset_id for item in indexed.index.assets if item.canonical_path == str(second_source)
    )
    previous_manifest = project.config.artifact_root / "proxies" / f"{changed_id}.manifest.json"
    previous_manifest_bytes = previous_manifest.read_bytes()
    make_video(first_source, color="yellow", frequency=880)
    with pytest.raises(PreflightError) as captured:
        build_proxies(
            ProxyRequest(
                config=project.config,
                index=indexed.index,
                asset_ids=[changed_id],
                resume=True,
            ),
            runner=SubprocessRunner(),
        )
    assert captured.value.code == "source_changed_since_ingest"
    assert previous_manifest.read_bytes() == previous_manifest_bytes

    reindexed = ingest_media(IngestRequest(config=project.config), runner=SubprocessRunner())
    rebuilt = build_proxies(
        ProxyRequest(config=project.config, index=reindexed.index, resume=True),
        runner=SubprocessRunner(),
    )

    assert rebuilt.built == [changed_id]
    assert rebuilt.cached == [unchanged_id]


def test_cli_ingest_and_proxy_emit_single_json_documents(tmp_path: Path) -> None:
    require_media_tools()
    media = tmp_path / "素材 with spaces"
    make_video(media / "talking head.mp4")
    project = _project(tmp_path, media)

    ingest_result = runner.invoke(
        app,
        ["ingest", "--project", str(project.config.artifact_root.parent), "--json"],
    )

    assert ingest_result.exit_code == ExitCode.SUCCESS, ingest_result.output
    ingest_payload = json.loads(ingest_result.stdout)
    assert ingest_payload["command"] == "ingest"
    assert ingest_payload["data"]["assetCount"] == 1
    assert len(ingest_result.stdout.strip().splitlines()) == 1
    assert "Scanning source-media roots" in ingest_result.stderr

    dry_run = runner.invoke(
        app,
        [
            "--dry-run",
            "proxy",
            "build",
            "--project",
            str(project.config.artifact_root.parent),
            "--json",
        ],
    )
    assert dry_run.exit_code == ExitCode.SUCCESS, dry_run.output
    dry_payload = json.loads(dry_run.stdout)
    assert "runId" not in dry_payload
    assert not list((project.config.artifact_root / "logs").glob("*.json"))

    proxy_result = runner.invoke(
        app,
        [
            "proxy",
            "build",
            "--project",
            str(project.config.artifact_root.parent),
            "--resume",
            "--json",
        ],
    )

    assert proxy_result.exit_code == ExitCode.SUCCESS, proxy_result.output
    proxy_payload = json.loads(proxy_result.stdout)
    assert proxy_payload["command"] == "proxy build"
    assert isinstance(proxy_payload["runId"], str)
    assert len(proxy_payload["data"]["built"]) == 1
    assert any(item["kind"] == "operation-run" for item in proxy_payload["artifacts"])
    assert len(proxy_result.stdout.strip().splitlines()) == 1
    assert "Preparing 1 indexed asset" in proxy_result.stderr


def test_ingest_skips_symlink_whose_target_is_outside_media_root(tmp_path: Path) -> None:
    require_media_tools()
    media = tmp_path / "media"
    make_video(media / "inside.mp4")
    outside = tmp_path / "outside.mp4"
    make_video(outside, color="purple")
    (media / "outside-link.mp4").symlink_to(outside)
    project = _project(tmp_path, media)

    result = ingest_media(IngestRequest(config=project.config), runner=SubprocessRunner())

    assert [asset.relative_path for asset in result.index.assets] == ["inside.mp4"]
    assert [warning.code for warning in result.index.warnings] == ["source_symlink_outside_root"]


def test_ingest_rejects_symlinked_artifact_directory(tmp_path: Path) -> None:
    require_media_tools()
    media = tmp_path / "media"
    make_video(media / "inside.mp4")
    project = _project(tmp_path, media)
    index_root = project.config.artifact_root / "index"
    index_root.rmdir()
    index_root.symlink_to(media, target_is_directory=True)

    with pytest.raises(PathSafetyError) as captured:
        ingest_media(IngestRequest(config=project.config), runner=SubprocessRunner())

    assert captured.value.code == "artifact_path_unsafe"
    assert not (media / "media-index.json").exists()


def test_cli_broken_media_returns_preflight_json(tmp_path: Path) -> None:
    require_media_tools()
    media = tmp_path / "media"
    media.mkdir()
    (media / "broken.mp4").write_text("not a media file", encoding="utf-8")
    project = _project(tmp_path, media)

    result = runner.invoke(
        app,
        ["ingest", "--project", str(project.config.artifact_root.parent), "--json"],
    )

    assert result.exit_code == ExitCode.PREFLIGHT_FAILED
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "media_probe_failed"
    assert not (project.config.artifact_root / "index" / "media-index.json").exists()


def test_proxy_resume_keeps_completed_asset_after_interruption(tmp_path: Path) -> None:
    require_media_tools()
    media = tmp_path / "media"
    make_video(media / "first.mp4", color="orange")
    make_video(media / "second.mp4", color="white")
    project = _project(tmp_path, media)
    indexed = ingest_media(IngestRequest(config=project.config), runner=SubprocessRunner())
    asset_ids = [asset.asset_id for asset in indexed.index.assets]

    with pytest.raises(KeyboardInterrupt):
        build_proxies(
            ProxyRequest(config=project.config, index=indexed.index, resume=True),
            runner=InterruptAfterFirstAssetRunner(),
        )

    interrupted_runs = list((project.config.artifact_root / "logs").glob("proxy_*.json"))
    assert len(interrupted_runs) == 1
    interrupted_manifest = json.loads(interrupted_runs[0].read_text(encoding="utf-8"))
    assert interrupted_manifest["state"] == "interrupted"
    assert interrupted_manifest["progress"]["completed_items"] == [asset_ids[0]]
    assert any(
        Path(item["path"]).name == f"{asset_ids[0]}.manifest.json"
        for item in interrupted_manifest["artifacts"]
    )
    first_manifest = project.config.artifact_root / "proxies" / f"{asset_ids[0]}.manifest.json"
    second_manifest = project.config.artifact_root / "proxies" / f"{asset_ids[1]}.manifest.json"
    assert first_manifest.is_file()
    assert not second_manifest.exists()
    assert not list(project.config.artifact_root.rglob("*.tmp.*"))

    resumed = build_proxies(
        ProxyRequest(config=project.config, index=indexed.index, resume=True),
        runner=SubprocessRunner(),
    )

    assert resumed.cached == [asset_ids[0]]
    assert resumed.built == [asset_ids[1]]
    assert resumed.run_id is not None
    assert resumed.run_manifest_path is not None
    resumed_manifest = json.loads(resumed.run_manifest_path.read_text(encoding="utf-8"))
    assert resumed_manifest["state"] == "succeeded"
    assert resumed_manifest["progress"]["cached_items"] == [asset_ids[0]]
    assert resumed_manifest["progress"]["completed_items"] == [asset_ids[1]]
    status = read_project_status(project.config, project_root=project.config.artifact_root.parent)
    assert status.stages["proxy"]["latestRun"] == {
        "runId": resumed.run_id,
        "state": "succeeded",
        "expectedCount": 2,
        "completedCount": 1,
        "cachedCount": 1,
        "skippedCount": 0,
        "errorCode": None,
        "startedAt": resumed_manifest["started_at"],
        "completedAt": resumed_manifest["completed_at"],
        "manifestPath": str(resumed.run_manifest_path),
    }
