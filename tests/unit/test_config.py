from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from interview_edit.config.loader import load_project_config
from interview_edit.config.models import PrivacyMode, SafetyConfig, TranscriptionConfig
from interview_edit.models.cutlist import TimelineSpec


def _write_config(path: Path, media_root: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "project_id": "prj_config_test",
                "name": "Config test",
                "media_roots": [str(media_root)],
                "artifact_root": "artifacts",
                "privacy_mode": "strict",
                "language": "zh",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_environment_overrides_project_and_cli_has_highest_priority(tmp_path: Path) -> None:
    media_root = tmp_path / "素材"
    media_root.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    _write_config(project / "interview-edit.yaml", media_root)
    user_config = tmp_path / "user-config.yaml"
    user_config.write_text(
        yaml.safe_dump(
            {
                "language": "fr",
                "transcription": {"backend": "faster-whisper", "model": "base"},
            }
        ),
        encoding="utf-8",
    )

    config = load_project_config(
        project,
        environ={
            "INTERVIEW_EDIT_USER_CONFIG": str(user_config),
            "INTERVIEW_EDIT_PRIVACY_MODE": "assisted",
            "INTERVIEW_EDIT_TRANSCRIPTION__BACKEND": "mlx-whisper",
        },
        cli_overrides={"language": "en"},
    )

    assert config.privacy_mode == PrivacyMode.ASSISTED
    assert config.language == "en"
    assert config.transcription.backend.value == "mlx-whisper"
    assert config.transcription.model == "base"
    assert config.artifact_root == (project / "artifacts").resolve()


def test_public_config_rejects_mock_transcription_backend() -> None:
    with pytest.raises(ValidationError):
        TranscriptionConfig(backend="mock")


@pytest.mark.parametrize(
    "values",
    [
        {"source_media_read_only": False},
        {"allow_network": True},
        {"allow_source_symlinks_outside_root": True},
    ],
)
def test_v1_safety_invariants_cannot_be_disabled(values: dict[str, bool]) -> None:
    with pytest.raises(ValidationError):
        SafetyConfig(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["25", "0/1", "25/0", "not-a-rate"])
def test_timeline_requires_positive_rational_frame_rate(value: str) -> None:
    with pytest.raises(ValidationError):
        TimelineSpec(frame_rate=value)


def test_timeline_accepts_ntsc_rational() -> None:
    assert TimelineSpec(frame_rate="30000/1001").frame_rate == "30000/1001"
