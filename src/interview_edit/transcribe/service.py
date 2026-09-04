from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import wave
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from interview_edit.adapters.artifacts import validated_audio_proxy
from interview_edit.adapters.filesystem import sha256_file
from interview_edit.adapters.process import ProcessRunner, SubprocessRunner
from interview_edit.adapters.transcription import Transcriber, create_transcriber
from interview_edit.config.models import ProjectConfig
from interview_edit.errors import DependencyError, PreflightError, ProcessingError, UsageError
from interview_edit.models.media import MediaAsset, MediaIndex
from interview_edit.models.transcript import (
    CorrectionDictionary,
    CorrectionRule,
    TranscriptChunk,
    TranscriptManifest,
    TranscriptOutput,
    TranscriptSegment,
    TranscriptWord,
)
from interview_edit.project.layout import atomic_write_text
from interview_edit.proxy.service import validate_source_revision

_TRANSCRIPTION_SCHEMA = "transcription-v1"


@dataclass(frozen=True)
class TranscribeRequest:
    config: ProjectConfig
    project_root: Path
    index: MediaIndex
    asset_ids: list[str] | None = None
    take_id: str | None = None
    language: str | None = None
    model: str | None = None
    device: str | None = None
    resume: bool = False
    force: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class TranscribeResult:
    built: list[str]
    cached: list[str]
    corrected: list[str]
    planned: list[str]
    artifacts: list[Path]
    resumed_chunks: int
    dry_run: bool


@dataclass(frozen=True)
class _TranscriptPaths:
    root: Path
    raw_jsonl: Path
    corrected_jsonl: Path
    raw_srt: Path
    corrected_srt: Path
    manifest: Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _paths(config: ProjectConfig, asset_id: str) -> _TranscriptPaths:
    root = config.artifact_root / "transcripts" / asset_id
    return _TranscriptPaths(
        root=root,
        raw_jsonl=root / "raw.jsonl",
        corrected_jsonl=root / "corrected.jsonl",
        raw_srt=root / "raw.srt",
        corrected_srt=root / "corrected.srt",
        manifest=root / "manifest.json",
    )


def _select_assets(request: TranscribeRequest) -> list[MediaAsset]:
    if request.asset_ids and request.take_id:
        raise UsageError(
            "transcription_selection_conflict",
            "Use either --asset or --take, not both.",
        )
    indexed = {asset.asset_id: asset for asset in request.index.assets}
    if request.asset_ids:
        unknown = sorted(set(request.asset_ids) - set(indexed))
        if unknown:
            raise UsageError(
                "asset_unknown",
                "One or more requested assets are not present in the media index.",
                details={"assetIds": unknown},
            )
        selected = [indexed[asset_id] for asset_id in sorted(set(request.asset_ids))]
        without_audio = [asset.asset_id for asset in selected if not asset.audio_streams]
        if without_audio:
            raise PreflightError(
                "asset_audio_missing",
                "One or more requested assets have no indexed audio stream.",
                details={"assetIds": without_audio},
            )
        return selected
    if request.take_id is not None:
        take_assets = [asset for asset in request.index.assets if asset.take_id == request.take_id]
        if not take_assets:
            raise UsageError(
                "take_unknown",
                "The requested take is not present in the media index.",
                details={"takeId": request.take_id},
            )
        selected = [asset for asset in take_assets if asset.audio_streams]
        if not selected:
            raise PreflightError(
                "take_audio_missing",
                "The requested take has no indexed audio streams.",
                details={"takeId": request.take_id},
            )
        return sorted(selected, key=lambda item: item.asset_id)
    return sorted(
        (asset for asset in request.index.assets if asset.audio_streams),
        key=lambda item: item.asset_id,
    )


def _load_corrections(project_root: Path) -> tuple[CorrectionDictionary, str]:
    path = project_root / "dictionaries" / "corrections.yaml"
    if not path.exists():
        digest = hashlib.sha256(b"").hexdigest()
        return CorrectionDictionary(), f"sha256:{digest}"
    try:
        raw = path.read_bytes()
        payload = yaml.safe_load(raw.decode("utf-8"))
        dictionary = CorrectionDictionary.model_validate(payload or {})
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as exc:
        raise UsageError(
            "correction_dictionary_invalid",
            "The project correction dictionary is invalid.",
            details={"path": str(path), "reason": str(exc)},
        ) from exc
    return dictionary, f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _audio_duration_us(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
    except (OSError, wave.Error) as exc:
        raise PreflightError(
            "audio_proxy_unreadable",
            "The normalized WAV audio proxy could not be read.",
            details={"path": str(path), "reason": str(exc)},
        ) from exc
    if rate <= 0:
        raise PreflightError(
            "audio_proxy_invalid",
            "The normalized WAV audio proxy has an invalid sample rate.",
            details={"path": str(path)},
        )
    return (frames * 1_000_000) // rate


def _model_revision(resolved_model: str) -> dict[str, Any]:
    path = Path(resolved_model)
    if not path.is_dir():
        return {"identity": resolved_model}
    revision: list[dict[str, Any]] = []
    for name in ("config.json", "weights.safetensors", "weights.npz"):
        candidate = path / name
        if candidate.is_file():
            stat = candidate.stat()
            revision.append({"name": name, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return {"path": str(path), "files": revision}


def _cache_key(
    asset: MediaAsset,
    *,
    audio_sha256: str,
    transcriber: Transcriber,
    language: str,
    chunk_duration_seconds: int,
) -> tuple[str, dict[str, Any]]:
    parameters = {
        "chunk_duration_seconds": chunk_duration_seconds,
        "condition_on_previous_text": False,
        "word_timestamps": True,
    }
    payload = {
        "schema": _TRANSCRIPTION_SCHEMA,
        "asset_id": asset.asset_id,
        "source_fingerprint": asset.fingerprint,
        "source_full_hash": asset.full_hash,
        "audio_proxy_sha256": audio_sha256,
        "backend": transcriber.backend,
        "backend_version": transcriber.backend_version,
        "model": transcriber.requested_model,
        "model_revision": _model_revision(transcriber.resolved_model),
        "device": transcriber.device,
        "language": language,
        "parameters": parameters,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), parameters


def _to_us(seconds: float) -> int:
    return int(
        (Decimal(str(seconds)) * Decimal(1_000_000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def _checkpoint_path(project_root: Path, asset_id: str, cache_key: str, chunk_index: int) -> Path:
    return (
        project_root
        / ".interview-edit"
        / "cache"
        / "transcribe"
        / asset_id
        / cache_key
        / f"chunk-{chunk_index:05d}.json"
    )


def _read_checkpoint(
    path: Path,
    *,
    asset_id: str,
    cache_key: str,
    chunk_index: int,
    start_us: int,
    end_us: int,
) -> TranscriptChunk | None:
    try:
        checkpoint = TranscriptChunk.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError):
        return None
    if (
        checkpoint.asset_id != asset_id
        or checkpoint.transcription_cache_key != cache_key
        or checkpoint.chunk_index != chunk_index
        or checkpoint.start_us != start_us
        or checkpoint.end_us != end_us
    ):
        return None
    return checkpoint


def _extract_chunk(
    source: Path,
    destination: Path,
    *,
    start_us: int,
    duration_us: int,
    runner: ProcessRunner,
) -> None:
    result = runner.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{start_us / 1_000_000:.6f}",
            "-i",
            str(source),
            "-t",
            f"{duration_us / 1_000_000:.6f}",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ],
        timeout_seconds=60 * 60,
    )
    if result.return_code == 127:
        raise DependencyError("ffmpeg_missing", "Required executable is unavailable: ffmpeg.")
    if result.return_code != 0:
        raise ProcessingError(
            "transcription_chunk_extract_failed",
            "FFmpeg could not prepare a bounded audio chunk for local transcription.",
            details={
                "path": str(source),
                "returnCode": result.return_code,
                "stderr": result.stderr[-4000:],
            },
        )


def _transcribe_chunk(
    *,
    asset: MediaAsset,
    audio_path: Path,
    cache_key: str,
    chunk_index: int,
    start_us: int,
    end_us: int,
    language: str,
    transcriber: Transcriber,
    runner: ProcessRunner,
) -> TranscriptChunk:
    temporary_name: str | None = None
    input_path = audio_path
    try:
        if start_us > 0 or end_us < _audio_duration_us(audio_path):
            cache_dir = audio_path.parent
            cache_dir.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{asset.asset_id}-{chunk_index:05d}-", suffix=".wav", dir=cache_dir
            )
            os.close(descriptor)
            Path(temporary_name).unlink(missing_ok=True)
            input_path = Path(temporary_name)
            _extract_chunk(
                audio_path,
                input_path,
                start_us=start_us,
                duration_us=end_us - start_us,
                runner=runner,
            )
        raw = transcriber.transcribe(input_path, language=language)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)

    segments: list[TranscriptSegment] = []
    for position, segment in enumerate(raw.segments, start=1):
        text = segment.text.strip()
        if not text:
            continue
        segment_start = max(start_us, min(end_us, start_us + _to_us(segment.start_seconds)))
        segment_end = max(segment_start, min(end_us, start_us + _to_us(segment.end_seconds)))
        words = [
            TranscriptWord(
                start_us=max(
                    segment_start,
                    min(segment_end, start_us + _to_us(word.start_seconds)),
                ),
                end_us=max(
                    segment_start,
                    min(segment_end, start_us + _to_us(word.end_seconds)),
                ),
                text=word.text,
                probability=word.probability,
            )
            for word in segment.words
        ]
        words = [
            word.model_copy(update={"end_us": max(word.start_us, word.end_us)}) for word in words
        ]
        segments.append(
            TranscriptSegment(
                segment_id=f"seg_{chunk_index * 100_000 + position:08d}",
                asset_id=asset.asset_id,
                start_us=segment_start,
                end_us=segment_end,
                text=text,
                words=words,
            )
        )
    return TranscriptChunk(
        asset_id=asset.asset_id,
        transcription_cache_key=cache_key,
        chunk_index=chunk_index,
        start_us=start_us,
        end_us=end_us,
        detected_language=raw.language,
        segments=segments,
    )


def _apply_rules(
    segments: list[TranscriptSegment], rules: list[CorrectionRule]
) -> list[TranscriptSegment]:
    corrected: list[TranscriptSegment] = []
    enabled = [rule for rule in rules if rule.enabled]
    for segment in segments:
        text = segment.text
        words = [word.model_copy() for word in segment.words]
        applied: list[str] = []
        for rule in enabled:
            changed = rule.find in text or any(rule.find in word.text for word in words)
            if not changed:
                continue
            text = text.replace(rule.find, rule.replace)
            words = [
                word.model_copy(update={"text": word.text.replace(rule.find, rule.replace)})
                for word in words
            ]
            applied.append(rule.id)
        corrected.append(
            segment.model_copy(
                update={"text": text, "words": words, "correction_rule_ids": applied}
            )
        )
    return corrected


def _jsonl(segments: list[TranscriptSegment], *, corrected: bool) -> str:
    lines = []
    for segment in segments:
        payload = segment.model_dump(mode="json")
        if not corrected:
            payload.pop("correction_rule_ids", None)
        lines.append(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return "\n".join(lines) + ("\n" if lines else "")


def _srt_timestamp(time_us: int) -> str:
    milliseconds = max(0, time_us) // 1000
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _srt(segments: list[TranscriptSegment]) -> str:
    entries = [
        f"{position}\n{_srt_timestamp(segment.start_us)} --> "
        f"{_srt_timestamp(segment.end_us)}\n{segment.text}\n"
        for position, segment in enumerate(segments, start=1)
    ]
    return "\n".join(entries)


def _output(
    kind: Literal["raw_jsonl", "corrected_jsonl", "raw_srt", "corrected_srt"],
    path: Path,
) -> TranscriptOutput:
    return TranscriptOutput(
        kind=kind, path=str(path), size=path.stat().st_size, sha256=sha256_file(path)
    )


def _read_manifest(path: Path, cache_key: str) -> TranscriptManifest | None:
    try:
        manifest = TranscriptManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError):
        return None
    if manifest.transcription_cache_key != cache_key:
        return None
    for output in manifest.outputs:
        candidate = Path(output.path)
        try:
            if (
                not candidate.is_file()
                or candidate.stat().st_size != output.size
                or sha256_file(candidate) != output.sha256
            ):
                return None
        except OSError:
            return None
    return manifest


def _read_raw(path: Path) -> list[TranscriptSegment]:
    try:
        return [
            TranscriptSegment.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, ValidationError) as exc:
        raise PreflightError(
            "transcript_raw_invalid",
            "The cached raw transcript is invalid.",
            details={"path": str(path), "reason": str(exc)},
        ) from exc


def _write_derivatives(
    *,
    paths: _TranscriptPaths,
    asset: MediaAsset,
    audio_sha256: str,
    cache_key: str,
    transcriber: Transcriber,
    language: str,
    parameters: dict[str, Any],
    corrections: CorrectionDictionary,
    correction_fingerprint: str,
    raw_segments: list[TranscriptSegment],
    write_raw: bool = True,
) -> TranscriptManifest:
    normalized_raw = [
        segment.model_copy(update={"segment_id": f"seg_{position:08d}"})
        for position, segment in enumerate(raw_segments, start=1)
    ]
    corrected = _apply_rules(normalized_raw, corrections.rules)
    if write_raw:
        atomic_write_text(paths.raw_jsonl, _jsonl(normalized_raw, corrected=False))
        atomic_write_text(paths.raw_srt, _srt(normalized_raw))
    atomic_write_text(paths.corrected_jsonl, _jsonl(corrected, corrected=True))
    atomic_write_text(paths.corrected_srt, _srt(corrected))
    outputs = [
        _output("raw_jsonl", paths.raw_jsonl),
        _output("corrected_jsonl", paths.corrected_jsonl),
        _output("raw_srt", paths.raw_srt),
        _output("corrected_srt", paths.corrected_srt),
    ]
    manifest = TranscriptManifest(
        asset_id=asset.asset_id,
        source_fingerprint=asset.fingerprint,
        source_full_hash=asset.full_hash,
        audio_proxy_sha256=audio_sha256,
        transcription_cache_key=cache_key,
        backend=transcriber.backend,
        backend_version=transcriber.backend_version,
        model=transcriber.requested_model,
        resolved_model=transcriber.resolved_model,
        device=transcriber.device,
        language=language,
        parameters=parameters,
        correction_fingerprint=correction_fingerprint,
        segment_count=len(normalized_raw),
        word_count=sum(len(segment.words) for segment in normalized_raw),
        outputs=outputs,
        completed_at=_utc_now(),
    )
    atomic_write_text(
        paths.manifest,
        manifest.model_dump_json(indent=2) + "\n",
    )
    return manifest


def transcribe_assets(
    request: TranscribeRequest,
    *,
    runner: ProcessRunner | None = None,
    transcriber: Transcriber | None = None,
    progress: Callable[[str], None] | None = None,
) -> TranscribeResult:
    selected = _select_assets(request)
    if not selected:
        raise PreflightError("transcription_audio_missing", "No indexed assets contain audio.")
    language = request.language or request.config.transcription.language or request.config.language
    corrections, correction_fingerprint = _load_corrections(request.project_root)
    selected_runner = runner or SubprocessRunner()
    selected_transcriber = transcriber
    if selected_transcriber is None and not request.dry_run:
        selected_transcriber = create_transcriber(
            request.config.transcription,
            model=request.model,
            device=request.device,
        )

    built: list[str] = []
    cached: list[str] = []
    corrected_only: list[str] = []
    planned: list[str] = []
    artifacts: list[Path] = []
    resumed_chunks = 0
    for position, asset in enumerate(selected, start=1):
        validate_source_revision(asset)
        audio = validated_audio_proxy(request.config, asset)
        if request.dry_run:
            planned.append(asset.asset_id)
            continue
        assert selected_transcriber is not None
        cache_key, parameters = _cache_key(
            asset,
            audio_sha256=audio.sha256,
            transcriber=selected_transcriber,
            language=language,
            chunk_duration_seconds=request.config.transcription.chunk_duration_seconds,
        )
        paths = _paths(request.config, asset.asset_id)
        manifest = None if request.force else _read_manifest(paths.manifest, cache_key)
        if manifest is not None and manifest.correction_fingerprint == correction_fingerprint:
            cached.append(asset.asset_id)
            artifacts.extend([*(Path(output.path) for output in manifest.outputs), paths.manifest])
            if progress is not None:
                progress(
                    f"[{position}/{len(selected)}] transcript cache hit: {asset.relative_path}"
                )
            continue
        if manifest is not None:
            raw_segments = _read_raw(paths.raw_jsonl)
            _write_derivatives(
                paths=paths,
                asset=asset,
                audio_sha256=audio.sha256,
                cache_key=cache_key,
                transcriber=selected_transcriber,
                language=language,
                parameters=parameters,
                corrections=corrections,
                correction_fingerprint=correction_fingerprint,
                raw_segments=raw_segments,
                write_raw=False,
            )
            corrected_only.append(asset.asset_id)
            artifacts.extend(
                [
                    paths.raw_jsonl,
                    paths.corrected_jsonl,
                    paths.raw_srt,
                    paths.corrected_srt,
                    paths.manifest,
                ]
            )
            continue

        duration_us = _audio_duration_us(audio.path)
        chunk_us = request.config.transcription.chunk_duration_seconds * 1_000_000
        chunk_count = max(1, math.ceil(duration_us / chunk_us))
        all_segments: list[TranscriptSegment] = []
        if progress is not None:
            progress(
                f"[{position}/{len(selected)}] transcribing {asset.relative_path} "
                f"in {chunk_count} chunk(s)..."
            )
        for chunk_index in range(chunk_count):
            start_us = chunk_index * chunk_us
            end_us = min(duration_us, (chunk_index + 1) * chunk_us)
            checkpoint_path = _checkpoint_path(
                request.project_root, asset.asset_id, cache_key, chunk_index
            )
            checkpoint = None
            if request.resume and not request.force:
                checkpoint = _read_checkpoint(
                    checkpoint_path,
                    asset_id=asset.asset_id,
                    cache_key=cache_key,
                    chunk_index=chunk_index,
                    start_us=start_us,
                    end_us=end_us,
                )
            if checkpoint is not None:
                resumed_chunks += 1
            else:
                checkpoint = _transcribe_chunk(
                    asset=asset,
                    audio_path=audio.path,
                    cache_key=cache_key,
                    chunk_index=chunk_index,
                    start_us=start_us,
                    end_us=end_us,
                    language=language,
                    transcriber=selected_transcriber,
                    runner=selected_runner,
                )
                atomic_write_text(
                    checkpoint_path,
                    checkpoint.model_dump_json(indent=2) + "\n",
                )
            all_segments.extend(checkpoint.segments)
        _write_derivatives(
            paths=paths,
            asset=asset,
            audio_sha256=audio.sha256,
            cache_key=cache_key,
            transcriber=selected_transcriber,
            language=language,
            parameters=parameters,
            corrections=corrections,
            correction_fingerprint=correction_fingerprint,
            raw_segments=all_segments,
        )
        built.append(asset.asset_id)
        artifacts.extend(
            [
                paths.raw_jsonl,
                paths.corrected_jsonl,
                paths.raw_srt,
                paths.corrected_srt,
                paths.manifest,
            ]
        )
    return TranscribeResult(
        built=built,
        cached=cached,
        corrected=corrected_only,
        planned=planned,
        artifacts=artifacts,
        resumed_chunks=resumed_chunks,
        dry_run=request.dry_run,
    )
