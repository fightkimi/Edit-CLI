from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from interview_edit.adapters.filesystem import full_sha256, quick_fingerprint
from interview_edit.adapters.media import parse_probe_payload
from interview_edit.errors import PathSafetyError
from interview_edit.ingest.service import compute_asset_id
from interview_edit.models.media import CameraMapRule
from interview_edit.project.layout import artifact_path


def test_asset_id_is_stable_for_normalized_relative_path(tmp_path: Path) -> None:
    root = tmp_path / "素材"
    composed = Path("访谈") / "café 01.mov"
    decomposed = Path("访谈") / "cafe\u0301 01.mov"

    assert compute_asset_id(root, composed) == compute_asset_id(root, decomposed)
    assert compute_asset_id(root, composed).startswith("asset_")


def test_quick_fingerprint_changes_when_source_revision_changes(tmp_path: Path) -> None:
    source = tmp_path / "large-ish.mov"
    source.write_bytes(b"a" * 900_000)
    first = quick_fingerprint(source)

    source.write_bytes(b"a" * 450_000 + b"b" + b"a" * 449_999)
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    assert quick_fingerprint(source) != first


def test_full_hash_detects_change_outside_fast_samples(tmp_path: Path) -> None:
    source = tmp_path / "sampled.mov"
    source.write_bytes(b"a" * (2 * 1024 * 1024))
    original_stat = source.stat()
    fast_before = quick_fingerprint(source)
    full_before = full_sha256(source)

    with source.open("r+b") as handle:
        handle.seek(600_000)
        handle.write(b"b")
    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    assert quick_fingerprint(source) == fast_before
    assert full_sha256(source) != full_before


@pytest.mark.parametrize(
    "field,value",
    [
        ("take_id", "../outside"),
        ("take_id", "/absolute"),
        ("camera_id", "nested/camera"),
        ("camera_id", ".."),
    ],
)
def test_camera_map_rejects_path_bearing_identifiers(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        CameraMapRule(glob="*.mp4", **{field: value})


def test_artifact_path_rejects_existing_symlink_component(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    artifact_root.mkdir()
    outside.mkdir()
    (artifact_root / "renders").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathSafetyError) as captured:
        artifact_path(artifact_root, "renders", "output.mp4")

    assert captured.value.code == "artifact_path_unsafe"


def test_ffprobe_parser_persists_integer_microseconds_and_stream_time_bases() -> None:
    payload = {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "pix_fmt": "yuv420p",
                "color_range": "tv",
                "color_space": "bt709",
                "color_transfer": "bt709",
                "color_primaries": "bt709",
                "field_order": "progressive",
                "time_base": "1/90000",
                "avg_frame_rate": "30000/1001",
                "r_frame_rate": "30000/1001",
                "start_time": "0.033367",
                "duration": "1.001000",
                "side_data_list": [{"rotation": -90}],
                "tags": {"creation_time": "2026-09-03T00:00:00.000000Z"},
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
                "channel_layout": "stereo",
                "time_base": "1/48000",
                "start_time": "0.000000",
                "duration": "1.024000",
            },
        ],
        "format": {"duration": "1.024000", "start_time": "0.000000", "tags": {}},
    }

    parsed = parse_probe_payload(json.dumps(payload))

    assert parsed.duration_us == 1_024_000
    assert parsed.start_time_us == 0
    assert parsed.stream_time_base == "1/90000"
    assert parsed.video_stream is not None
    assert parsed.video_stream.duration_us == 1_001_000
    assert parsed.video_stream.rotation == -90
    assert parsed.video_stream.color_range == "tv"
    assert parsed.video_stream.color_space == "bt709"
    assert parsed.video_stream.field_order == "progressive"
    assert parsed.audio_streams[0].time_base == "1/48000"
    assert parsed.capture_time == "2026-09-03T00:00:00.000000Z"
