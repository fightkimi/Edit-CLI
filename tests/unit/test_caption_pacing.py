from interview_edit.cutlist.captions import split_subtitle
from interview_edit.models.cutlist import Subtitle
from interview_edit.models.transcript import TranscriptWord


def words():
    return [
        TranscriptWord(start_us=0, end_us=100_000, text="甲"),
        TranscriptWord(start_us=110_000, end_us=200_000, text="乙"),
        TranscriptWord(start_us=800_000, end_us=1_000_000, text="丙"),
    ]


def test_pause_breaks_a_cue_even_when_it_fits_the_character_limit():
    cue = Subtitle(subtitle_id="s", start_us=0, duration_us=1_000_000, text="甲乙丙")
    parts, estimated = split_subtitle(cue, words=words(), pause_us=300_000, min_duration_us=350_000)
    assert not estimated
    assert [p.text for p in parts] == ["甲乙", "丙"]
    assert [(p.start_us, p.end_us) for p in parts] == [(0, 350_000), (800_000, 1_000_000)]
    assert "".join(p.text for p in parts) == cue.text


def test_tiny_cues_merge_without_crossing_a_pause_or_exceeding_bounds():
    cue = Subtitle(subtitle_id="s", start_us=0, duration_us=400_000, text="甲乙丙丁")
    words = [
        TranscriptWord(start_us=i * 100_000, end_us=(i + 1) * 100_000, text=t)
        for i, t in enumerate(cue.text)
    ]
    parts, _ = split_subtitle(
        cue, words=words, max_chars=4, min_duration_us=350_000, pause_us=300_000
    )
    assert len(parts) == 1 and parts[0].end_us <= cue.end_us


def test_estimated_timing_never_claims_pause_evidence():
    cue = Subtitle(subtitle_id="s", start_us=0, duration_us=300_000, text="一二三四五六")
    parts, estimated = split_subtitle(cue, max_chars=2, min_duration_us=350_000, pause_us=300_000)
    assert estimated
    assert "".join(p.text for p in parts) == cue.text
    assert all(0 <= p.start_us < p.end_us <= cue.end_us for p in parts)
