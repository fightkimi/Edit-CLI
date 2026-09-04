from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from interview_edit.models.cutlist import TimelineSpec


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class PrivacyMode(StrEnum):
    STRICT = "strict"
    ASSISTED = "assisted"


class TranscriptionBackend(StrEnum):
    AUTO = "auto"
    MLX_WHISPER = "mlx-whisper"
    FASTER_WHISPER = "faster-whisper"
    MOCK = "mock"


class ModelSource(StrEnum):
    REGISTRY = "registry"
    LOCAL = "local"


class TranscriptionConfig(StrictModel):
    backend: TranscriptionBackend = TranscriptionBackend.AUTO
    model: str = "tiny"
    model_source: ModelSource = ModelSource.REGISTRY
    device: Literal["auto", "cpu", "cuda", "metal"] = "auto"
    language: str = "zh"
    download_policy: Literal["ask", "never"] = "ask"
    chunk_duration_seconds: int = Field(default=300, ge=30, le=3600)


class SyncConfig(StrictModel):
    window_count: int = Field(default=3, ge=3)
    minimum_confidence: float = Field(default=0.7, ge=0, le=1)
    sample_rate: int = Field(default=8_000, ge=4_000, le=48_000)
    envelope_hz: int = Field(default=100, ge=20, le=200)
    window_duration_seconds: int = Field(default=20, ge=2, le=120)
    max_offset_seconds: int = Field(default=30, ge=1, le=300)
    drift_tolerance_us_per_hour: int = Field(default=40_000, ge=0)


class RenderProfile(StrictModel):
    video_codec: str
    width: int = Field(ge=2)
    height: int = Field(ge=2)
    frame_rate: str
    audio_codec: str = "aac"
    audio_sample_rate: int = Field(default=48_000, ge=8_000)
    audio_channels: int = Field(default=2, ge=1)
    crf: int | None = Field(default=None, ge=0, le=63)


def default_render_profiles() -> dict[str, RenderProfile]:
    return {
        "preview": RenderProfile(
            video_codec="libx264",
            width=1280,
            height=720,
            frame_rate="25/1",
            crf=24,
        ),
        "master": RenderProfile(
            video_codec="auto",
            width=1920,
            height=1080,
            frame_rate="25/1",
            crf=18,
        ),
    }


class AudioTargets(StrictModel):
    integrated_lufs: float = -16.0
    true_peak_dbtp: float = -1.0
    loudness_range_lu: float = 11.0


class QCConfig(StrictModel):
    black_min_duration_seconds: float = Field(default=0.5, gt=0, le=60)
    black_pixel_threshold: float = Field(default=0.1, ge=0, le=1)
    black_picture_ratio: float = Field(default=0.98, ge=0, le=1)
    silence_min_duration_seconds: float = Field(default=2.0, gt=0, le=300)
    silence_noise_db: float = Field(default=-50.0, ge=-120, le=0)
    max_av_duration_delta_us: int = Field(default=100_000, ge=0, strict=True)
    max_timeline_duration_delta_us: int = Field(default=100_000, ge=0, strict=True)
    integrated_lufs_tolerance: float = Field(default=1.0, ge=0, le=10)
    true_peak_tolerance_db: float = Field(default=0.1, ge=0, le=3)
    cut_evidence_offset_us: int = Field(default=100_000, gt=0, strict=True)
    max_evidence_cuts: int = Field(default=100, ge=0, le=1_000, strict=True)
    max_detection_findings: int = Field(default=100, ge=1, le=10_000, strict=True)


class ProxyConfig(StrictModel):
    video_codec: str = "libx264"
    max_width: int = Field(default=1280, ge=160)
    crf: int = Field(default=28, ge=0, le=51)
    preset: str = "veryfast"
    audio_sample_rate: int = Field(default=16_000, ge=8_000)
    audio_channels: int = Field(default=1, ge=1, le=2)
    thumbnail_width: int = Field(default=480, ge=160)
    contact_sheet_columns: int = Field(default=4, ge=1, le=8)
    contact_sheet_rows: int = Field(default=5, ge=1, le=8)


class SafetyConfig(StrictModel):
    source_media_read_only: bool = True
    allow_network: bool = False
    allow_source_symlinks_outside_root: bool = False


class ProjectConfig(StrictModel):
    schema_version: Literal["1"] = "1"
    project_id: str = Field(pattern=r"^prj_[a-z0-9][a-z0-9_-]{5,63}$")
    name: str = Field(min_length=1, max_length=200)
    media_roots: list[Path] = Field(min_length=1)
    artifact_root: Path
    privacy_mode: PrivacyMode
    language: str = "zh"
    timeline: TimelineSpec = Field(default_factory=TimelineSpec)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    render_profiles: dict[str, RenderProfile] = Field(default_factory=default_render_profiles)
    audio_targets: AudioTargets = Field(default_factory=AudioTargets)
    qc: QCConfig = Field(default_factory=QCConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    fonts: list[Path] = Field(default_factory=list)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
