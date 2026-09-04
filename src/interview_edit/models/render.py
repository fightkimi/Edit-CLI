from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RenderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class RenderCommand(RenderModel):
    purpose: str
    args: list[str]
    return_code: int


class RenderCacheEntry(RenderModel):
    item_id: str
    cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: Literal["built", "cached", "planned"]
    path: str
    size: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class RenderItemManifest(RenderModel):
    schema_version: Literal["1"] = "1"
    item_id: str
    cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile: str
    encoder: str
    output_path: str
    output_size: int = Field(ge=0)
    output_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    commands: list[RenderCommand]
    completed_at: str


class RenderOutput(RenderModel):
    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duration_us: int = Field(ge=0)


class RenderRunManifest(RenderModel):
    schema_version: Literal["1"] = "1"
    run_id: str
    state: Literal["running", "succeeded", "failed", "interrupted", "planned"]
    project_id: str
    cutlist_path: str
    cutlist_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile: str
    selection: dict[str, Any]
    invocation: dict[str, Any]
    input_fingerprints: dict[str, str]
    ffmpeg_version: str
    encoder: str
    environment: dict[str, str | None]
    cache: list[RenderCacheEntry] = Field(default_factory=list)
    commands: list[RenderCommand] = Field(default_factory=list)
    output: RenderOutput | None = None
    error: dict[str, Any] | None = None
    started_at: str
    completed_at: str | None = None
