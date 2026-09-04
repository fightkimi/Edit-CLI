from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from interview_edit.config.loader import (
    config_path_for,
    load_project_config,
    serialize_project_config,
)
from interview_edit.config.models import PrivacyMode, ProjectConfig
from interview_edit.errors import PathSafetyError, UsageError
from interview_edit.project.layout import (
    ARTIFACT_DIRECTORIES,
    PROJECT_DIRECTORIES,
    atomic_write_text,
    canonical,
    is_within,
    validate_artifact_boundary,
    validate_media_roots,
)


@dataclass(frozen=True)
class InitRequest:
    project: Path
    name: str
    media_roots: list[Path]
    privacy: str
    artifact_root: Path | None = None
    force: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class InitResult:
    config: ProjectConfig
    config_path: Path
    state_path: Path
    created_directories: tuple[Path, ...]
    dry_run: bool


def _project_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
    slug = slug[:32].rstrip("-")
    return f"prj_{slug}_{uuid.uuid4().hex[:8]}"


def _privacy_mode(value: str) -> PrivacyMode:
    try:
        return PrivacyMode(value)
    except ValueError as exc:
        raise UsageError(
            "privacy_required",
            "Privacy must be explicitly set to 'strict' or 'assisted'.",
            details={"value": value},
        ) from exc


def _existing_project_id(config_path: Path, force: bool) -> str | None:
    if not config_path.exists():
        return None
    if not force:
        raise UsageError(
            "project_exists",
            f"Project configuration already exists: {config_path}",
            details={"path": str(config_path)},
        )
    return load_project_config(config_path).project_id


def initialize_project(request: InitRequest) -> InitResult:
    project = canonical(request.project)
    if project.exists() and not project.is_dir():
        raise PathSafetyError(
            "project_not_directory",
            f"Project path is not a directory: {project}",
            details={"path": str(project)},
        )
    name = request.name.strip()
    if not name:
        raise UsageError("name_required", "Project name must not be empty.")

    media_roots = validate_media_roots(request.media_roots)
    for media_root in media_roots:
        if is_within(project, media_root):
            raise PathSafetyError(
                "project_media_overlap",
                "The editing project may not be created inside a source-media root.",
                details={"projectRoot": str(project), "mediaRoot": str(media_root)},
            )
    requested_artifact = request.artifact_root or Path("artifacts")
    if not requested_artifact.is_absolute():
        requested_artifact = project / requested_artifact
    artifact_root = validate_artifact_boundary(requested_artifact, media_roots)
    privacy = _privacy_mode(request.privacy)
    config_path = config_path_for(project)
    existing_id = _existing_project_id(config_path, request.force)

    config = ProjectConfig(
        project_id=existing_id or _project_id(name),
        name=name,
        media_roots=media_roots,
        artifact_root=artifact_root,
        privacy_mode=privacy,
    )
    state_path = project / ".interview-edit" / "state.json"
    directories = tuple(
        [project / relative for relative in PROJECT_DIRECTORIES]
        + [artifact_root / relative for relative in ARTIFACT_DIRECTORIES]
    )

    if not request.dry_run:
        try:
            project.mkdir(parents=True, exist_ok=True)
            for directory in directories:
                directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PathSafetyError(
                "project_create_failed",
                f"Could not create project directories under: {project}",
                details={"path": str(project), "reason": str(exc)},
            ) from exc
        atomic_write_text(config_path, serialize_project_config(config))
        if not state_path.exists():
            state = {"schemaVersion": "1", "projectId": config.project_id, "runs": {}}
            atomic_write_text(
                state_path,
                json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )

    return InitResult(
        config=config,
        config_path=config_path,
        state_path=state_path,
        created_directories=directories,
        dry_run=request.dry_run,
    )
