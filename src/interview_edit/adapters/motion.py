from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from interview_edit.adapters.text import _missing_glyph_count, _wrapped_lines
from interview_edit.errors import PreflightError
from interview_edit.models.motion import MotionSpec
from interview_edit.motion.easing import progress


def card(spec: MotionSpec) -> tuple[Image.Image, tuple[int, int, int, int]]:
    primary = ImageFont.truetype(
        spec.font_path,
        max(12, round(spec.height * (0.085 if spec.template == "chapter" else 0.05))),
    )
    secondary = ImageFont.truetype(spec.font_path, max(10, round(spec.height * 0.03)))
    image = Image.new("RGBA", (spec.width, spec.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    padding = max(10, round(spec.height * 0.022))
    max_width = round(spec.width * 0.78) - 2 * padding
    first = _wrapped_lines(draw, spec.text, primary, max_width)
    second = _wrapped_lines(draw, spec.secondary, secondary, max_width) if spec.secondary else []
    if len(first) > 2 or len(second) > 2:
        raise PreflightError(
            "motion_text_overflow", "Shorten motion text to at most two lines per field."
        )
    if _missing_glyph_count(primary, spec.text) or _missing_glyph_count(secondary, spec.secondary):
        raise PreflightError(
            "motion_font_missing_glyphs", "Choose a local font covering all motion text."
        )
    sizes = [draw.textlength(line, font=primary) for line in first] + [
        draw.textlength(line, font=secondary) for line in second
    ]
    width = round(max(sizes)) + 2 * padding + max(5, spec.width // 160)
    first_height = round(primary.size * 1.3)
    second_height = round(secondary.size * 1.3)
    gap = padding if second else 0
    height = 2 * padding + len(first) * first_height + gap + len(second) * second_height
    margin = round(spec.height * 0.06)
    if width > spec.width - 2 * margin or height > spec.height - 2 * margin:
        raise PreflightError(
            "motion_layout_overflow", "Motion card does not fit the selected canvas."
        )
    if spec.template == "chapter":
        left, top = (spec.width - width) // 2, (spec.height - height) // 2
    else:
        left = round(spec.width * 0.07)
        top = round(spec.height * (0.16 if spec.template == "callout" else 0.62))
        top = min(top, spec.height - margin - height)
    right, bottom = left + width, top + height
    draw.rounded_rectangle(
        (left, top, right, bottom), radius=max(4, padding // 2), fill=spec.background + "E8"
    )
    draw.rounded_rectangle(
        (left, top, left + max(4, spec.width // 200), bottom), radius=3, fill=spec.accent
    )
    x, y = left + padding, top + padding
    for line in first:
        draw.text((x, y), line, font=primary, fill=spec.foreground, anchor="lt")
        y += first_height
    y += gap
    for line in second:
        draw.text((x, y), line, font=secondary, fill=spec.foreground, anchor="lt")
        y += second_height
    return image, (left, top, right, bottom)


def frame(base: Image.Image, spec: MotionSpec, time_us: int) -> Image.Image:
    amount = progress(time_us, spec.duration_us, spec.enter_us, spec.exit_us)
    result = Image.new("RGBA", base.size, (0, 0, 0, 0))
    faded = base.copy()
    faded.putalpha(base.getchannel("A").point(lambda alpha: round(alpha * amount)))
    displacement = round(spec.height * 0.04 * (1 - amount))
    result.alpha_composite(faded, (0, displacement))
    return result
