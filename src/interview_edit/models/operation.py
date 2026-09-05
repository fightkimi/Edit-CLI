from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

OperationCommand = Literal["proxy_build", "transcribe", "sync"]
OperationState = Literal["running", "succeeded", "review_required", "failed", "interrupted"]


class OperationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OperationProgress(OperationModel):
    expected_items: list[str] = Field(default_factory=list)
    completed_items: list[str] = Field(default_factory=list)
    cached_items: list[str] = Field(default_factory=list)
    skipped_items: list[str] = Field(default_factory=list)
    metrics: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_progress(self) -> OperationProgress:
        expected = self.expected_items
        groups = [self.completed_items, self.cached_items, self.skipped_items]
        if len(expected) != len(set(expected)) or any(
            len(group) != len(set(group)) for group in groups
        ):
            raise ValueError("Operation progress item lists must not contain duplicates.")
        expected_set = set(expected)
        observed = [set(group) for group in groups]
        if any(not group.issubset(expected_set) for group in observed):
            raise ValueError("Operation progress items must belong to expected_items.")
        if any(
            observed[left] & observed[right] for left in range(3) for right in range(left + 1, 3)
        ):
            raise ValueError("Completed, cached, and skipped operation items must be disjoint.")
        if any(value < 0 for value in self.metrics.values()):
            raise ValueError("Operation progress metrics must be non-negative.")
        return self


class OperationArtifact(OperationModel):
    kind: Literal["control"] = "control"
    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class OperationError(OperationModel):
    code: str
    category: str


class OperationEnvironment(OperationModel):
    package_version: str
    python: str
    platform: str
    git_commit: str | None = None


class OperationRunManifest(OperationModel):
    schema_version: Literal["1"] = "1"
    run_id: str = Field(pattern=r"^(proxy|transcribe|sync)_[A-Za-z0-9_]+$")
    command: OperationCommand
    state: OperationState
    project_id: str
    invocation: dict[str, Any]
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_fingerprints: dict[str, str] = Field(default_factory=dict)
    tools: dict[str, str] = Field(default_factory=dict)
    environment: OperationEnvironment
    progress: OperationProgress
    artifacts: list[OperationArtifact] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    error: OperationError | None = None
    parent_run_id: str | None = None
    started_at: str
    completed_at: str | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> OperationRunManifest:
        expected_prefix = "proxy" if self.command == "proxy_build" else self.command
        if not self.run_id.startswith(f"{expected_prefix}_"):
            raise ValueError("Operation run ID prefix must match its command.")
        if self.state == "running":
            if self.completed_at is not None or self.error is not None:
                raise ValueError("A running operation cannot contain terminal evidence.")
        elif self.state in {"succeeded", "review_required"}:
            if self.completed_at is None or self.error is not None:
                raise ValueError("A successful/review operation requires clean terminal evidence.")
            if self.state == "review_required" and not self.warning_codes:
                raise ValueError("A review-required operation must explain the review reason.")
        elif self.completed_at is None or self.error is None:
            raise ValueError("A failed/interrupted operation requires terminal error evidence.")
        return self
