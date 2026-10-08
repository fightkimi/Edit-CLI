from __future__ import annotations

from interview_edit.config.models import ProjectConfig
from interview_edit.cutlist.timing import map_source_range
from interview_edit.models.cutlist import TimelineItem
from interview_edit.models.media import MediaIndex


def audio_range(
    config: ProjectConfig, index: MediaIndex, item: TimelineItem
) -> tuple[str, int, int] | None:
    assets = {a.asset_id: a for a in index.assets}
    source = assets.get(item.source_id or "")
    audio = assets.get(item.audio_source or item.source_id or "")
    if source is None or audio is None or not audio.audio_streams or item.source_in_us is None:
        return None
    start, length = map_source_range(
        config=config,
        index=index,
        source=source,
        target=audio,
        start_us=item.source_in_us,
        duration_us=item.timeline_duration_us,
    )
    return audio.asset_id, start, length


def edge_fades(
    config: ProjectConfig, index: MediaIndex, items: list[TimelineItem], requested_us: int
) -> list[tuple[int, int]]:
    """Only smooth actual discontinuities; visual camera edits do not interrupt the audio clock."""
    if not requested_us:
        return [(0, 0) for _ in items]
    ranges = [audio_range(config, index, item) for item in items]
    result = []
    for i, item in enumerate(items):
        current = ranges[i]
        limit = min(requested_us, item.timeline_duration_us // 4)
        if current is None:
            result.append((0, 0))
            continue
        previous = ranges[i - 1] if i else None
        following = ranges[i + 1] if i + 1 < len(items) else None
        continuous_in = (
            previous is not None
            and previous[0] == current[0]
            and previous[1] + previous[2] == current[1]
        )
        continuous_out = (
            following is not None
            and following[0] == current[0]
            and current[1] + current[2] == following[1]
        )
        result.append((0 if continuous_in else limit, 0 if continuous_out else limit))
    return result
