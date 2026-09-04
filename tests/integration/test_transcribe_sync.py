from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from interview_edit.adapters.process import SubprocessRunner
from interview_edit.adapters.transcription import (
    BackendSegment,
    BackendTranscript,
    BackendWord,
)
from interview_edit.cli.app import app
from interview_edit.config.models import SyncConfig, TranscriptionConfig
from interview_edit.exit_codes import ExitCode
from interview_edit.ingest.service import IngestRequest, ingest_media
from interview_edit.project.service import InitRequest, initialize_project
from interview_edit.proxy.service import ProxyRequest, build_proxies
from interview_edit.sync.service import SyncRequest, sync_take
from interview_edit.transcribe import service as transcribe_service
from interview_edit.transcribe.service import TranscribeRequest, transcribe_assets
from tests.fixtures.media_factory import make_noise_wav, make_video_from_audio, require_media_tools
from tests.fixtures.transcription import MockTranscriber

runner = CliRunner()


class InterruptSecondChunkTranscriber:
    backend = "mock"
    backend_version = "resume-test"
    requested_model = "mock"
    resolved_model = "mock:resume"
    device = "cpu"

    def __init__(self, *, interrupt: bool) -> None:
        self.calls = 0
        self.interrupt = interrupt

    def transcribe(self, audio_path: Path, *, language: str) -> BackendTranscript:
        self.calls += 1
        if self.interrupt and self.calls == 2:
            raise KeyboardInterrupt
        word = BackendWord(0.0, 0.5, f"chunk {self.calls}", 1.0)
        segment = BackendSegment(0.0, 0.5, f"chunk {self.calls}", (word,))
        return BackendTranscript(language=language, segments=(segment,))


def _project(tmp_path: Path, media_root: Path):
    return initialize_project(
        InitRequest(
            project=tmp_path / "project",
            name="M3 test",
            media_roots=[media_root],
            privacy="assisted",
        )
    )


def test_transcription_keeps_raw_separate_and_rebuilds_only_corrections(tmp_path: Path) -> None:
    require_media_tools()
    media = tmp_path / "media"
    make_noise_wav(media / "voice.wav", duration_seconds=3)
    project = _project(tmp_path, media)
    indexed = ingest_media(IngestRequest(config=project.config), runner=SubprocessRunner())
    build_proxies(
        ProxyRequest(config=project.config, index=indexed.index), runner=SubprocessRunner()
    )
    request = TranscribeRequest(
        config=project.config,
        project_root=project.config.artifact_root.parent,
        index=indexed.index,
        resume=True,
    )

    first = transcribe_assets(request, transcriber=MockTranscriber(), runner=SubprocessRunner())
    transcript_root = project.config.artifact_root / "transcripts" / first.built[0]
    raw_before = (transcript_root / "raw.jsonl").read_bytes()
    raw_mtime_before = (transcript_root / "raw.jsonl").stat().st_mtime_ns
    (project.config.artifact_root.parent / "dictionaries" / "corrections.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "rules": [
                    {
                        "id": "mock-label",
                        "find": "mock transcript",
                        "replace": "校正文本",
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    second = transcribe_assets(request, transcriber=MockTranscriber(), runner=SubprocessRunner())

    assert first.built
    assert second.corrected == first.built
    assert second.built == []
    assert (transcript_root / "raw.jsonl").read_bytes() == raw_before
    assert (transcript_root / "raw.jsonl").stat().st_mtime_ns == raw_mtime_before
    corrected = (transcript_root / "corrected.jsonl").read_text(encoding="utf-8")
    assert "校正文本" in corrected
    assert "mock-label" in corrected


def test_transcription_resume_reuses_completed_chunk(tmp_path: Path) -> None:
    require_media_tools()
    media = tmp_path / "media"
    make_noise_wav(media / "long.wav", duration_seconds=61)
    project = _project(tmp_path, media)
    config = project.config.model_copy(
        update={
            "transcription": TranscriptionConfig(model="mock", chunk_duration_seconds=30)
        }
    )
    indexed = ingest_media(IngestRequest(config=config), runner=SubprocessRunner())
    build_proxies(ProxyRequest(config=config, index=indexed.index), runner=SubprocessRunner())
    request = TranscribeRequest(
        config=config,
        project_root=config.artifact_root.parent,
        index=indexed.index,
        resume=True,
    )
    interrupted = InterruptSecondChunkTranscriber(interrupt=True)

    with pytest.raises(KeyboardInterrupt):
        transcribe_assets(request, transcriber=interrupted, runner=SubprocessRunner())

    resumed = InterruptSecondChunkTranscriber(interrupt=False)
    result = transcribe_assets(request, transcriber=resumed, runner=SubprocessRunner())

    assert result.resumed_chunks == 1
    assert resumed.calls == 2
    assert result.built == [indexed.index.assets[0].asset_id]


def test_sync_recovers_offset_and_writes_visual_evidence(tmp_path: Path) -> None:
    require_media_tools()
    media = tmp_path / "media"
    base_audio = tmp_path / "base.wav"
    make_noise_wav(base_audio, duration_seconds=8)
    make_video_from_audio(media / "wide.mp4", base_audio, delay_ms=0)
    make_video_from_audio(media / "close.mp4", base_audio, delay_ms=250)
    project = _project(tmp_path, media)
    camera_map = tmp_path / "camera-map.yaml"
    camera_map.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "rules": [
                    {"glob": "wide.mp4", "camera_id": "wide", "take_id": "take-01"},
                    {"glob": "close.mp4", "camera_id": "close", "take_id": "take-01"},
                ],
            }
        ),
        encoding="utf-8",
    )
    config = project.config.model_copy(
        update={
            "sync": SyncConfig(
                window_count=3,
                minimum_confidence=0.5,
                window_duration_seconds=2,
                max_offset_seconds=1,
            )
        }
    )
    indexed = ingest_media(
        IngestRequest(config=config, camera_map=camera_map), runner=SubprocessRunner()
    )
    build_proxies(ProxyRequest(config=config, index=indexed.index), runner=SubprocessRunner())

    result = sync_take(
        SyncRequest(
            config=config,
            index=indexed.index,
            take_id="take-01",
            reference_camera_id="wide",
            visual_check=True,
        ),
        runner=SubprocessRunner(),
    )

    assert result.uncertain_cameras == []
    assert result.report is not None
    close = next(camera for camera in result.report.cameras if camera.camera_id == "close")
    assert close.offset_us == pytest.approx(250_000, abs=30_000)
    assert close.confidence >= 0.5
    assert len(close.windows) == 3
    assert len(result.report.evidence) == 3
    assert all(
        Path(item.path).read_bytes().startswith(b"\xff\xd8") for item in result.report.evidence
    )
    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["convention"] == "camera_time = reference_time + offset"


def test_cli_transcribe_emits_one_json_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    require_media_tools()
    media = tmp_path / "media"
    make_noise_wav(media / "voice.wav", duration_seconds=3)
    project = _project(tmp_path, media)
    indexed = ingest_media(IngestRequest(config=project.config), runner=SubprocessRunner())
    build_proxies(
        ProxyRequest(config=project.config, index=indexed.index), runner=SubprocessRunner()
    )
    monkeypatch.setattr(
        transcribe_service,
        "create_transcriber",
        lambda *_args, **_kwargs: MockTranscriber(),
    )

    result = runner.invoke(
        app,
        [
            "transcribe",
            "--project",
            str(project.config.artifact_root.parent),
            "--resume",
            "--json",
        ],
    )

    assert result.exit_code == ExitCode.SUCCESS, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "transcribe"
    assert payload["data"]["built"] == [indexed.index.assets[0].asset_id]
    assert len(result.stdout.strip().splitlines()) == 1


def test_cli_uncertain_sync_is_nonzero_but_manual_override_succeeds(tmp_path: Path) -> None:
    require_media_tools()
    media = tmp_path / "media"
    make_noise_wav(media / "wide.wav", duration_seconds=5, seed=1)
    make_noise_wav(media / "close.wav", duration_seconds=5, seed=2)
    project = _project(tmp_path, media)
    camera_map = tmp_path / "camera-map.yaml"
    camera_map.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "rules": [
                    {"glob": "wide.wav", "camera_id": "wide", "take_id": "take-02"},
                    {"glob": "close.wav", "camera_id": "close", "take_id": "take-02"},
                ],
            }
        ),
        encoding="utf-8",
    )
    indexed = ingest_media(
        IngestRequest(config=project.config, camera_map=camera_map), runner=SubprocessRunner()
    )
    build_proxies(
        ProxyRequest(config=project.config, index=indexed.index), runner=SubprocessRunner()
    )
    base_args = [
        "sync",
        "--project",
        str(project.config.artifact_root.parent),
        "--take",
        "take-02",
        "--reference-camera",
        "wide",
        "--json",
    ]

    uncertain = runner.invoke(app, base_args)

    assert uncertain.exit_code == ExitCode.PREFLIGHT_FAILED, uncertain.output
    uncertain_payload = json.loads(uncertain.stdout)
    assert uncertain_payload["ok"] is False
    assert uncertain_payload["error"]["code"] == "sync_confidence_insufficient"
    assert Path(uncertain_payload["data"]["reportPath"]).is_file()

    manual = runner.invoke(app, [*base_args[:-1], "--manual-offset", "close=125ms", "--json"])

    assert manual.exit_code == ExitCode.SUCCESS, manual.output
    manual_payload = json.loads(manual.stdout)
    close = next(
        camera
        for camera in manual_payload["data"]["report"]["cameras"]
        if camera["camera_id"] == "close"
    )
    assert close["status"] == "manual"
    assert close["offset_us"] == 125_000
    assert close["provenance"] == "manual_override"
