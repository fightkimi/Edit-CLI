from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from interview_edit.adapters import transcription
from interview_edit.config.models import ModelSource, TranscriptionBackend
from interview_edit.errors import DependencyError, PreflightError, ProcessingError, UsageError
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
        transcription.resolve_model(
            backend=TranscriptionBackend.MLX_WHISPER,
            model="not-present",
            source=ModelSource.REGISTRY,
            download_policy="ask",
        )

    assert captured.value.code == "model_download_authorization_required"


def test_local_model_path_resolves_from_explicit_project_base(tmp_path: Path) -> None:
    project = tmp_path / "project"
    model = project / "models" / "local-whisper"
    model.mkdir(parents=True)

    resolved = transcription.resolve_model(
        backend=TranscriptionBackend.MLX_WHISPER,
        model="models/local-whisper",
        source=ModelSource.LOCAL,
        download_policy="never",
        base_dir=project,
    )

    assert resolved == str(model.resolve())


def test_mlx_adapter_normalizes_backend_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = SimpleNamespace(
        transcribe=lambda *_args, **_kwargs: {
            "language": "zh",
            "segments": [
                {
                    "start": 0.25,
                    "end": 0.75,
                    "text": " 你好",
                    "words": [{"start": 0.25, "end": 0.5, "word": " 你", "probability": 0.9}],
                }
            ],
        }
    )
    monkeypatch.setattr(transcription.importlib, "import_module", lambda _name: fake_module)
    adapter = transcription.MlxWhisperTranscriber(
        model="tiny", resolved_model="/models/tiny", device="metal"
    )

    result = adapter.transcribe(Path("chunk.wav"), language="zh")

    assert result.language == "zh"
    assert result.segments[0].start_seconds == 0.25
    assert result.segments[0].words[0].text == " 你"
    assert result.segments[0].words[0].probability == 0.9


def test_mlx_adapter_classifies_initialization_and_runtime_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = transcription.MlxWhisperTranscriber(
        model="tiny", resolved_model="/models/tiny", device="metal"
    )
    monkeypatch.setattr(
        transcription.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("missing runtime")),
    )
    with pytest.raises(DependencyError) as missing:
        adapter.transcribe(Path("chunk.wav"), language="zh")
    assert missing.value.code == "mlx_whisper_unavailable"

    monkeypatch.setattr(
        transcription.importlib,
        "import_module",
        lambda _name: SimpleNamespace(
            transcribe=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("metal failed"))
        ),
    )
    with pytest.raises(ProcessingError) as failed:
        adapter.transcribe(Path("chunk.wav"), language="zh")
    assert failed.value.code == "transcription_failed"


def test_faster_whisper_adapter_normalizes_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    segment = SimpleNamespace(
        start=0.0,
        end=1.0,
        text="hello",
        words=[SimpleNamespace(start=0.0, end=0.5, word="hello", probability=None)],
    )

    class FakeModel:
        def __init__(self, model: str, *, device: str, compute_type: str) -> None:
            assert (model, device, compute_type) == ("/models/base", "cpu", "auto")

        def transcribe(self, *_args: object, **_kwargs: object) -> tuple[object, object]:
            return iter([segment]), SimpleNamespace(language="en")

    monkeypatch.setattr(
        transcription.importlib,
        "import_module",
        lambda _name: SimpleNamespace(WhisperModel=FakeModel),
    )
    adapter = transcription.FasterWhisperTranscriber(
        model="base", resolved_model="/models/base", device="cpu"
    )

    result = adapter.transcribe(Path("chunk.wav"), language="auto")

    assert result.language == "en"
    assert result.segments[0].text == "hello"
    assert result.segments[0].words[0].probability is None


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
