from __future__ import annotations

from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MotionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class MotionSpec(MotionModel):
    schema_version: Literal["1"] = "1"
    template: Literal["callout", "lower_third", "chapter"] = "callout"
    text: str = Field(min_length=1, max_length=160)
    secondary: str = Field(default="", max_length=160)
    font_path: str = Field(min_length=1)
    width: int = Field(default=1920, ge=320, le=3840, strict=True)
    height: int = Field(default=1080, ge=180, le=3840, strict=True)
    frame_rate: str = "25/1"
    duration_us: int = Field(default=3_000_000, ge=800_000, le=10_000_000, strict=True)
    enter_us: int = Field(default=300_000, ge=0, le=2_000_000, strict=True)
    exit_us: int = Field(default=250_000, ge=0, le=2_000_000, strict=True)
    foreground: str = Field(default="#FFFFFF", pattern=r"^#[0-9a-fA-F]{6}$")
    background: str = Field(default="#151B24", pattern=r"^#[0-9a-fA-F]{6}$")
    accent: str = Field(default="#76A9FA", pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("text")
    @classmethod
    def visible_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Motion primary text must contain visible characters.")
        return value

    @field_validator("frame_rate")
    @classmethod
    def frame_rate_supported(cls, value: str) -> str:
        try:
            rate = Fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError("Use a positive rational frame rate.") from exc
        if "/" not in value or not 1 <= rate <= 60:
            raise ValueError("Motion frame rate must be 1–60fps.")
        return value

    @model_validator(mode="after")
    def budget(self) -> MotionSpec:
        if self.enter_us + self.exit_us > self.duration_us - 500_000:
            raise ValueError("Motion must retain at least 500ms at full readability.")
        if self.width * self.height > 3840 * 2160:
            raise ValueError("Motion canvas exceeds the 4K pixel budget.")
        return self


class MotionFile(MotionModel):
    relative_path: str
    size: int = Field(ge=0, strict=True)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class MotionManifest(MotionModel):
    schema_version: Literal["1"] = "1"
    asset_id: str = Field(pattern=r"^motion_[a-f0-9]{32}$")
    project_id: str
    spec_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    font_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duration_us: int = Field(gt=0, strict=True)
    frame_count: int = Field(gt=0, le=600, strict=True)
    codec: Literal["qtrle"] = "qtrle"
    pixel_format: Literal["argb"] = "argb"
    bounds: tuple[int, int, int, int]
    files: list[MotionFile]
    created_at: str
