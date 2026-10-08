from __future__ import annotations

from interview_edit.cutlist.captions import compact
from interview_edit.models.review import Phrase
from interview_edit.models.transcript import TranscriptSegment


def group_phrases(asset_id: str, segments: list[TranscriptSegment], pause_us: int) -> list[Phrase]:
    result: list[Phrase] = []
    for segment in segments:
        words = segment.words
        aligned = bool(words) and compact("".join(w.text for w in words)) == compact(segment.text)
        aligned = aligned and all(w.end_us > w.start_us for w in words)
        aligned = aligned and all(
            a.end_us <= b.start_us for a, b in zip(words, words[1:], strict=False)
        )
        if not aligned:
            if segment.end_us > segment.start_us:
                result.append(
                    Phrase(
                        asset_id=asset_id,
                        start_us=segment.start_us,
                        end_us=segment.end_us,
                        text=segment.text,
                        timing="segment",
                    )
                )
            continue
        # Preserve edited punctuation and spacing; speaker labels remain unknown.
        consumed = 0
        first = 0
        text_start = 0
        compact_count = 0
        ends = {}
        for position, char in enumerate(segment.text):
            compact_count += bool(compact(char))
            ends[compact_count] = position + 1
        for position, word in enumerate(words):
            consumed += len(compact(word.text))
            last = position == len(words) - 1
            if last or words[position + 1].start_us - word.end_us >= pause_us:
                stop = len(segment.text) if last else ends[consumed]
                result.append(
                    Phrase(
                        asset_id=asset_id,
                        start_us=words[first].start_us,
                        end_us=word.end_us,
                        text=segment.text[text_start:stop],
                        words=words[first : position + 1],
                        timing="words",
                    )
                )
                first = position + 1
                text_start = stop
    return result
