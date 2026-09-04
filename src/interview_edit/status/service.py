from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from interview_edit.config.models import ProjectConfig
from interview_edit.project.layout import artifact_path

ARTIFACT_STAGES: dict[str, tuple[str, ...]] = {
    "ingest": ("index",),
    "proxy": ("proxies", "audio", "contact-sheets"),
    "transcribe": ("transcripts",),
    "sync": ("sync",),
    "render": ("renders",),
    "qc": ("qc",),
    "version": ("versions",),
}


@dataclass(frozen=True)
class ProjectStatus:
    project_id: str
    name: str
    privacy_mode: str
    artifact_root: Path
    stages: dict[str, dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "projectId": self.project_id,
            "name": self.name,
            "privacyMode": self.privacy_mode,
            "artifactRoot": str(self.artifact_root),
            "stages": self.stages,
        }


def _file_count(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for candidate in directory.rglob("*") if candidate.is_file())


def _published_render_count(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    count = 0
    for candidate in directory.rglob("*.mp4"):
        relative = candidate.relative_to(directory)
        if relative.parts and relative.parts[0] not in {"cache", "runs"} and candidate.is_file():
            count += 1
    return count


def read_project_status(config: ProjectConfig) -> ProjectStatus:
    stages: dict[str, dict[str, Any]] = {}
    for stage, directories in ARTIFACT_STAGES.items():
        paths = [artifact_path(config.artifact_root, directory) for directory in directories]
        count = (
            _published_render_count(paths[0])
            if stage == "render"
            else sum(_file_count(path) for path in paths)
        )
        stages[stage] = {
            "state": "present" if count else "missing",
            "fileCount": count,
            "paths": [str(path) for path in paths],
        }
    return ProjectStatus(
        project_id=config.project_id,
        name=config.name,
        privacy_mode=config.privacy_mode.value,
        artifact_root=config.artifact_root,
        stages=stages,
    )
