from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from interview_edit.models.motion import MotionManifest, MotionSpec


class DraftMotion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str
    spec: MotionSpec
    manifest: MotionManifest
    resources: dict[str, str]
    inputs: dict[str, str]


class DraftFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relative_path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class DraftSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str
    resource_path: str
    duration_us: int = Field(gt=0, strict=True)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class JianyingManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1", "2", "3"] = "2"
    exporter: Literal[
        "interview-edit-jianying-v1", "interview-edit-jianying-v2", "interview-edit-jianying-v3"
    ] = "interview-edit-jianying-v2"
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
    input_snapshot: str | None = None
    control_fingerprints: dict[str, str] = Field(default_factory=dict)
    config_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_assets: dict[str, DraftSource] = Field(default_factory=dict)
    material_sources: dict[str, str] = Field(default_factory=dict)
    native_effects: bool = False
    motion_assets: dict[str, DraftMotion] = Field(default_factory=dict)

    @model_validator(mode="after")
    def snapshot_required(self) -> JianyingManifest:
        if self.schema_version in {"2", "3"} and (
            not self.input_snapshot or not self.config_sha256
        ):
            raise ValueError("Export v2 requires an input snapshot and configuration hash.")
        if (self.native_effects or self.motion_assets) and self.schema_version != "3":
            raise ValueError("Native effects require export schema 3.")
        return self
