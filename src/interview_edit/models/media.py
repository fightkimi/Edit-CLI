from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$"


class MediaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VideoStream(MediaModel):
    index: int = Field(ge=0)
    codec_name: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    pixel_format: str | None = None
    color_range: str | None = None
    color_space: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None
    field_order: str | None = None
    time_base: str | None = None
    average_frame_rate: str | None = None
    real_frame_rate: str | None = None
    start_time_us: int | None = None
    duration_us: int | None = Field(default=None, ge=0)
    rotation: int | None = None


class AudioStream(MediaModel):
    index: int = Field(ge=0)
    codec_name: str | None = None
    sample_rate: int | None = Field(default=None, ge=1)
    channels: int | None = Field(default=None, ge=1)
    channel_layout: str | None = None
    time_base: str | None = None
    start_time_us: int | None = None
    duration_us: int | None = Field(default=None, ge=0)


class MediaAsset(MediaModel):
    asset_id: str = Field(pattern=r"^asset_[a-f0-9]{24}$")
    canonical_path: str
    media_root: str
    relative_path: str
    size: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)
    fingerprint: str = Field(pattern=r"^quick-sha256-v1:[a-f0-9]{64}$")
    full_hash: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    duration_us: int = Field(ge=0)
    stream_time_base: str | None = None
    start_time_us: int | None = None
    video_stream: VideoStream | None = None
    audio_streams: list[AudioStream] = Field(default_factory=list)
    camera_id: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)
    take_id: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)
    capture_time: str | None = None
    probe_version: str


class MediaIndexChanges(MediaModel):
    added: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)


class MediaIndexWarning(MediaModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class MediaIndex(MediaModel):
    schema_version: Literal["1"] = "1"
    project_id: str
    generated_at: str
    probe_version: str
    media_roots: list[str]
    extensions: list[str]
    assets: list[MediaAsset]
    changes: MediaIndexChanges = Field(default_factory=MediaIndexChanges)
    warnings: list[MediaIndexWarning] = Field(default_factory=list)


class CameraMapRule(MediaModel):
    glob: str = Field(min_length=1)
    camera_id: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)
    take_id: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)


class CameraMap(MediaModel):
    schema_version: Literal["1"] = "1"
    rules: list[CameraMapRule] = Field(default_factory=list)


ProxyOutputKind: TypeAlias = Literal["video", "audio", "thumbnail", "time_map"]


class ProxyOutput(MediaModel):
    kind: ProxyOutputKind
    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ProxyManifest(MediaModel):
    schema_version: Literal["1"] = "1"
    asset_id: str
    source_fingerprint: str
    source_full_hash: str | None = None
    cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    ffmpeg_version: str
    ffprobe_version: str
    settings: dict[str, Any]
    outputs: list[ProxyOutput]
    completed_at: str


class TimeMap(MediaModel):
    schema_version: Literal["1"] = "1"
    asset_id: str
    mapping: Literal["normalized_identity"] = "normalized_identity"
    source_start_us: int
    source_duration_us: int = Field(ge=0)
    proxy_start_us: int
    proxy_duration_us: int = Field(ge=0)
    source_time_base: str | None = None
    proxy_time_base: str | None = None
