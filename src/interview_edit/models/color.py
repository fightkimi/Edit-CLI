from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from interview_edit.models.cutlist import ColorCorrection


class ColorStats(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mean_luma: float = Field(ge=0, le=1)
    luma_p05: float = Field(ge=0, le=1)
    luma_p95: float = Field(ge=0, le=1)
    mean_saturation: float = Field(ge=0, le=1)
    shadow_fraction: float = Field(ge=0, le=1)
    highlight_fraction: float = Field(ge=0, le=1)


class ColorSample(BaseModel):
    time_us: int = Field(ge=0, strict=True)
    original_path: str
    original_sha256: str
    corrected_path: str
    corrected_sha256: str


class ColorReferenceSample(BaseModel):
    time_us: int = Field(ge=0, strict=True)
    path: str
    sha256: str


class ColorReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1"] = "1"
    project_id: str
    asset_id: str
    reference_id: str | None = None
    start_us: int = Field(ge=0, strict=True)
    end_us: int = Field(gt=0, strict=True)
    source_clock_origin_us: int = Field(default=0, strict=True)
    reference_clock_origin_us: int | None = Field(default=None, strict=True)
    before: ColorStats
    after: ColorStats
    reference: ColorStats | None = None
    reference_start_us: int | None = Field(default=None, ge=0, strict=True)
    reference_end_us: int | None = Field(default=None, gt=0, strict=True)
    reference_correction: ColorCorrection | None = None
    reference_samples: list[ColorReferenceSample] = Field(default_factory=list)
    correction: ColorCorrection
    correction_status: Literal["proposed", "configured"]
    samples: list[ColorSample]
    image_path: str
    image_sha256: str
    input_hashes: dict[str, str]
    source_fingerprints: dict[str, str]
    color_transfer: str | None = None
    warnings: list[str]
    quality_verified: Literal[False] = False
