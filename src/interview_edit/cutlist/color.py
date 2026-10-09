from __future__ import annotations

from interview_edit.models.color import ColorStats
from interview_edit.models.cutlist import ColorCorrection


def correction_filter(value: ColorCorrection | None) -> str:
    if value is None or value == ColorCorrection():
        return ""
    # Static bounded eq values: https://ffmpeg.org/ffmpeg-filters.html#eq
    return (
        f"eq=brightness={value.brightness:.6f}:contrast={value.contrast:.6f}:"
        f"gamma={value.gamma:.6f}:saturation={value.saturation:.6f}"
    )


def suggest_correction(stats: ColorStats, reference: ColorStats | None) -> ColorCorrection:
    if stats.luma_p95 - stats.luma_p05 < 0.08:
        return ColorCorrection()
    if reference is not None:
        return ColorCorrection(
            brightness=round(max(-0.08, min(0.08, reference.mean_luma - stats.mean_luma)), 6)
        )
    brightness = round(min(0.06, max(0.0, (0.35 - stats.mean_luma) * 0.25)), 6)
    if stats.highlight_fraction > 0.1:
        brightness = round(max(-0.04, brightness - 0.04), 6)
    return ColorCorrection(brightness=brightness)


def is_hdr(transfer: str | None) -> bool:
    return transfer in {"smpte2084", "arib-std-b67"}
