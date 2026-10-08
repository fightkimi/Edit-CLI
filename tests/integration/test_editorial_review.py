from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from interview_edit.adapters.process import ProcessResult
from interview_edit.cli.app import app
from interview_edit.config.loader import load_project_config
from interview_edit.cutlist.service import load_cutlist, serialize_cutlist
from interview_edit.errors import PreflightError, ProcessingError
from interview_edit.ingest.service import read_media_index
from interview_edit.models.cutlist import AudioPolicy
from interview_edit.models.review import PhraseIndex, TimelineReview
from interview_edit.render.service import RenderRequest, render_cutlist
from interview_edit.review.service import phrase_view, timeline_review
from interview_edit.transcribe.service import TranscribeRequest, transcribe_assets
from tests.fixtures.transcription import MockTranscriber
from tests.integration.test_render import _render_project


@pytest.fixture
def project(tmp_path):
    root, path = _render_project(tmp_path)
    config = load_project_config(root)
    index = read_media_index(config, required=True)
    transcribe_assets(
        TranscribeRequest(config=config, project_root=root, index=index),
        transcriber=MockTranscriber(),
    )
    return root, path, config, index.assets[0]


def test_phrase_cli_keeps_content_local_and_rejects_changed_transcripts(project):
    root, path, config, asset = project
    result = CliRunner().invoke(
        app, ["review", "transcript", "--project", str(root), "--asset", asset.asset_id, "--json"]
    )
    assert result.exit_code == 0, result.output
    assert "[mock transcript]" not in result.stdout
    data = json.loads(result.stdout)
    folder = Path(data["data"]["reviewPath"])
    index = PhraseIndex.model_validate_json((folder / "phrases.json").read_text(encoding="utf-8"))
    assert index.phrases[0].text == "[mock transcript]" and index.input_hashes
    before = set((config.artifact_root / "review").iterdir())
    transcript = config.artifact_root / "transcripts" / asset.asset_id / "corrected.jsonl"
    transcript.write_text("{}", encoding="utf-8")
    with pytest.raises(PreflightError):
        phrase_view(config, asset_ids=[asset.asset_id])
    assert set((config.artifact_root / "review").iterdir()) == before


def test_source_window_has_absolute_audio_word_times_and_no_dry_run_writes(project):
    root, path, config, asset = project
    dry = timeline_review(
        config, asset_id=asset.asset_id, focus_us=400_000, window_us=300_000, dry_run=True
    )
    assert not dry.path.exists()
    result = timeline_review(config, asset_id=asset.asset_id, focus_us=400_000, window_us=300_000)
    report = TimelineReview.model_validate_json(
        (result.path / "report.json").read_text(encoding="utf-8")
    )
    assert report.audio_status == "decoded" and report.peak_dbfs < 0
    assert report.words[0].source_start_us == report.words[0].start_us == 0
    assert report.image_sha256 and (result.path / "window.wav").is_file()
    assert not report.listening_verified


def test_output_window_maps_clipped_words_and_rejects_replaced_video(project):
    root, path, config, asset = project
    doc = load_cutlist(path)
    doc.audio_policy = AudioPolicy(edge_fade_us=5_000)
    path.write_text(serialize_cutlist(doc), encoding="utf-8")
    rendered = render_cutlist(
        RenderRequest(
            config=config, project_root=root, cutlist=doc, cutlist_path=path, profile_name="preview"
        )
    )
    result = timeline_review(config, run_id=rendered.run_id, focus_us=400_000, window_us=300_000)
    report = TimelineReview.model_validate_json(
        (result.path / "report.json").read_text(encoding="utf-8")
    )
    word = report.words[0]
    assert word.start_us == 0 and word.end_us == 800_000 and word.clipped
    assert word.source_start_us == 0 and word.source_end_us == 1_200_000
    assert "word_clipped_at_cut" in report.warnings
    Path(rendered.output.path).write_bytes(b"replaced")
    with pytest.raises(PreflightError):
        timeline_review(config, run_id=rendered.run_id, focus_us=400_000)


def test_decode_failure_cleans_only_new_review_and_is_not_reported_as_silence(project):
    root, path, config, asset = project
    old = phrase_view(config, asset_ids=[asset.asset_id]).path

    class BrokenAudio:
        def run(self, args, **kwargs):
            if args[0] == "ffprobe":
                return ProcessResult(
                    tuple(args),
                    0,
                    json.dumps(
                        {
                            "format": {"duration": "1.2"},
                            "streams": [
                                {"codec_type": "video", "width": 320, "height": 180},
                                {"codec_type": "audio", "sample_rate": "48000"},
                            ],
                        }
                    ),
                    "",
                )
            return ProcessResult(tuple(args), 1, "", "decode error")

    with pytest.raises(ProcessingError):
        timeline_review(config, asset_id=asset.asset_id, focus_us=400_000, runner=BrokenAudio())
    assert list((config.artifact_root / "review").iterdir()) == [old]


def test_windows_reaching_the_end_of_a_clip_still_have_valid_frames(project):
    root, path, config, asset = project
    result = timeline_review(
        config, asset_id=asset.asset_id, focus_us=asset.duration_us - 1, window_us=200_000
    )
    report = TimelineReview.model_validate_json(
        (result.path / "report.json").read_text(encoding="utf-8")
    )
    assert report.frames and all(Path(frame.path).is_file() for frame in report.frames)


def test_audio_cli_revision_changes_pcm_edges_and_native_keyframes(project, tmp_path):
    import numpy as np

    from interview_edit.adapters.process import SubprocessRunner
    from interview_edit.adapters.timeline import audio_window
    from interview_edit.export.jianying import export_jianying

    root, path, config, asset = project
    original = load_cutlist(path)
    baseline = render_cutlist(
        RenderRequest(
            config=config,
            project_root=root,
            cutlist=original,
            cutlist_path=path,
            profile_name="preview",
            output=config.artifact_root / "renders/baseline.mp4",
        )
    )
    command = CliRunner().invoke(
        app,
        [
            "cutlist",
            "audio",
            "--project",
            str(root),
            "--cutlist",
            str(path),
            "--edge-fade-us",
            "30000",
            "--json",
        ],
    )
    assert command.exit_code == 0, command.output
    revised_path = Path(json.loads(command.stdout)["data"]["cutlistPath"])
    revised = load_cutlist(revised_path)
    processed = render_cutlist(
        RenderRequest(
            config=config,
            project_root=root,
            cutlist=revised,
            cutlist_path=revised_path,
            profile_name="preview",
            output=config.artifact_root / "renders/processed.mp4",
        )
    )
    runner = SubprocessRunner()
    left = audio_window(Path(baseline.output.path), tmp_path / "before.wav", 0, 20_000, runner)
    right = audio_window(Path(processed.output.path), tmp_path / "after.wav", 0, 20_000, runner)
    assert np.mean(right * right) < 0.6 * np.mean(left * left)
    assert baseline.output.duration_us == processed.output.duration_us
    assert baseline.cache[0].cache_key != processed.cache[0].cache_key
    package = export_jianying(config, revised, revised_path, name="edges").draft_path
    native = json.loads((package / "draft_info.json").read_text(encoding="utf-8"))
    audio = next(t for t in native["tracks"] if t["type"] == "audio")["segments"][0]
    assert audio["common_keyframes"][0]["property_type"] == "KFTypeVolume"
    points = audio["common_keyframes"][0]["keyframe_list"]
    assert points[0]["values"] == [0.0] and points[-1]["values"] == [0.0]


def test_review_rejects_input_change_during_frame_generation(project, monkeypatch):
    from interview_edit.review import service

    root, path, config, asset = project
    real = service.draw_timeline

    def corrupt(*args):
        real(*args)
        (config.artifact_root / "proxies" / f"{asset.asset_id}.mp4").write_bytes(b"changed")

    monkeypatch.setattr(service, "draw_timeline", corrupt)
    with pytest.raises(PreflightError):
        timeline_review(config, asset_id=asset.asset_id, focus_us=400_000, window_us=200_000)
    assert not list((config.artifact_root / "review").iterdir())


def test_contiguous_items_preserve_volume_at_the_join_and_cache_boundary_context(project):
    from interview_edit.export.jianying import export_jianying

    root, path, config, asset = project
    doc = load_cutlist(path)
    first = doc.acts[0].items[0]
    first.source_out_us = 500_000
    first.timeline_duration_us = 400_000
    second = first.model_copy(
        deep=True, update={"item_id": "second", "source_in_us": 500_000, "source_out_us": 900_000}
    )
    doc.acts[0].items.append(second)
    doc.audio_policy.edge_fade_us = 30_000
    path.write_text(serialize_cutlist(doc), encoding="utf-8")
    full = render_cutlist(
        RenderRequest(
            config=config,
            project_root=root,
            cutlist=doc,
            cutlist_path=path,
            profile_name="preview",
            output=config.artifact_root / "renders/full.mp4",
        )
    )
    selected = render_cutlist(
        RenderRequest(
            config=config,
            project_root=root,
            cutlist=doc,
            cutlist_path=path,
            profile_name="preview",
            item_id=second.item_id,
            resume=True,
            output=config.artifact_root / "renders/item.mp4",
        )
    )
    assert full.cache[1].cache_key != selected.cache[0].cache_key
    review = timeline_review(config, run_id=full.run_id, focus_us=400_000, window_us=300_000)
    import wave

    with wave.open(str(review.path / "window.wav")) as handle:
        assert handle.getnframes() == 28_800
        import numpy as np

        pcm = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(float)
        boundary = pcm[12_000:16_800]  # 350–450ms includes mux/codec offsets around the cut
        energies = [np.mean(chunk * chunk) for chunk in np.array_split(boundary, 20)]
        assert min(energies) > 0.4 * np.mean(pcm * pcm), (
            "Continuous speech gained an encoder-priming gap"
        )
    package = export_jianying(config, doc, path, name="continuous").draft_path
    native = json.loads((package / "draft_info.json").read_text(encoding="utf-8"))
    segments = next(t for t in native["tracks"] if t["type"] == "audio")["segments"]
    assert segments[0]["common_keyframes"][0]["keyframe_list"][-1]["values"] == [1.0]
    assert segments[1]["common_keyframes"][0]["keyframe_list"][0]["values"] == [1.0]


def test_review_without_an_audio_stream_is_explicit(project, monkeypatch):
    from interview_edit.adapters.media import ProbeMetadata
    from interview_edit.review import service

    root, path, config, asset = project
    real = service.probe_media

    def no_audio(*args):
        metadata = real(*args)
        return ProbeMetadata(
            metadata.duration_us,
            metadata.start_time_us,
            metadata.stream_time_base,
            metadata.video_stream,
            [],
            metadata.capture_time,
        )

    monkeypatch.setattr(service, "probe_media", no_audio)
    result = timeline_review(config, asset_id=asset.asset_id, focus_us=400_000, window_us=200_000)
    report = TimelineReview.model_validate_json(
        (result.path / "report.json").read_text(encoding="utf-8")
    )
    assert (
        report.audio_status == "missing" and report.audio_path is None and report.peak_dbfs is None
    )
    assert not (result.path / "window.wav").exists()
