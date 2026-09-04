from __future__ import annotations

import os
import tempfile
from pathlib import Path

from interview_edit.errors import PathSafetyError

PROJECT_DIRECTORIES = (
    "cutlists/revisions",
    "dictionaries",
    ".interview-edit/cache",
)

ARTIFACT_DIRECTORIES = (
    "index",
    "proxies",
    "audio",
    "transcripts",
    "contact-sheets",
    "sync",
    "renders",
    "qc",
    "versions",
    "logs",
)


def canonical(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(candidate: Path, root: Path) -> bool:
    candidate_resolved = canonical(candidate)
    root_resolved = canonical(root)
    return candidate_resolved == root_resolved or root_resolved in candidate_resolved.parents


def validate_media_roots(media_roots: list[Path]) -> list[Path]:
    if not media_roots:
        raise PathSafetyError("media_root_required", "At least one media root is required.")
    resolved: list[Path] = []
    for media_root in media_roots:
        root = canonical(media_root)
        if not root.exists():
            raise PathSafetyError(
                "media_root_missing",
                f"Media root does not exist: {root}",
                details={"path": str(root)},
            )
        if not root.is_dir():
            raise PathSafetyError(
                "media_root_not_directory",
                f"Media root is not a directory: {root}",
                details={"path": str(root)},
            )
        if not os.access(root, os.R_OK):
            raise PathSafetyError(
                "media_root_not_readable",
                f"Media root is not readable: {root}",
                details={"path": str(root)},
            )
        if root not in resolved:
            resolved.append(root)
    return resolved


def validate_artifact_boundary(artifact_root: Path, media_roots: list[Path]) -> Path:
    artifact = canonical(artifact_root)
    for media_root in media_roots:
        if is_within(artifact, media_root) or is_within(media_root, artifact):
            raise PathSafetyError(
                "artifact_media_overlap",
                "Artifact root and media roots must not overlap.",
                details={"artifactRoot": str(artifact), "mediaRoot": str(media_root)},
            )
    return artifact


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise PathSafetyError(
            "atomic_write_failed",
            f"Could not write file atomically: {path}",
            details={"path": str(path), "reason": str(exc)},
        ) from exc
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
