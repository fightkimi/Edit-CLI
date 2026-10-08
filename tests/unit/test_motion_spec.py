import pytest
from pydantic import ValidationError

from interview_edit.models.motion import MotionSpec
from interview_edit.motion.easing import progress


def spec(**kwargs):
    return MotionSpec(text="Editable title", font_path="/tmp/font.ttf", **kwargs)


def test_timing_and_frame_budget_are_bounded():
    for value in [
        {"duration_us": 100_000},
        {"enter_us": 2_000_000, "exit_us": 2_000_000},
        {"frame_rate": "120/1"},
        {"accent": "red"},
        {"width": 3840, "height": 3840},
    ]:
        with pytest.raises(ValidationError):
            spec(**value)
    with pytest.raises(ValidationError):
        MotionSpec(text=" \n\t", font_path="/tmp/font.ttf")
    with pytest.raises(ValidationError):
        MotionSpec(text="Title", font_path="")


def test_motion_easing_has_hold_and_returns_to_transparency():
    assert progress(0, 3_000_000, 300_000, 250_000) == 0
    assert 0 < progress(150_000, 3_000_000, 300_000, 250_000) < 1
    assert progress(500_000, 3_000_000, 300_000, 250_000) == 1
    assert progress(2_500_000, 3_000_000, 300_000, 250_000) == 1
    assert progress(3_000_000, 3_000_000, 300_000, 250_000) == 0
