"""Bounded experimental slider mapping, not a claim of pixel-equivalent grading."""

from interview_edit.models.cutlist import ColorCorrection


def native_color_values(correction: ColorCorrection) -> dict[str, float]:
    return {
        name: value
        for name, value in {
            "KFTypeBrightness": correction.brightness,
            "KFTypeContrast": correction.contrast - 1,
            "KFTypeSaturation": correction.saturation - 1,
        }.items()
        if value != 0
    }
