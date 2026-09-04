from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TranscriptModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TranscriptWord(TranscriptModel):
    start_us: int = Field(ge=0)
    end_us: int = Field(ge=0)
    text: str
    probability: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def end_not_before_start(self) -> TranscriptWord:
        if self.end_us < self.start_us:
            raise ValueError("word end_us must be greater than or equal to start_us")
        return self


class TranscriptSegment(TranscriptModel):
    schema_version: Literal["1"] = "1"
    segment_id: str = Field(pattern=r"^seg_[0-9]{8}$")
    asset_id: str = Field(pattern=r"^asset_[a-f0-9]{24}$")
    start_us: int = Field(ge=0)
    end_us: int = Field(ge=0)
    text: str = Field(min_length=1)
    words: list[TranscriptWord] = Field(default_factory=list)
    correction_rule_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_times(self) -> TranscriptSegment:
        if self.end_us < self.start_us:
            raise ValueError("segment end_us must be greater than or equal to start_us")
        if any(word.start_us < self.start_us or word.end_us > self.end_us for word in self.words):
            raise ValueError("word timestamps must be within their segment")
        return self


class CorrectionRule(TranscriptModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    find: str = Field(min_length=1)
    replace: str
    enabled: bool = True


class CorrectionDictionary(TranscriptModel):
    schema_version: Literal["1"] = "1"
    rules: list[CorrectionRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self) -> CorrectionDictionary:
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("correction rule IDs must be unique")
        return self


class TranscriptChunk(TranscriptModel):
    schema_version: Literal["1"] = "1"
    asset_id: str = Field(pattern=r"^asset_[a-f0-9]{24}$")
    transcription_cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    chunk_index: int = Field(ge=0)
    start_us: int = Field(ge=0)
    end_us: int = Field(ge=0)
    detected_language: str
    segments: list[TranscriptSegment]


class TranscriptOutput(TranscriptModel):
    kind: Literal["raw_jsonl", "corrected_jsonl", "raw_srt", "corrected_srt"]
    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class TranscriptManifest(TranscriptModel):
    schema_version: Literal["1"] = "1"
    asset_id: str = Field(pattern=r"^asset_[a-f0-9]{24}$")
    source_fingerprint: str
    source_full_hash: str | None = None
    audio_proxy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    transcription_cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    backend: str
    backend_version: str
    model: str
    resolved_model: str
    device: str
    language: str
    parameters: dict[str, Any]
    correction_fingerprint: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    segment_count: int = Field(ge=0)
    word_count: int = Field(ge=0)
    outputs: list[TranscriptOutput]
    completed_at: str
