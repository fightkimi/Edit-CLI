from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


class VersionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


FrozenFileRole: TypeAlias = Literal[
    "output",
    "render_run",
    "release_qc",
    "qc_checksum",
    "qc_evidence",
    "config",
    "cutlist",
]


class FrozenFile(VersionModel):
    role: FrozenFileRole
    relative_path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class VersionManifest(VersionModel):
    schema_version: Literal["1"] = "1"
    version_id: str = Field(pattern=r"^v[0-9]{4}$")
    project_id: str
    note: str | None = None
    source_run_id: str
    source_report_id: str
    source_render_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_qc_report_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    approval: Literal["explicit_cli_flag"] = "explicit_cli_flag"
    files: list[FrozenFile]
    created_at: str


class VersionSummary(VersionModel):
    version_id: str
    created_at: str
    source_run_id: str
    source_report_id: str
    note: str | None = None
    output_sha256: str


class VersionVerificationIssue(VersionModel):
    code: str
    message: str
    relative_path: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class VersionVerification(VersionModel):
    schema_version: Literal["1"] = "1"
    version_id: str
    state: Literal["passed", "failed"]
    checked_file_count: int = Field(ge=0)
    issues: list[VersionVerificationIssue] = Field(default_factory=list)
