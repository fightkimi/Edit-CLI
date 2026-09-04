from __future__ import annotations

import wave
from pathlib import Path

from interview_edit.adapters.transcription import (
    BackendSegment,
    BackendTranscript,
    BackendWord,
)


class MockTranscriber:
    backend = "mock"
    backend_version = "1"
    resolved_model = "mock:deterministic"
    device = "cpu"

    def __init__(self, *, model: str = "mock") -> None:
        self.requested_model = model

    def transcribe(self, audio_path: Path, *, language: str) -> BackendTranscript:
        with wave.open(str(audio_path), "rb") as handle:
            duration = handle.getnframes() / handle.getframerate()
        if duration <= 0:
            return BackendTranscript(language=language, segments=())
        end = min(duration, 2.0)
        word = BackendWord(0.0, end, "[mock transcript]", 1.0)
        segment = BackendSegment(0.0, end, "[mock transcript]", (word,))
        return BackendTranscript(language=language, segments=(segment,))
