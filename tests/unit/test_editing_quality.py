from __future__ import annotations

import pytest

from interview_edit.cutlist.captions import split_subtitle
from interview_edit.cutlist.editing import revise_item_range, speech_boundaries
from interview_edit.errors import PreflightError
from interview_edit.models.cutlist import CameraCut, Overlay, Subtitle, TimelineItem
from interview_edit.models.transcript import TranscriptWord

ASSET = "asset_0123456789abcdef01234567"


def item() -> TimelineItem:
    return TimelineItem(
        item_id="spoken",
        kind="primary",
        source_id=ASSET,
        source_in_us=1_000_000,
        source_out_us=5_000_000,
        timeline_duration_us=4_000_000,
        subtitles=[
            Subtitle(subtitle_id="s1", start_us=1_000_000, duration_us=1_000_000, text="不能删")
        ],
        camera_cuts=[
            CameraCut(cut_id="c1", camera_id="wide", start_us=500_000, duration_us=2_000_000)
        ],
        overlays=[
            Overlay(
                overlay_id="b1",
                kind="broll",
                start_us=0,
                duration_us=2_000_000,
                source_id=ASSET,
                source_in_us=6_000_000,
                source_out_us=8_000_000,
            )
        ],
    )


def test_range_change_preserves_source_anchored_children_and_original() -> None:
    original = item()
    changed = revise_item_range(original, 2_000_000, 4_000_000)
    assert changed.timeline_duration_us == 2_000_000
    assert changed.subtitles[0].start_us == 0
    assert changed.camera_cuts[0].start_us == 0
    assert changed.camera_cuts[0].duration_us == 1_500_000
    assert changed.overlays[0].source_in_us == 7_000_000
    assert changed.overlays[0].source_out_us == 8_000_000
    assert changed.overlays[0].duration_us == 1_000_000
    assert original.overlays[0].source_in_us == 6_000_000
    expanded = revise_item_range(original, 0, 6_000_000)
    assert expanded.subtitles[0].start_us == 2_000_000
    assert expanded.camera_cuts[0].start_us == 1_500_000


def test_range_change_does_not_keep_text_from_a_partially_removed_caption() -> None:
    with pytest.raises(PreflightError) as error:
        revise_item_range(item(), 2_500_000, 4_000_000)
    assert error.value.code == "subtitle_partial_trim"


def test_speech_boundary_inside_word_has_safe_suggestion_without_text() -> None:
    words = [TranscriptWord(text="private", start_us=900_000, end_us=1_100_000)]
    findings = speech_boundaries(item(), words)
    assert findings[0]["code"] == "speech_cut_inside_word"
    assert findings[0]["suggestedUs"] == 900_000
    assert "private" not in str(findings)
    assert speech_boundaries(item(), []) == []


def test_caption_split_preserves_chinese_numbers_and_negation() -> None:
    text = "预算为1.25万元，但是不能超支。接下来检查API输出。"
    original = Subtitle(subtitle_id="s1", start_us=100_000, duration_us=5_000_000, text=text)
    cues, estimated = split_subtitle(original, max_chars=10)
    assert "".join(cue.text for cue in cues) == text
    assert any("1.25万元" in cue.text for cue in cues)
    assert estimated
    assert cues[0].start_us == original.start_us
    assert cues[-1].end_us == original.end_us
    assert all(a.end_us == b.start_us for a, b in zip(cues, cues[1:], strict=False))


def test_caption_split_uses_matching_word_times() -> None:
    original = Subtitle(subtitle_id="s1", start_us=0, duration_us=2_000_000, text="保持完整。")
    words = [
        TranscriptWord(text="保持", start_us=1_100_000, end_us=1_400_000),
        TranscriptWord(text="完整。", start_us=1_700_000, end_us=2_300_000),
    ]
    cues, estimated = split_subtitle(original, words=words, source_in_us=1_000_000, max_chars=2)
    assert not estimated
    assert [(x.start_us, x.end_us) for x in cues] == [(100_000, 400_000), (700_000, 1_300_000)]
    assert "".join(x.text for x in cues) == original.text


def test_mismatched_correction_is_preserved_with_explicit_estimated_timing() -> None:
    original = Subtitle(subtitle_id="s1", start_us=0, duration_us=2_000_000, text="不能超支。")
    words = [TranscriptWord(text="可以超支", start_us=0, end_us=1_000_000)]
    cues, estimated = split_subtitle(original, words=words, max_chars=2)
    assert estimated
    assert "".join(x.text for x in cues) == original.text
