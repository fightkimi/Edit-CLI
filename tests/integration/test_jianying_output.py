from __future__ import annotations

import pytest

from interview_edit.cutlist.service import serialize_cutlist
from interview_edit.errors import PreflightError
from interview_edit.export.jianying import export_jianying
from interview_edit.export.jianying_output import check_output
from tests.fixtures.media_factory import make_video
from tests.integration.test_jianying_integrity import setup as base_setup


def setup(tmp_path):
    config, path, doc = base_setup(tmp_path)
    doc.timeline.width = 320
    doc.timeline.height = 180
    path.write_text(serialize_cutlist(doc), encoding="utf-8")
    return config, path, doc


def test_native_output_is_checked_independently_and_does_not_certify_app(tmp_path):
    config, path, doc = setup(tmp_path)
    package = export_jianying(config, doc, path, name="output").draft_path
    video = tmp_path / "native.mp4"
    make_video(video, duration_seconds=0.8)
    result = check_output(package, video)
    assert result.output_check == "passed"
    assert result.native_validation == "not_run"
    assert result.duration_us == 800_000
    assert result.sha256 and result.decode_checked


def test_output_changed_duration_needs_explicit_new_expectation(tmp_path):
    config, path, doc = setup(tmp_path)
    package = export_jianying(config, doc, path, name="output").draft_path
    video = tmp_path / "native.mp4"
    make_video(video, duration_seconds=1.2)
    with pytest.raises(PreflightError, match="duration"):
        check_output(package, video)
    assert check_output(package, video, expected_duration_us=1_200_000).output_check == "passed"


def test_output_wrong_canvas_is_rejected(tmp_path):
    config, path, doc = setup(tmp_path)
    doc.timeline.width = 640
    path.write_text(serialize_cutlist(doc), encoding="utf-8")
    package = export_jianying(config, doc, path, name="output").draft_path
    video = tmp_path / "native.mp4"
    make_video(video, duration_seconds=0.8)
    with pytest.raises(PreflightError, match="dimensions"):
        check_output(package, video)


def test_incomplete_output_is_rejected(tmp_path):
    config, path, doc = setup(tmp_path)
    package = export_jianying(config, doc, path, name="output").draft_path
    video = tmp_path / "native.mp4"
    video.write_bytes(b"partial")
    with pytest.raises(PreflightError):
        check_output(package, video)
