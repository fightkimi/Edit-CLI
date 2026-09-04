from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from interview_edit.adapters.process import SubprocessRunner
from interview_edit.adapters.transcription import (
    BackendSegment,
    BackendTranscript,
    BackendWord,
)
from interview_edit.ingest.service import IngestRequest, ingest_media
from interview_edit.project.service import InitRequest, initialize_project
from interview_edit.proxy.service import ProxyRequest, build_proxies
from interview_edit.transcribe.service import TranscribeRequest, transcribe_assets
from tests.fixtures.media_factory import make_video, require_media_tools


class MixedLanguageFixtureTranscriber:
    backend = "fixture"
    backend_version = "beta-mixed-language-v1"
    requested_model = "fixture"
    resolved_model = "fixture:mixed-language"
    device = "cpu"

    def transcribe(self, audio_path: Path, *, language: str) -> BackendTranscript:
        del audio_path, language
        words = (
            BackendWord(0.0, 0.3, "你好", 1.0),
            BackendWord(0.3, 0.6, " creator", 1.0),
        )
        return BackendTranscript(
            language="zh",
            segments=(BackendSegment(0.0, 0.6, "你好 creator", words),),
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_beta_fixture_has_three_cameras_two_takes_and_mixed_language(
    tmp_path: Path,
) -> None:
    require_media_tools()
    media = tmp_path / "原始 素材"
    colors = ("blue", "red", "green", "yellow", "purple", "orange")
    frequencies = (410, 440, 470, 510, 540, 570)
    mapped_files: list[tuple[Path, str, str]] = []
    for take_number, take_id in enumerate(("take-01", "take-02"), start=1):
        for camera_number, camera_id in enumerate(("wide", "close", "side")):
            filename = media / f"第 {take_number} 条" / f"{camera_id} 机位.mp4"
            fixture_index = (take_number - 1) * 3 + camera_number
            make_video(
                filename,
                color=colors[fixture_index],
                frequency=frequencies[fixture_index],
                duration_seconds=0.8,
            )
            mapped_files.append((filename, camera_id, take_id))
    broll = media / "补充 素材" / "可重复 B-roll.mp4"
    make_video(broll, color="white", frequency=610, duration_seconds=0.8)

    before = {path: _sha256(path) for path, _, _ in mapped_files}
    before[broll] = _sha256(broll)
    project = initialize_project(
        InitRequest(
            project=tmp_path / "Beta 项目",
            name="M6 synthetic Beta",
            media_roots=[media],
            privacy="assisted",
        )
    )
    camera_map = tmp_path / "camera-map.yaml"
    camera_map.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "rules": [
                    {
                        "glob": str(path.relative_to(media)),
                        "camera_id": camera_id,
                        "take_id": take_id,
                    }
                    for path, camera_id, take_id in mapped_files
                ],
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

    mapped = [asset for asset in first.index.assets if asset.camera_id is not None]
    assert len(first.index.assets) == 7
    assert {asset.camera_id for asset in mapped} == {"wide", "close", "side"}
    assert {asset.take_id for asset in mapped} == {"take-01", "take-02"}
    assert len(second.index.changes.unchanged) == 7
    assert second.index.changes.added == []

    speech_asset = next(
        asset
        for asset in first.index.assets
        if asset.camera_id == "wide" and asset.take_id == "take-01"
    )
    build_proxies(
        ProxyRequest(
            config=project.config,
            index=first.index,
            asset_ids=[speech_asset.asset_id],
            resume=True,
        ),
        runner=SubprocessRunner(),
    )
    transcript = transcribe_assets(
        TranscribeRequest(
            config=project.config,
            project_root=project.config.artifact_root.parent,
            index=first.index,
            asset_ids=[speech_asset.asset_id],
            resume=True,
        ),
        transcriber=MixedLanguageFixtureTranscriber(),
        runner=SubprocessRunner(),
    )

    corrected = (
        project.config.artifact_root / "transcripts" / transcript.built[0] / "corrected.jsonl"
    ).read_text(encoding="utf-8")
    assert "你好 creator" in corrected
    assert all(_sha256(path) == digest for path, digest in before.items())
