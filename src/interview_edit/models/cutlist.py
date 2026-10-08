from __future__ import annotations

from enum import StrEnum
from fractions import Fraction
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CutListModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class TimelineItemKind(StrEnum):
    PRIMARY = "primary"
    BROLL = "broll"
    STILL = "still"
    TITLE = "title"
    TRANSITION = "transition"


class OverlayKind(StrEnum):
    BROLL = "broll"
    STILL = "still"
    TITLE = "title"
    MOTION = "motion"


class TransitionKind(StrEnum):
    FADE = "fade"


class TimelineSpec(CutListModel):
    frame_rate: str = "25/1"
    width: int = Field(default=1920, ge=2)
    height: int = Field(default=1080, ge=2)

    @field_validator("frame_rate")
    @classmethod
    def validate_frame_rate(cls, value: str) -> str:
        try:
            rate = Fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError("frame_rate must be a positive rational such as 25/1") from exc
        if rate <= 0 or "/" not in value:
            raise ValueError("frame_rate must be a positive rational such as 25/1")
        return value


class CameraCut(CutListModel):
    cut_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    camera_id: str = Field(min_length=1, max_length=120)
    start_us: int = Field(ge=0, strict=True)
    duration_us: int = Field(gt=0, strict=True)

    @property
    def end_us(self) -> int:
        return self.start_us + self.duration_us


class Overlay(CutListModel):
    overlay_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    kind: OverlayKind
    start_us: int = Field(ge=0, strict=True)
    duration_us: int = Field(gt=0, strict=True)
    source_id: str | None = Field(default=None, pattern=r"^asset_[a-f0-9]{24}$")
    source_in_us: int | None = Field(default=None, ge=0, strict=True)
    source_out_us: int | None = Field(default=None, ge=0, strict=True)
    image_path: str | None = None
    text: str | None = Field(default=None, min_length=1)
    font_path: str | None = None
    motion_path: str | None = None

    @property
    def end_us(self) -> int:
        return self.start_us + self.duration_us

    @model_validator(mode="after")
    def validate_kind_fields(self) -> Overlay:
        source_values = (self.source_id, self.source_in_us, self.source_out_us)
        if self.kind is OverlayKind.BROLL:
            if any(value is None for value in source_values):
                raise ValueError(
                    "broll overlay requires source_id, source_in_us, and source_out_us"
                )
            assert self.source_in_us is not None and self.source_out_us is not None
            if self.source_out_us <= self.source_in_us:
                raise ValueError("broll overlay source_out_us must be greater than source_in_us")
            if self.source_out_us - self.source_in_us != self.duration_us:
                raise ValueError("broll overlay source range must equal duration_us")
        elif any(value is not None for value in source_values):
            raise ValueError("only broll overlays may define source fields")
        if self.kind is OverlayKind.STILL and not self.image_path:
            raise ValueError("still overlay requires image_path")
        if self.kind is OverlayKind.TITLE and not self.text:
            raise ValueError("title overlay requires text")
        if self.kind is OverlayKind.MOTION and not self.motion_path:
            raise ValueError("motion overlay requires a generated motion asset directory")
        if self.kind is not OverlayKind.MOTION and self.motion_path is not None:
            raise ValueError("only motion overlays may define motion_path")
        return self


class Subtitle(CutListModel):
    subtitle_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    start_us: int = Field(ge=0, strict=True)
    duration_us: int = Field(gt=0, strict=True)
    text: str = Field(min_length=1)
    font_path: str | None = None

    @property
    def end_us(self) -> int:
        return self.start_us + self.duration_us


class Transition(CutListModel):
    kind: TransitionKind = TransitionKind.FADE
    duration_us: int = Field(gt=0, strict=True)


class TimelineItem(CutListModel):
    item_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    kind: TimelineItemKind
    content_role: str | None = Field(default=None, min_length=1, max_length=120)
    source_id: str | None = Field(default=None, pattern=r"^asset_[a-f0-9]{24}$")
    source_in_us: int | None = Field(default=None, ge=0, strict=True)
    source_out_us: int | None = Field(default=None, ge=0, strict=True)
    timeline_duration_us: int = Field(gt=0, strict=True)
    audio_source: str | None = Field(default=None, pattern=r"^asset_[a-f0-9]{24}$")
    base_camera: str | None = Field(default=None, min_length=1, max_length=120)
    image_path: str | None = None
    title_text: str | None = Field(default=None, min_length=1)
    font_path: str | None = None
    camera_cuts: list[CameraCut] = Field(default_factory=list)
    overlays: list[Overlay] = Field(default_factory=list)
    subtitles: list[Subtitle] = Field(default_factory=list)
    transition_in: Transition | None = None
    transition_out: Transition | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_kind_fields(self) -> TimelineItem:
        source_values = (self.source_id, self.source_in_us, self.source_out_us)
        source_backed = self.kind in {TimelineItemKind.PRIMARY, TimelineItemKind.BROLL}
        if source_backed:
            if any(value is None for value in source_values):
                raise ValueError(
                    "primary and broll items require source_id, source_in_us, and source_out_us"
                )
            assert self.source_in_us is not None and self.source_out_us is not None
            if self.source_out_us <= self.source_in_us:
                raise ValueError("source_out_us must be greater than source_in_us")
            if self.source_out_us - self.source_in_us != self.timeline_duration_us:
                raise ValueError("source range must equal timeline_duration_us for 1x playback")
        elif any(value is not None for value in source_values):
            raise ValueError("only primary and broll items may define source fields")

        if self.kind is TimelineItemKind.STILL and not self.image_path:
            raise ValueError("still item requires image_path")
        if self.kind is TimelineItemKind.TITLE and not self.title_text:
            raise ValueError("title item requires title_text")
        if self.kind is not TimelineItemKind.PRIMARY and (
            self.camera_cuts or self.base_camera is not None
        ):
            raise ValueError("camera cuts and base_camera are valid only on primary items")
        if self.kind not in {TimelineItemKind.PRIMARY, TimelineItemKind.BROLL} and (
            self.audio_source is not None
        ):
            raise ValueError("audio_source is valid only on primary and broll items")
        return self


class Act(CutListModel):
    act_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    title: str | None = None
    items: list[TimelineItem] = Field(default_factory=list)


class SubtitlePolicy(CutListModel):
    enabled: bool = True
    language: str = Field(default="zh", min_length=1, max_length=32)
    safe_area_percent: int = Field(default=5, ge=0, le=25)
    style: Literal["standard", "minimal"] = "standard"


class AudioPolicy(CutListModel):
    edge_fade_us: int = Field(default=0, ge=0, le=50_000, strict=True)


class ColorCorrection(CutListModel):
    brightness: float = Field(default=0, ge=-0.15, le=0.15, strict=True)
    contrast: float = Field(default=1, ge=0.75, le=1.25, strict=True)
    gamma: float = Field(default=1, ge=0.75, le=1.25, strict=True)
    saturation: float = Field(default=1, ge=0, le=1.5, strict=True)


class ColorPolicy(CutListModel):
    by_source: dict[Annotated[str, Field(pattern=r"^asset_[a-f0-9]{24}$")], ColorCorrection] = (
        Field(default_factory=dict)
    )


class CutList(CutListModel):
    schema_version: Literal["1"] = "1"
    project_id: str = Field(pattern=r"^prj_[a-z0-9][a-z0-9_-]{5,63}$")
    timeline: TimelineSpec = Field(default_factory=TimelineSpec)
    acts: list[Act] = Field(default_factory=list)
    subtitle_policy: SubtitlePolicy = Field(default_factory=SubtitlePolicy)
    audio_policy: AudioPolicy = Field(default_factory=AudioPolicy)
    color_policy: ColorPolicy = Field(default_factory=ColorPolicy)
    render_profile: str = Field(default="preview", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ValidationIssue(CutListModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    path: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class CutListValidationReport(CutListModel):
    schema_version: Literal["1"] = "1"
    cutlist_path: str
    project_id: str
    profile: str
    ok: bool
    act_count: int = Field(ge=0)
    item_count: int = Field(ge=0)
    timeline_duration_us: int = Field(ge=0)
    issues: list[ValidationIssue] = Field(default_factory=list)
