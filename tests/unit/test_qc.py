from __future__ import annotations

from pathlib import Path

import pytest

from interview_edit.adapters.qc import (
    parse_black_intervals,
    parse_loudness_measurement,
    parse_silence_intervals,
)
from interview_edit.adapters.text import inspect_text_layout
from interview_edit.config.models import QCConfig
from interview_edit.models.cutlist import TimelineItem
from interview_edit.models.qc import QCFinding
from interview_edit.qc.service import TimelineSegment, _check_duplicate_sources


def test_qc_config_has_conservative_release_defaults() -> None:
    config = QCConfig()

    assert config.black_min_duration_seconds == 0.5
    assert config.silence_min_duration_seconds == 2.0
    assert config.silence_noise_db == -50.0
    assert config.max_av_duration_delta_us == 100_000
    assert config.max_timeline_duration_delta_us == 100_000
    assert config.integrated_lufs_tolerance == 1.0
    assert config.true_peak_tolerance_db == 0.1


def test_parse_black_and_silence_intervals_uses_integer_microseconds() -> None:
    black = parse_black_intervals(
        "black_start:0.25 black_end:1.75 black_duration:1.5\n"
        "black_start:2 black_end:2.6 black_duration:0.6"
    )
    silence = parse_silence_intervals(
        "silence_start: 0.500000\nsilence_end: 2.750000 | silence_duration: 2.250000\n"
    )

    assert [(span.start_us, span.end_us, span.duration_us) for span in black] == [
        (250_000, 1_750_000, 1_500_000),
        (2_000_000, 2_600_000, 600_000),
    ]
    assert [(span.start_us, span.end_us, span.duration_us) for span in silence] == [
        (500_000, 2_750_000, 2_250_000)
    ]


def test_qc_flags_an_exact_reused_broll_range() -> None:
    source_id = "asset_" + "a" * 24
    items = [
        TimelineItem(
            item_id=f"item_{index:03d}",
            kind="broll",
            source_id=source_id,
            source_in_us=100_000,
            source_out_us=600_000,
            timeline_duration_us=500_000,
        )
        for index in (1, 2)
    ]
    findings: list[QCFinding] = []

    _check_duplicate_sources(
        [
            TimelineSegment(item=items[0], start_us=0, end_us=500_000),
            TimelineSegment(item=items[1], start_us=500_000, end_us=1_000_000),
        ],
        findings,
    )

    assert [finding.code for finding in findings] == ["source_range_reused"]
    assert findings[0].details["firstItemId"] == "item_001"


def test_parse_loudness_measurement_handles_finite_and_unmeasurable_values() -> None:
    measured = parse_loudness_measurement(
        'prefix\n{"input_i":"-16.20","input_tp":"-1.05","input_lra":"3.10"}\nsuffix'
    )
    silent = parse_loudness_measurement('{"input_i":"-inf","input_tp":"-inf","input_lra":"0.00"}')

    assert measured.integrated_lufs == -16.2
    assert measured.true_peak_dbtp == -1.05
    assert measured.loudness_range_lu == 3.1
    assert silent.integrated_lufs is None
    assert silent.true_peak_dbtp is None


def test_text_inspection_enforces_safe_area_and_counts_missing_glyphs() -> None:
    font = Path("/System/Library/Fonts/STHeiti Medium.ttc")
    if not font.is_file():
        pytest.skip("macOS Chinese test font is unavailable")

    inspection = inspect_text_layout(
        text="中文 A \U0010ffff",
        font_path=font,
        width=1280,
        height=720,
        placement="subtitle",
        safe_area_percent=5,
    )

    assert inspection.within_safe_area is True
    assert inspection.alpha_bounds is not None
    assert inspection.missing_glyph_count == 1
