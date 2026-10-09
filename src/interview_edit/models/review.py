from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from interview_edit.models.transcript import TranscriptWord


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Phrase(ReviewModel):
    asset_id: str
    start_us: int = Field(ge=0, strict=True)
    end_us: int = Field(gt=0, strict=True)
    text: str
    words: list[TranscriptWord] = Field(default_factory=list)
    timing: Literal["words", "segment"]
    speaker: Literal["unknown"] = "unknown"
    audio_events: Literal["unavailable"] = "unavailable"


class PhraseIndex(ReviewModel):
    schema_version: Literal["1"] = "1"
    project_id: str
    phrases: list[Phrase]
    input_hashes: dict[str, str]
    source_fingerprints: dict[str, str]


class TimelineWord(ReviewModel):
    asset_id: str
    item_id: str | None = None
    source_start_us: int = Field(ge=0, strict=True)
    source_end_us: int = Field(gt=0, strict=True)
    start_us: int = Field(ge=0, strict=True)
    end_us: int = Field(gt=0, strict=True)
    text: str
    clipped: bool = False


class ReviewFrame(ReviewModel):
    time_us: int = Field(ge=0, strict=True)
    path: str
    sha256: str


class TimelineReview(ReviewModel):
    schema_version: Literal["1"] = "1"
    project_id: str
    mode: Literal["source", "render"]
    media_path: str
    media_sha256: str
    start_us: int = Field(ge=0, strict=True)
    end_us: int = Field(gt=0, strict=True)
    focus_us: int = Field(ge=0, strict=True)
    words: list[TimelineWord]
    frames: list[ReviewFrame]
    image_path: str
    image_sha256: str
    audio_status: Literal["decoded", "missing"]
    audio_path: str | None = None
    audio_sha256: str | None = None
    audio_time_basis: Literal["resampled_presentation_clock"] = "resampled_presentation_clock"
    peak_dbfs: float | None
    rms_dbfs: float | None
    input_hashes: dict[str, str]
    source_fingerprints: dict[str, str]
    warnings: list[str] = Field(default_factory=list)
    listening_verified: Literal[False] = False
