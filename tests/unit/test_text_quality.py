from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from interview_edit.adapters.render import video_codec_args
from interview_edit.adapters.text import _wrapped_lines, inspect_text_layout, render_text_png
from interview_edit.config.models import RenderProfile
from interview_edit.errors import PreflightError


def font_path() -> Path:
    return Path(
        os.environ.get("INTERVIEW_EDIT_TEST_FONT", "/System/Library/Fonts/STHeiti Medium.ttc")
    )


@pytest.mark.parametrize("crf,expected", [(None, "20"), (0, "0"), (18, "18")])
def test_x264_preserves_zero_quality(crf: int | None, expected: str) -> None:
    profile = RenderProfile(
        video_codec="libx264", width=1920, height=1080, frame_rate="25/1", crf=crf
    )
    args = video_codec_args(profile, "libx264")
    assert args[args.index("-crf") + 1] == expected


def test_wrapping_preserves_long_chinese_and_uses_measured_width() -> None:
    font = ImageFont.truetype(str(font_path()), 37)
    draw = ImageDraw.Draw(Image.new("RGBA", (1280, 720)))
    text = "字幕必须保留完整语义，并且不能丢失结尾的关键数字1.25万元和否定条件。" * 10
    lines = _wrapped_lines(draw, text, font, 400)
    assert "".join(lines) == text
    assert all(draw.textlength(line, font=font) <= 400 for line in lines)


def test_overflow_is_reported_and_does_not_replace_a_raster(tmp_path: Path) -> None:
    args = dict(
        text="不能丢掉结尾的否定条件。" * 40,
        font_path=font_path(),
        width=1280,
        height=720,
        placement="subtitle",
        safe_area_percent=5,
    )
    inspection = inspect_text_layout(**args)
    assert inspection.overflow
    assert inspection.line_count > 4
    output = tmp_path / "kept.png"
    output.write_bytes(b"previous good raster")
    with pytest.raises(PreflightError) as error:
        render_text_png(**args, output_path=output)
    assert error.value.code == "text_layout_overflow"
    assert output.read_bytes() == b"previous good raster"


def test_minimal_and_standard_render_different_rasters(tmp_path: Path) -> None:
    from PIL import ImageChops

    common = dict(
        text="完整字幕",
        font_path=font_path(),
        width=1280,
        height=720,
        placement="subtitle",
        safe_area_percent=5,
    )
    standard = tmp_path / "standard.png"
    minimal = tmp_path / "minimal.png"
    render_text_png(**common, output_path=standard, style="standard")
    render_text_png(**common, output_path=minimal, style="minimal")
    with Image.open(standard) as a, Image.open(minimal) as b:
        assert ImageChops.difference(a, b).getbbox() is not None


def test_atomic_new_revision_does_not_overwrite_a_concurrent_file(tmp_path: Path) -> None:
    from interview_edit.errors import PathSafetyError
    from interview_edit.project.layout import atomic_write_text

    target = tmp_path / "revision.yaml"
    atomic_write_text(target, "winner", overwrite=False)
    with pytest.raises(PathSafetyError):
        atomic_write_text(target, "loser", overwrite=False)
    assert target.read_text() == "winner"
    assert list(tmp_path.iterdir()) == [target]


def test_small_canvas_cannot_silently_clip_two_line_title() -> None:
    inspection = inspect_text_layout(
        text="中\n文",
        font_path=font_path(),
        width=64,
        height=64,
        placement="center",
        safe_area_percent=5,
    )
    assert inspection.overflow
