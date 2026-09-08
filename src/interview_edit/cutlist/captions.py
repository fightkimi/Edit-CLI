from __future__ import annotations

import re

from interview_edit.errors import PreflightError, UsageError
from interview_edit.models.cutlist import Subtitle
from interview_edit.models.transcript import TranscriptWord

_TOKENS = re.compile(r"[A-Za-z0-9]+(?:[.,:/_-][A-Za-z0-9]+)*(?:万元|亿元|美元|元|%|℃|秒)?|\s+|.")
_STOPS = frozenset("。！？!?；;，,")
_CLOSING = _STOPS | frozenset("、：:）)]】》’”")


def compact(text: str) -> str:
    return "".join(text.split())


def _chunks(text: str, max_chars: int) -> list[str]:
    if not 2 <= max_chars <= 80:
        raise UsageError("caption_width_invalid", "Caption length must be from 2 to 80 characters.")
    chunks: list[str] = []
    current = ""
    for token in _TOKENS.findall(text):
        if current and len(current + token) > max_chars and token not in _CLOSING:
            chunks.append(current)
            current = ""
        current += token
        if token in _STOPS:
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    return chunks


def split_subtitle(
    subtitle: Subtitle,
    *,
    max_chars: int = 18,
    words: list[TranscriptWord] | None = None,
    source_in_us: int = 0,
) -> tuple[list[Subtitle], bool]:
    """Preserve edited text; only use ASR times when the entire text agrees."""
    text = " ".join(subtitle.text.split())
    if not text:
        raise PreflightError("caption_text_empty", "A subtitle contains only whitespace.")
    chunks = _chunks(text, max_chars)
    selected = [
        word
        for word in (words or [])
        if word.start_us >= source_in_us + subtitle.start_us
        and word.end_us <= source_in_us + subtitle.end_us
        and compact(word.text)
    ]
    aligned = bool(selected) and compact("".join(w.text for w in selected)) == compact(text)
    aligned = aligned and all(w.end_us > w.start_us for w in selected)
    aligned = aligned and all(
        a.end_us <= b.start_us for a, b in zip(selected, selected[1:], strict=False)
    )
    spans: list[tuple[str, int, int]] = []
    if aligned:
        # Merge proposed chunks until their boundary coincides with a whole word.
        ends: dict[int, int] = {}
        length = 0
        for position, word in enumerate(selected):
            length += len(compact(word.text))
            ends[length] = position
        buffer = ""
        cursor = 0
        first = 0
        for chunk in chunks:
            buffer += chunk
            cursor += len(compact(chunk))
            if cursor not in ends:
                continue
            last = ends[cursor]
            spans.append(
                (
                    buffer,
                    selected[first].start_us - source_in_us,
                    selected[last].end_us - source_in_us,
                )
            )
            first = last + 1
            buffer = ""
    else:
        # Existing cue time is the only evidence: label proportional timing as estimated.
        cursor = 0
        for chunk in chunks:
            start = subtitle.start_us + subtitle.duration_us * cursor // len(text)
            cursor += len(chunk)
            end = subtitle.start_us + subtitle.duration_us * cursor // len(text)
            spans.append((chunk, start, end))
    if any(end <= start for _, start, end in spans):
        raise PreflightError("caption_duration_too_short", "Not enough cue time for this split.")
    return [
        Subtitle(
            subtitle_id=subtitle.subtitle_id
            if len(spans) == 1
            else f"{subtitle.subtitle_id}.{i + 1}",
            start_us=start,
            duration_us=end - start,
            text=chunk,
            font_path=subtitle.font_path,
        )
        for i, (chunk, start, end) in enumerate(spans)
    ], not aligned
