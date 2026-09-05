from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from interview_edit.config.models import ProjectConfig
from interview_edit.errors import ProcessingError
from interview_edit.models.operation import OperationRunManifest
from interview_edit.operation.service import start_operation


def _config(tmp_path: Path) -> ProjectConfig:
    media = tmp_path / "media"
    media.mkdir()
    return ProjectConfig(
        project_id="prj_operation_test",
        name="Operation test",
        media_roots=[media],
        artifact_root=tmp_path / "artifacts",
        privacy_mode="strict",
    )


def test_operation_run_records_progress_and_only_small_control_artifacts(tmp_path: Path) -> None:
    config = _config(tmp_path)
    control = config.artifact_root / "proxies" / "asset.manifest.json"
    content = config.artifact_root / "transcripts" / "asset" / "corrected.jsonl"
    control.parent.mkdir(parents=True)
    content.parent.mkdir(parents=True)
    control.write_text('{"ok":true}', encoding="utf-8")
    content.write_text('{"text":"PRIVATE TRANSCRIPT"}', encoding="utf-8")
    recorder = start_operation(
        config,
        command="proxy_build",
        invocation={"assetIds": ["asset_0123456789abcdef01234567"], "resume": True},
        expected_items=["asset_0123456789abcdef01234567"],
        input_fingerprints={"asset_0123456789abcdef01234567": "quick-sha256-v1:test"},
    )
    running = OperationRunManifest.model_validate_json(recorder.path.read_text(encoding="utf-8"))
    assert running.state == "running"

    recorder.checkpoint(
        completed_items=["asset_0123456789abcdef01234567"],
        metrics={"completedChunks": 1},
        tools={"ffmpeg": "ffmpeg test"},
    )
    recorder.finish(artifacts=[control, content])

    completed_text = recorder.path.read_text(encoding="utf-8")
    completed = OperationRunManifest.model_validate_json(completed_text)
    assert completed.state == "succeeded"
    assert completed.progress.completed_items == ["asset_0123456789abcdef01234567"]
    assert completed.progress.metrics == {"completedChunks": 1}
    assert [Path(item.path).name for item in completed.artifacts] == ["asset.manifest.json"]
    assert completed.artifacts[0].sha256
    assert "PRIVATE TRANSCRIPT" not in completed_text


def test_operation_run_failure_keeps_only_stable_error_identity(tmp_path: Path) -> None:
    recorder = start_operation(
        _config(tmp_path),
        command="transcribe",
        invocation={"modelOverride": True},
        expected_items=["asset_0123456789abcdef01234567"],
    )

    recorder.fail(
        ProcessingError(
            "transcription_failed",
            "Recognition failed for PRIVATE TRANSCRIPT.",
            details={"stderr": "PRIVATE TRANSCRIPT", "path": "/private/source.wav"},
        )
    )

    text = recorder.path.read_text(encoding="utf-8")
    failed = OperationRunManifest.model_validate_json(text)
    assert failed.state == "failed"
    assert failed.error is not None
    assert failed.error.code == "transcription_failed"
    assert failed.error.category == "ProcessingError"
    assert "PRIVATE TRANSCRIPT" not in text
    assert "/private/source.wav" not in text


def test_disabled_operation_run_writes_nothing(tmp_path: Path) -> None:
    config = _config(tmp_path)

    recorder = start_operation(
        config,
        command="sync",
        invocation={},
        expected_items=[],
        enabled=False,
    )

    assert recorder is None
    assert not (config.artifact_root / "logs").exists()

    with pytest.raises(ValidationError):
        OperationRunManifest(
            run_id="proxy_20260904T000000Z_invalid",
            command="proxy_build",
            state="succeeded",
            project_id=config.project_id,
            invocation={},
            config_sha256="0" * 64,
            environment={
                "package_version": "0.6.0",
                "python": "3.11",
                "platform": "test",
            },
            progress={"expected_items": ["asset_a"], "completed_items": ["asset_other"]},
            started_at="2026-09-04T00:00:00Z",
            completed_at="2026-09-04T00:00:01Z",
        )
