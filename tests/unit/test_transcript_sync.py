from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from interview_edit.adapters import transcription
from interview_edit.config.models import ModelSource, TranscriptionBackend
from interview_edit.errors import PreflightError, UsageError
from interview_edit.models.transcript import CorrectionRule, TranscriptSegment, TranscriptWord
from interview_edit.sync.analysis import estimate_sync, window_centers_us
from interview_edit.sync.service import parse_manual_offset
from interview_edit.transcribe.service import _apply_rules, _model_revision


def test_transcript_times_are_integer_microseconds_and_words_stay_inside_segment() -> None:
    segment = TranscriptSegment(
        segment_id="seg_00000001",
        asset_id="asset_0123456789abcdef01234567",
        start_us=1_000_000,
        end_us=2_000_000,
        text="hello",
        words=[TranscriptWord(start_us=1_100_000, end_us=1_500_000, text="hello")],
    )

    assert segment.start_us == 1_000_000
    with pytest.raises(ValidationError):
        TranscriptSegment(
            segment_id="seg_00000001",
            asset_id="asset_0123456789abcdef01234567",
            start_us=1_000_000,
            end_us=2_000_000,
            text="hello",
            words=[TranscriptWord(start_us=900_000, end_us=1_500_000, text="hello")],
        )


def test_corrections_change_text_without_mutating_raw_segment() -> None:
    raw = TranscriptSegment(
        segment_id="seg_00000001",
        asset_id="asset_0123456789abcdef01234567",
        start_us=0,
        end_us=1_000_000,
        text="光厂 CLI",
        words=[TranscriptWord(start_us=0, end_us=500_000, text="光厂")],
    )

    corrected = _apply_rules(
        [raw], [CorrectionRule(id="brand", find="光厂", replace="Guang Tech")]
    )[0]

    assert raw.text == "光厂 CLI"
    assert raw.correction_rule_ids == []
    assert corrected.text == "Guang Tech CLI"
    assert corrected.words[0].text == "Guang Tech"
    assert corrected.correction_rule_ids == ["brand"]
    assert corrected.start_us == raw.start_us


@pytest.mark.parametrize(
    ("value", "expected"),
    [("close=125000", 125_000), ("close=-12.5ms", -12_500), ("close=+0.25s", 250_000)],
)
def test_manual_offset_parser_uses_integer_microseconds(value: str, expected: int) -> None:
    parsed = parse_manual_offset(value)

    assert parsed.camera_id == "close"
    assert parsed.offset_us == expected


def test_manual_offset_parser_rejects_ambiguous_value() -> None:
    with pytest.raises(UsageError):
        parse_manual_offset("close=one frame")


def test_registry_model_miss_requires_authorization_without_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(transcription, "_cached_snapshot", lambda _repo_id: None)

    with pytest.raises(PreflightError) as captured:
        transcription._resolve_model(
            backend=TranscriptionBackend.MLX_WHISPER,
            model="not-present",
            source=ModelSource.REGISTRY,
            download_policy="ask",
        )

    assert captured.value.code == "model_download_authorization_required"


def test_local_model_revision_changes_when_unlisted_weight_content_changes(
    tmp_path: Path,
) -> None:
    model = tmp_path / "model"
    model.mkdir()
    weight = model / "model.bin"
    weight.write_bytes(b"first")
    original = weight.stat()
    before = _model_revision(str(model))

    weight.write_bytes(b"other")
    os.utime(weight, ns=(original.st_atime_ns, original.st_mtime_ns))

    assert _model_revision(str(model)) != before


def test_multi_window_fft_sync_recovers_positive_offset() -> None:
    generator = np.random.default_rng(42)
    reference = generator.normal(size=6_000)
    target = np.zeros_like(reference)
    target[17:] = reference[:-17]

    estimate = estimate_sync(
        reference,
        target,
        envelope_hz=100,
        window_count=3,
        window_duration_us=20_000_000,
        max_offset_us=1_000_000,
    )

    assert estimate.offset_us == 170_000
    assert estimate.drift_us_per_hour == 0
    assert estimate.confidence > 0.95
    assert len(estimate.windows) == 3


def test_short_take_still_uses_distinct_beginning_middle_end_windows() -> None:
    centers = window_centers_us(5_000_000, window_count=3, window_duration_us=20_000_000)

    assert centers == (1_250_000, 2_500_000, 3_750_000)


def test_multi_window_sync_reports_clock_drift() -> None:
    generator = np.random.default_rng(7)
    reference = generator.normal(size=12_000)
    target_positions = np.arange(reference.size, dtype=np.float64)
    reference_positions = (target_positions - 12) / 1.002
    target = np.interp(reference_positions, target_positions, reference, left=0, right=0)

    estimate = estimate_sync(
        reference,
        target,
        envelope_hz=100,
        window_count=5,
        window_duration_us=20_000_000,
        max_offset_us=1_000_000,
    )

    assert estimate.offset_us == pytest.approx(120_000, abs=30_000)
    assert estimate.drift_ppm == pytest.approx(2_000, abs=300)
    assert estimate.drift_us_per_hour > 6_000_000
