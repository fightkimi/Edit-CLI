from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from interview_edit.adapters.process import ProcessRunner
from interview_edit.adapters.render import run_render_command, seconds
from interview_edit.cutlist.color import correction_filter
from interview_edit.models.color import ColorStats
from interview_edit.models.cutlist import ColorCorrection


def color_frame(
    media: Path, time_us: int, output: Path, correction: ColorCorrection, runner: ProcessRunner
) -> None:
    grade = correction_filter(correction)
    filters = (grade + "," if grade else "") + "scale=640:-2:force_original_aspect_ratio=decrease"
    run_render_command(
        [
            "-nostdin",
            "-v",
            "error",
            "-ss",
            seconds(time_us),
            "-i",
            str(media),
            "-frames:v",
            "1",
            "-vf",
            filters,
            "-q:v",
            "2",
            "-y",
            str(output),
        ],
        runner,
        purpose="sample source color",
        timeout_seconds=120,
    )
    if not output.is_file():
        from interview_edit.errors import ProcessingError

        raise ProcessingError("color_frame_missing", "Color sample could not be extracted.")


def image_stats(paths: list[Path]) -> ColorStats:
    pixels = []
    for path in paths:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
            image.thumbnail((320, 180))
            pixels.append(np.asarray(image, dtype=np.float64).reshape(-1, 3) / 255)
    rgb = np.concatenate(pixels)
    luma = rgb @ np.array([0.2126, 0.7152, 0.0722])
    maximum = rgb.max(axis=1)
    saturation = (maximum - rgb.min(axis=1)) / np.maximum(maximum, 1 / 255)
    return ColorStats(
        mean_luma=float(luma.mean()),
        luma_p05=float(np.quantile(luma, 0.05)),
        luma_p95=float(np.quantile(luma, 0.95)),
        mean_saturation=float(saturation.mean()),
        shadow_fraction=float(np.mean(luma <= 0.03)),
        highlight_fraction=float(np.mean(luma >= 0.97)),
    )


def color_contact(
    before: list[Path], after: list[Path], times: list[int], output: Path, status: str
) -> None:
    width = 360
    row = 250
    image = Image.new("RGB", (width * 2 + 60, 80 + row * len(before)), "#171b23")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=18)
    draw.text(
        (20, 12),
        "Original",
        font=font,
        fill="white",
    )
    draw.text((width + 40, 12), f"After ({status})", font=font, fill="white")
    for i, (left, right, time) in enumerate(zip(before, after, times, strict=True)):
        draw.text((20, 48 + row * i), f"{seconds(time)} s", font=font, fill="#b9c4d5")
        for column, path in enumerate([left, right]):
            with Image.open(path) as opened:
                frame = opened.convert("RGB")
                frame.thumbnail((width, 202))
                image.paste(
                    frame,
                    (
                        20 + column * (width + 20) + (width - frame.width) // 2,
                        75 + row * i + (202 - frame.height) // 2,
                    ),
                )
    image.save(output)
