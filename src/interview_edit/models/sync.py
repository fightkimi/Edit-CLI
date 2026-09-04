from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SyncModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyncWindow(SyncModel):
    reference_center_us: int = Field(ge=0)
    offset_us: int
    confidence: float = Field(ge=0, le=1)
    peak_margin: float = Field(ge=0, le=1)


class SyncCamera(SyncModel):
    camera_id: str
    asset_id: str = Field(pattern=r"^asset_[a-f0-9]{24}$")
    status: Literal["reference", "confirmed", "drifting", "uncertain", "manual"]
    offset_us: int
    drift_us_per_hour: int
    drift_ppm: int
    confidence: float = Field(ge=0, le=1)
    provenance: Literal["reference", "automatic_audio_correlation", "manual_override"]
    manual_value: str | None = None
    windows: list[SyncWindow] = Field(default_factory=list)


class SyncEvidence(SyncModel):
    kind: Literal["visual_contact_sheet"]
    path: str
    reference_time_us: int = Field(ge=0)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SyncReport(SyncModel):
    schema_version: Literal["1"] = "1"
    take_id: str
    reference_camera_id: str
    convention: Literal["camera_time = reference_time + offset"] = (
        "camera_time = reference_time + offset"
    )
    cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    analysis: dict[str, Any]
    cameras: list[SyncCamera]
    evidence: list[SyncEvidence] = Field(default_factory=list)
    completed_at: str
