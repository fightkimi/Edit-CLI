from types import SimpleNamespace

from interview_edit.cutlist.audio import edge_fades
from interview_edit.models.cutlist import TimelineItem


def item(identifier, start, end):
    return TimelineItem(
        item_id=identifier,
        kind="primary",
        source_id="asset_" + "a" * 24,
        source_in_us=start,
        source_out_us=end,
        timeline_duration_us=end - start,
    )


def index():
    return SimpleNamespace(
        assets=[SimpleNamespace(asset_id="asset_" + "a" * 24, audio_streams=[1])]
    )


def test_continuous_audio_is_not_faded_at_an_item_or_camera_join():
    items = [item("a", 0, 500_000), item("b", 500_000, 1_000_000)]
    assert edge_fades(None, index(), items, 5_000) == [(5_000, 0), (0, 5_000)]


def test_removed_pause_creates_two_smoothed_edges():
    items = [item("a", 0, 500_000), item("b", 700_000, 1_000_000)]
    assert edge_fades(None, index(), items, 5_000) == [(5_000, 5_000), (5_000, 5_000)]


def test_short_clips_keep_an_unfaded_middle_and_disabled_policy_is_exact():
    items = [item("a", 0, 8_000)]
    assert edge_fades(None, index(), items, 30_000) == [(2_000, 2_000)]
    assert edge_fades(None, index(), items, 0) == [(0, 0)]
