from __future__ import annotations

import importlib.metadata
import importlib.util
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from interview_edit.config.models import (
    ModelSource,
    TranscriptionBackend,
    TranscriptionConfig,
)
from interview_edit.errors import DependencyError, PreflightError, ProcessingError, UsageError


@dataclass(frozen=True)
class BackendWord:
    start_seconds: float
    end_seconds: float
    text: str
    probability: float | None = None


@dataclass(frozen=True)
class BackendSegment:
    start_seconds: float
    end_seconds: float
    text: str
    words: tuple[BackendWord, ...] = ()


@dataclass(frozen=True)
class BackendTranscript:
    language: str
    segments: tuple[BackendSegment, ...]


class Transcriber(Protocol):
    backend: str
    backend_version: str
    requested_model: str
    resolved_model: str
    device: str

    def transcribe(self, audio_path: Path, *, language: str) -> BackendTranscript: ...


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _cached_snapshot(repo_id: str) -> Path | None:
    try:
        huggingface_hub = importlib.import_module("huggingface_hub")
    except ImportError:
        return None
    try:
        return Path(
            huggingface_hub.snapshot_download(repo_id=repo_id, local_files_only=True)
        ).resolve()
    except Exception:
        return None


def resolve_model(
    *,
    backend: TranscriptionBackend,
    model: str,
    source: ModelSource,
    download_policy: str,
    base_dir: Path | None = None,
) -> str:
    candidate = Path(model).expanduser()
    if source == ModelSource.LOCAL and not candidate.is_absolute() and base_dir is not None:
        candidate = base_dir / candidate
    if candidate.exists():
        if not candidate.is_dir():
            raise PreflightError(
                "transcription_model_not_directory",
                "The local transcription model must be a directory.",
                details={"path": str(candidate)},
            )
        return str(candidate.resolve())
    if source == ModelSource.LOCAL:
        raise PreflightError(
            "transcription_model_missing",
            "The configured local transcription model does not exist.",
            details={"path": str(candidate)},
        )
    if backend == TranscriptionBackend.MLX_WHISPER:
        repo_id = model if "/" in model else f"mlx-community/whisper-{model}"
    else:
        repo_id = model if "/" in model else f"Systran/faster-whisper-{model}"
    cached = _cached_snapshot(repo_id)
    if cached is not None:
        return str(cached)
    code = (
        "model_download_authorization_required"
        if download_policy == "ask"
        else "transcription_model_not_cached"
    )
    raise PreflightError(
        code,
        "The requested model is not available locally; no download was attempted.",
        details={"model": model, "repository": repo_id, "downloadPolicy": download_policy},
    )


def _word(raw: dict[str, Any]) -> BackendWord:
    probability = raw.get("probability")
    return BackendWord(
        start_seconds=float(raw.get("start", 0.0)),
        end_seconds=float(raw.get("end", raw.get("start", 0.0))),
        text=str(raw.get("word", raw.get("text", ""))),
        probability=float(probability) if probability is not None else None,
    )


class MlxWhisperTranscriber:
    backend = TranscriptionBackend.MLX_WHISPER.value

    def __init__(self, *, model: str, resolved_model: str, device: str) -> None:
        self.backend_version = _distribution_version("mlx-whisper")
        self.requested_model = model
        self.resolved_model = resolved_model
        self.device = device

    def transcribe(self, audio_path: Path, *, language: str) -> BackendTranscript:
        try:
            mlx_whisper = importlib.import_module("mlx_whisper")
        except Exception as exc:
            raise DependencyError(
                "mlx_whisper_unavailable",
                "MLX Whisper could not initialize in this execution environment.",
                details={"reason": str(exc)},
            ) from exc
        try:
            raw: dict[str, Any] = mlx_whisper.transcribe(
                str(audio_path),
                path_or_hf_repo=self.resolved_model,
                language=language,
                word_timestamps=True,
                condition_on_previous_text=False,
                verbose=None,
            )
        except Exception as exc:
            raise ProcessingError(
                "transcription_failed",
                "MLX Whisper failed to transcribe an audio chunk.",
                details={"path": str(audio_path), "reason": str(exc)},
            ) from exc
        segments = tuple(
            BackendSegment(
                start_seconds=float(segment.get("start", 0.0)),
                end_seconds=float(segment.get("end", segment.get("start", 0.0))),
                text=str(segment.get("text", "")),
                words=tuple(_word(word) for word in segment.get("words", [])),
            )
            for segment in raw.get("segments", [])
        )
        return BackendTranscript(language=str(raw.get("language", language)), segments=segments)


class FasterWhisperTranscriber:
    backend = TranscriptionBackend.FASTER_WHISPER.value

    def __init__(self, *, model: str, resolved_model: str, device: str) -> None:
        self.backend_version = _distribution_version("faster-whisper")
        self.requested_model = model
        self.resolved_model = resolved_model
        self.device = device

    def transcribe(self, audio_path: Path, *, language: str) -> BackendTranscript:
        try:
            faster_whisper = importlib.import_module("faster_whisper")
        except ImportError as exc:
            raise DependencyError(
                "faster_whisper_missing",
                "Faster-Whisper is not installed; install the faster-whisper extra explicitly.",
            ) from exc
        try:
            model = faster_whisper.WhisperModel(
                self.resolved_model,
                device=self.device,
                compute_type="auto",
            )
            segment_stream, info = model.transcribe(
                str(audio_path),
                language=language,
                word_timestamps=True,
                condition_on_previous_text=False,
                vad_filter=True,
            )
            segments = tuple(
                BackendSegment(
                    start_seconds=float(segment.start),
                    end_seconds=float(segment.end),
                    text=str(segment.text),
                    words=tuple(
                        BackendWord(
                            start_seconds=float(word.start),
                            end_seconds=float(word.end),
                            text=str(word.word),
                            probability=(
                                float(word.probability) if word.probability is not None else None
                            ),
                        )
                        for word in (segment.words or [])
                    ),
                )
                for segment in segment_stream
            )
        except Exception as exc:
            raise ProcessingError(
                "transcription_failed",
                "Faster-Whisper failed to transcribe an audio chunk.",
                details={"path": str(audio_path), "reason": str(exc)},
            ) from exc
        return BackendTranscript(language=str(info.language or language), segments=segments)


def create_transcriber(
    config: TranscriptionConfig,
    *,
    model: str | None = None,
    device: str | None = None,
    model_base: Path | None = None,
) -> Transcriber:
    requested_model = model or config.model
    requested_device = device or config.device
    if requested_device not in {"auto", "cpu", "cuda", "metal"}:
        raise UsageError(
            "transcription_device_invalid",
            "Transcription device must be auto, cpu, cuda, or metal.",
            details={"device": requested_device},
        )
    backend = config.backend
    if backend == TranscriptionBackend.AUTO:
        mlx_candidate = platform.system() == "Darwin" and platform.machine() == "arm64"
        if mlx_candidate and importlib.util.find_spec("mlx_whisper") is not None:
            backend = TranscriptionBackend.MLX_WHISPER
        elif importlib.util.find_spec("faster_whisper") is not None:
            backend = TranscriptionBackend.FASTER_WHISPER
        else:
            raise DependencyError(
                "transcription_backend_missing",
                "No supported local transcription backend is installed.",
            )
    if backend == TranscriptionBackend.MLX_WHISPER:
        if requested_device not in {"auto", "metal"}:
            raise UsageError(
                "transcription_device_incompatible",
                "MLX Whisper supports device auto or metal on Apple Silicon.",
                details={"device": requested_device},
            )
        if importlib.util.find_spec("mlx_whisper") is None:
            raise DependencyError("mlx_whisper_missing", "MLX Whisper is not installed.")
        resolved = resolve_model(
            backend=backend,
            model=requested_model,
            source=config.model_source,
            download_policy=config.download_policy,
            base_dir=model_base,
        )
        return MlxWhisperTranscriber(model=requested_model, resolved_model=resolved, device="metal")
    if requested_device == "metal":
        raise UsageError(
            "transcription_device_incompatible",
            "Faster-Whisper does not use the MLX metal device selector.",
            details={"device": requested_device},
        )
    if importlib.util.find_spec("faster_whisper") is None:
        raise DependencyError(
            "faster_whisper_missing",
            "Faster-Whisper is not installed; install the faster-whisper extra explicitly.",
        )
    resolved = resolve_model(
        backend=backend,
        model=requested_model,
        source=config.model_source,
        download_policy=config.download_policy,
        base_dir=model_base,
    )
    return FasterWhisperTranscriber(
        model=requested_model,
        resolved_model=resolved,
        device="auto" if requested_device == "auto" else requested_device,
    )
