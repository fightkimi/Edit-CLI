from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from interview_edit.models.media import AudioStream, VideoStream


class QCModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class QCPolicy(StrEnum):
    PREVIEW = "preview"
    RELEASE = "release"


class QCFindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKING = "blocking"


class QCTimeRange(QCModel):
    start_us: int = Field(ge=0, strict=True)
    end_us: int = Field(gt=0, strict=True)
    duration_us: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def validate_duration(self) -> QCTimeRange:
        if self.end_us <= self.start_us or self.end_us - self.start_us != self.duration_us:
            raise ValueError("QC time range duration must equal end_us - start_us")
        return self


class LoudnessMeasurement(QCModel):
    integrated_lufs: float | None = None
    true_peak_dbtp: float | None = None
    loudness_range_lu: float | None = None


class QCCommand(QCModel):
    purpose: str
    args: list[str]
    return_code: int


class QCEvidence(QCModel):
    kind: Literal["cut_before", "cut_after", "black_frame"]
    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    timeline_time_us: int = Field(ge=0, strict=True)
    item_id: str | None = None


class QCFinding(QCModel):
    severity: QCFindingSeverity
    code: str
    message: str
    item_id: str | None = None
    timeline_time_us: int | None = Field(default=None, ge=0, strict=True)
    source_id: str | None = None
    evidence_path: str | None = None
    suggested_action: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class QCStreamSummary(QCModel):
    duration_us: int = Field(ge=0, strict=True)
    video: VideoStream | None = None
    audio: list[AudioStream] = Field(default_factory=list)


class QCMeasurements(QCModel):
    black_intervals: list[QCTimeRange] = Field(default_factory=list)
    silence_intervals: list[QCTimeRange] = Field(default_factory=list)
    loudness: LoudnessMeasurement | None = None
    av_duration_delta_us: int | None = Field(default=None, ge=0, strict=True)
    timeline_duration_us: int | None = Field(default=None, ge=0, strict=True)
    output_duration_delta_us: int | None = Field(default=None, ge=0, strict=True)


class QCReport(QCModel):
    schema_version: Literal["1"] = "1"
    report_id: str = Field(pattern=r"^qc_[A-Za-z0-9_]+$")
    state: Literal["planned", "passed", "failed"]
    policy: QCPolicy
    project_id: str
    run_id: str
    render_manifest_path: str
    render_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    cutlist_path: str
    cutlist_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_path: str | None = None
    output_size: int | None = Field(default=None, ge=0)
    output_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    profile: str
    thresholds: dict[str, int | float]
    streams: QCStreamSummary | None = None
    measurements: QCMeasurements = Field(default_factory=QCMeasurements)
    findings: list[QCFinding] = Field(default_factory=list)
    evidence: list[QCEvidence] = Field(default_factory=list)
    ffmpeg_version: str | None = None
    ffprobe_version: str | None = None
    commands: list[QCCommand] = Field(default_factory=list)
    started_at: str
    completed_at: str | None = None
