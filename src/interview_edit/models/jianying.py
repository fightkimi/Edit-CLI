from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DraftFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relative_path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class JianyingManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1"] = "1"
    exporter: Literal["interview-edit-jianying-v1"] = "interview-edit-jianying-v1"
    export_id: str = Field(pattern=r"^[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}$")
    project_id: str
    draft_name: str
    cutlist_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    platform: Literal["macos", "windows", "both"]
    bundled_media: bool
    native_validation: Literal["not_run"] = "not_run"
    duration_us: int = Field(gt=0, strict=True)
    files: list[DraftFile]
    source_map: list[dict[str, Any]]
    source_fingerprints: dict[str, str]
    created_at: str
