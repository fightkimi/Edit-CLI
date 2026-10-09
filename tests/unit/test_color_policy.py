import pytest
from pydantic import ValidationError

from interview_edit.cutlist.color import correction_filter, suggest_correction
from interview_edit.models.color import ColorStats
from interview_edit.models.cutlist import ColorCorrection


def test_neutral_policy_is_exactly_no_filter_and_values_are_finite_bounded():
    assert correction_filter(ColorCorrection()) == ""
    for values in [
        {"brightness": 0.5},
        {"gamma": float("nan")},
        {"contrast": float("inf")},
        {"saturation": -1},
    ]:
        with pytest.raises(ValidationError):
            ColorCorrection(**values)


def test_low_variation_graphics_are_not_blindly_brightened():
    stats = ColorStats(
        mean_luma=0.05,
        luma_p05=0.05,
        luma_p95=0.05,
        mean_saturation=0.9,
        shadow_fraction=1,
        highlight_fraction=0,
    )
    assert suggest_correction(stats, None) == ColorCorrection()


def test_reference_brightness_suggestion_is_bounded_and_not_a_hue_filter():
    dark = ColorStats(
        mean_luma=0.2,
        luma_p05=0.1,
        luma_p95=0.4,
        mean_saturation=0.2,
        shadow_fraction=0,
        highlight_fraction=0,
    )
    light = dark.model_copy(update={"mean_luma": 0.6})
    result = suggest_correction(dark, light)
    assert result.brightness == 0.08
    assert result.gamma == 1 and result.saturation == 1
    assert "hue" not in correction_filter(result)
