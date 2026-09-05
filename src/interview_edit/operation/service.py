from __future__ import annotations

import hashlib
import json
import platform
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from interview_edit import __version__
from interview_edit.adapters.filesystem import sha256_file
from interview_edit.config.models import ProjectConfig
from interview_edit.errors import InterviewEditError
from interview_edit.models.operation import (
    OperationArtifact,
    OperationCommand,
    OperationEnvironment,
    OperationError,
    OperationProgress,
    OperationRunManifest,
    OperationState,
)
from interview_edit.project.layout import artifact_path, atomic_write_text, canonical, is_within


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _run_id(command: OperationCommand) -> str:
    prefix = "proxy" if command == "proxy_build" else command
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:10]}"


def _config_sha256(config: ProjectConfig) -> str:
    payload = json.dumps(
        config.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _control_artifacts(config: ProjectConfig, paths: list[Path]) -> list[OperationArtifact]:
    root = canonical(config.artifact_root)
    artifacts: list[OperationArtifact] = []
    seen: set[Path] = set()
    for candidate in paths:
        path = canonical(candidate)
        if path in seen or candidate.suffix not in {".json", ".sha256"}:
            continue
        seen.add(path)
        try:
            if (
                candidate.is_symlink()
                or not is_within(path, root)
                or not path.is_file()
                or path.stat().st_size > 16 * 1024 * 1024
            ):
                continue
            artifacts.append(
                OperationArtifact(
                    path=str(path),
                    size=path.stat().st_size,
                    sha256=sha256_file(path),
                )
            )
        except OSError:
            continue
    return sorted(artifacts, key=lambda item: item.path)


class OperationRecorder:
    def __init__(
        self,
        config: ProjectConfig,
        *,
        command: OperationCommand,
        invocation: dict[str, Any],
        expected_items: list[str],
        input_fingerprints: dict[str, str] | None = None,
        parent_run_id: str | None = None,
    ) -> None:
        self.config = config
        self.run_id = _run_id(command)
        self.path = artifact_path(config.artifact_root, "logs", f"{self.run_id}.json")
        self._terminal = False
        self.manifest = OperationRunManifest(
            run_id=self.run_id,
            command=command,
            state="running",
            project_id=config.project_id,
            invocation=invocation,
            config_sha256=_config_sha256(config),
            input_fingerprints=input_fingerprints or {},
            environment=OperationEnvironment(
                package_version=__version__,
                python=platform.python_version(),
                platform=platform.platform(),
            ),
            progress=OperationProgress(expected_items=_unique(expected_items)),
            parent_run_id=parent_run_id,
            started_at=_utc_now(),
        )
        self._write()

    def _write(self) -> None:
        atomic_write_text(self.path, self.manifest.model_dump_json(indent=2) + "\n")

    def _updated_manifest(self, **updates: Any) -> OperationRunManifest:
        payload = self.manifest.model_dump(mode="python")
        payload.update(updates)
        return OperationRunManifest.model_validate(payload)

    def checkpoint(
        self,
        *,
        completed_items: list[str] | None = None,
        cached_items: list[str] | None = None,
        skipped_items: list[str] | None = None,
        metrics: dict[str, int] | None = None,
        tools: dict[str, str] | None = None,
        artifacts: list[Path] | None = None,
    ) -> None:
        if self._terminal:
            return
        progress = OperationProgress.model_validate(
            {
                **self.manifest.progress.model_dump(mode="python"),
                "completed_items": _unique(
                    completed_items
                    if completed_items is not None
                    else self.manifest.progress.completed_items
                ),
                "cached_items": _unique(
                    cached_items
                    if cached_items is not None
                    else self.manifest.progress.cached_items
                ),
                "skipped_items": _unique(
                    skipped_items
                    if skipped_items is not None
                    else self.manifest.progress.skipped_items
                ),
                "metrics": {
                    **self.manifest.progress.metrics,
                    **(metrics or {}),
                },
            }
        )
        self.manifest = self._updated_manifest(
            progress=progress,
            tools={**self.manifest.tools, **(tools or {})},
            artifacts=(
                _control_artifacts(self.config, artifacts)
                if artifacts is not None
                else self.manifest.artifacts
            ),
        )
        self._write()

    def finish(
        self,
        *,
        state: OperationState = "succeeded",
        artifacts: list[Path] | None = None,
        warning_codes: list[str] | None = None,
    ) -> None:
        if self._terminal:
            return
        if state not in {"succeeded", "review_required"}:
            raise ValueError("Operation finish state must be succeeded or review_required.")
        self.manifest = self._updated_manifest(
            state=state,
            artifacts=_control_artifacts(
                self.config,
                [
                    *(Path(item.path) for item in self.manifest.artifacts),
                    *(artifacts or []),
                ],
            ),
            warning_codes=sorted(set(warning_codes or [])),
            completed_at=_utc_now(),
        )
        self._write()
        self._terminal = True

    def fail(self, error: BaseException) -> None:
        if self._terminal:
            return
        interrupted = isinstance(error, KeyboardInterrupt)
        if isinstance(error, InterviewEditError):
            code = error.code
        elif interrupted:
            code = "interrupted"
        else:
            code = "operation_failed"
        self.manifest = self._updated_manifest(
            state="interrupted" if interrupted else "failed",
            error=OperationError(code=code, category=type(error).__name__),
            completed_at=_utc_now(),
        )
        self._write()
        self._terminal = True


def start_operation(
    config: ProjectConfig,
    *,
    command: OperationCommand,
    invocation: dict[str, Any],
    expected_items: list[str],
    input_fingerprints: dict[str, str] | None = None,
    parent_run_id: str | None = None,
    enabled: bool = True,
) -> OperationRecorder | None:
    if not enabled:
        return None
    return OperationRecorder(
        config,
        command=command,
        invocation=invocation,
        expected_items=expected_items,
        input_fingerprints=input_fingerprints,
        parent_run_id=parent_run_id,
    )


def fail_operation(recorder: OperationRecorder | None, error: BaseException) -> None:
    if recorder is None:
        return
    recorder.fail(error)
    if isinstance(error, InterviewEditError):
        error.details.setdefault("runId", recorder.run_id)
        error.details.setdefault("runManifestPath", str(recorder.path))
