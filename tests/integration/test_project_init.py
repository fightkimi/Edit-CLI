from __future__ import annotations

from pathlib import Path

import pytest

from interview_edit.config.loader import load_project_config
from interview_edit.errors import PathSafetyError, UsageError
from interview_edit.exit_codes import ExitCode
from interview_edit.project.service import InitRequest, initialize_project
from interview_edit.status.service import read_project_status


def _request(project: Path, media: Path, **overrides: object) -> InitRequest:
    values: dict[str, object] = {
        "project": project,
        "name": "中文 Creator Project",
        "media_roots": [media],
        "privacy": "assisted",
    }
    values.update(overrides)
    return InitRequest(**values)  # type: ignore[arg-type]


def test_init_creates_project_without_changing_source_media(tmp_path: Path) -> None:
    media = tmp_path / "原始 素材"
    media.mkdir()
    source = media / "镜头 01.txt"
    source.write_bytes(b"read-only evidence")
    before = source.read_bytes()
    project = tmp_path / "编辑项目"

    result = initialize_project(_request(project, media))

    assert result.config_path.is_file()
    assert result.state_path.is_file()
    assert (project / "cutlists" / "revisions").is_dir()
    assert (result.config.artifact_root / "renders").is_dir()
    assert source.read_bytes() == before
    loaded = load_project_config(project, environ={"INTERVIEW_EDIT_USER_CONFIG": ""})
    assert loaded.project_id == result.config.project_id
    assert loaded.media_roots == [media.resolve()]


def test_init_refuses_to_overwrite_existing_config(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    project = tmp_path / "project"
    initialize_project(_request(project, media))

    with pytest.raises(UsageError) as captured:
        initialize_project(_request(project, media))

    assert captured.value.exit_code == ExitCode.USAGE_ERROR
    assert captured.value.code == "project_exists"


def test_force_preserves_existing_project_identity(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    project = tmp_path / "project"
    first = initialize_project(_request(project, media))

    second = initialize_project(_request(project, media, name="Renamed", force=True))

    assert second.config.project_id == first.config.project_id
    assert second.config.name == "Renamed"


def test_init_rejects_artifact_and_media_overlap(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()

    with pytest.raises(PathSafetyError) as captured:
        initialize_project(_request(tmp_path / "project", media, artifact_root=media / "generated"))

    assert captured.value.exit_code == ExitCode.PATH_ERROR
    assert captured.value.code == "artifact_media_overlap"


def test_init_rejects_project_metadata_inside_media_root(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()

    with pytest.raises(PathSafetyError) as captured:
        initialize_project(
            _request(media, media, artifact_root=tmp_path / "external-artifacts")
        )

    assert captured.value.code == "project_media_overlap"
    assert not (media / "interview-edit.yaml").exists()


def test_dry_run_does_not_create_project(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    project = tmp_path / "project"

    result = initialize_project(_request(project, media, dry_run=True))

    assert result.dry_run
    assert not project.exists()


def test_status_uses_files_not_empty_directories_as_evidence(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    result = initialize_project(_request(tmp_path / "project", media))

    initial = read_project_status(result.config)
    assert initial.stages["ingest"]["state"] == "missing"

    index = result.config.artifact_root / "index" / "media-index.json"
    index.write_text("{}", encoding="utf-8")
    updated = read_project_status(result.config)
    assert updated.stages["ingest"] == {
        "state": "present",
        "fileCount": 1,
        "paths": [str(result.config.artifact_root / "index")],
    }
