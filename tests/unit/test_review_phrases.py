from interview_edit.models.transcript import TranscriptSegment, TranscriptWord
from interview_edit.review.phrases import group_phrases


def test_phrase_view_preserves_words_and_source_time_across_a_pause():
    asset = "asset_" + "a" * 24
    segment = TranscriptSegment(
        segment_id="seg_00000001",
        asset_id=asset,
        start_us=0,
        end_us=1_000_000,
        text="预算1.25万元，继续。",
        words=[
            TranscriptWord(start_us=0, end_us=100_000, text="预算"),
            TranscriptWord(start_us=100_000, end_us=200_000, text="1.25万元，"),
            TranscriptWord(start_us=800_000, end_us=1_000_000, text="继续。"),
        ],
    )
    phrases = group_phrases(asset, [segment], 500_000)
    assert [p.start_us for p in phrases] == [0, 800_000]
    assert "".join(p.text for p in phrases) == segment.text
    assert [w for p in phrases for w in p.words] == segment.words
    assert all(p.speaker == "unknown" for p in phrases)


def test_corrected_text_mismatch_is_not_misrepresented_as_word_aligned():
    asset = "asset_" + "a" * 24
    segment = TranscriptSegment(
        segment_id="seg_00000001",
        asset_id=asset,
        start_us=0,
        end_us=200_000,
        text="修改后的文字",
        words=[TranscriptWord(start_us=0, end_us=200_000, text="原文")],
    )
    phrase = group_phrases(asset, [segment], 500_000)[0]
    assert phrase.text == segment.text and phrase.timing == "segment" and not phrase.words
