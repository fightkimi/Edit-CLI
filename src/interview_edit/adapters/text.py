from __future__ import annotations

import importlib
import os
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from interview_edit.errors import DependencyError, ProcessingError


@dataclass(frozen=True)
class TextInspection:
    alpha_bounds: tuple[int, int, int, int] | None
    safe_bounds: tuple[int, int, int, int]
    within_safe_area: bool
    missing_glyph_count: int


def _pillow() -> tuple[Any, Any, Any]:
    try:
        return (
            importlib.import_module("PIL.Image"),
            importlib.import_module("PIL.ImageDraw"),
            importlib.import_module("PIL.ImageFont"),
        )
    except ImportError as exc:
        raise DependencyError(
            "pillow_missing",
            "Local title and subtitle rendering requires Pillow.",
        ) from exc


def _wrapped_lines(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return [""]
    estimated = max(1, int(max_width / max(1, draw.textlength("字", font=font))))
    lines: list[str] = []
    for paragraph in normalized.splitlines() or [normalized]:
        candidate_lines = textwrap.wrap(
            paragraph,
            width=estimated,
            break_long_words=True,
            break_on_hyphens=False,
        ) or [paragraph]
        lines.extend(candidate_lines)
    return lines[:4]


def _missing_glyph_count(font: Any, text: str) -> int:
    replacement = bytes(font.getmask("\ufffd"))
    replacement_bbox = font.getbbox("\ufffd")
    missing = 0
    for character in set(text):
        if character.isspace():
            continue
        if character == "\ufffd":
            missing += 1
            continue
        if (
            font.getbbox(character) == replacement_bbox
            and bytes(font.getmask(character)) == replacement
        ):
            missing += 1
    return missing


def _compose_text_image(
    *,
    text: str,
    font_path: Path,
    width: int,
    height: int,
    placement: Literal["center", "subtitle"],
    safe_area_percent: int,
) -> tuple[Any, TextInspection]:
    image_module, draw_module, font_module = _pillow()
    font_size = max(20, round(height * (0.072 if placement == "center" else 0.052)))
    font = font_module.truetype(str(font_path), font_size)
    image = image_module.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = draw_module.Draw(image)
    margin_x = round(width * safe_area_percent / 100)
    margin_y = round(height * safe_area_percent / 100)
    padding_x = round(font_size * 0.7)
    padding_y = round(font_size * 0.45)
    max_width = max(1, min(round(width * 0.82), width - 2 * margin_x - 2 * padding_x))
    lines = _wrapped_lines(draw, text, font, max_width)
    line_height = round(font_size * 1.35)
    block_height = line_height * len(lines)
    if placement == "center":
        center_y = height // 2
        fill = (255, 255, 255, 255)
        background = (0, 0, 0, 155)
    else:
        center_y = height - margin_y - padding_y - block_height // 2 - 1
        fill = (255, 255, 255, 255)
        background = (0, 0, 0, 185)
    top = center_y - block_height // 2
    measurements = [draw.textbbox((0, 0), line, font=font) for line in lines]
    max_text_width = max((box[2] - box[0] for box in measurements), default=0)
    left = max(margin_x, (width - max_text_width) // 2 - padding_x)
    right = min(width - margin_x, (width + max_text_width) // 2 + padding_x)
    rectangle = (left, top - padding_y, right, top + block_height + padding_y)
    draw.rounded_rectangle(
        rectangle,
        radius=max(8, font_size // 4),
        fill=background,
    )
    for position, line in enumerate(lines):
        box = measurements[position]
        text_width = box[2] - box[0]
        draw.text(
            ((width - text_width) // 2, top + position * line_height),
            line,
            font=font,
            fill=fill,
            stroke_width=max(1, font_size // 24),
            stroke_fill=(0, 0, 0, 230),
        )
    alpha_bounds = image.getchannel("A").getbbox()
    safe_bounds = (margin_x, margin_y, width - margin_x, height - margin_y)
    within_safe_area = alpha_bounds is not None and (
        alpha_bounds[0] >= safe_bounds[0]
        and alpha_bounds[1] >= safe_bounds[1]
        and alpha_bounds[2] <= safe_bounds[2]
        and alpha_bounds[3] <= safe_bounds[3]
    )
    return image, TextInspection(
        alpha_bounds=alpha_bounds,
        safe_bounds=safe_bounds,
        within_safe_area=within_safe_area,
        missing_glyph_count=_missing_glyph_count(font, text),
    )


def inspect_text_layout(
    *,
    text: str,
    font_path: Path,
    width: int,
    height: int,
    placement: Literal["center", "subtitle"],
    safe_area_percent: int,
) -> TextInspection:
    try:
        _, inspection = _compose_text_image(
            text=text,
            font_path=font_path,
            width=width,
            height=height,
            placement=placement,
            safe_area_percent=safe_area_percent,
        )
        return inspection
    except (OSError, ValueError) as exc:
        raise ProcessingError(
            "text_inspection_failed",
            "Could not inspect local title or subtitle layout.",
            details={"fontPath": str(font_path)},
        ) from exc


def render_text_png(
    *,
    text: str,
    font_path: Path,
    output_path: Path,
    width: int,
    height: int,
    placement: Literal["center", "subtitle"],
    safe_area_percent: int = 5,
) -> None:
    try:
        image, _ = _compose_text_image(
            text=text,
            font_path=font_path,
            width=width,
            height=height,
            placement=placement,
            safe_area_percent=safe_area_percent,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp.png")
        image.save(temporary, format="PNG", optimize=False)
        os.replace(temporary, output_path)
    except (OSError, ValueError) as exc:
        raise ProcessingError(
            "text_raster_failed",
            "Could not rasterize local title or subtitle text.",
            details={"fontPath": str(font_path), "outputPath": str(output_path)},
        ) from exc
