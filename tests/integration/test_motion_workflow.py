from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from interview_edit.cli.app import app
from interview_edit.config.loader import load_project_config
from interview_edit.cutlist.editing import attach_motion
from interview_edit.cutlist.service import load_cutlist
from interview_edit.errors import PreflightError
from interview_edit.export.jianying import export_jianying
from interview_edit.models.motion import MotionSpec
from interview_edit.motion.service import build_motion, revise_motion, verify_motion
from interview_edit.qc.service import QCRequest, run_qc
from interview_edit.render.service import RenderRequest, render_cutlist
from tests.integration.test_render import _render_project
from tests.unit.test_text_quality import font_path


@pytest.fixture
def project(tmp_path):
    root, path = _render_project(tmp_path)
    return root, path, load_project_config(root)


def spec(template="callout"):
    return MotionSpec(
        template=template,
        text="Keep source editable",
        secondary="Local motion",
        font_path=str(font_path()),
        width=640,
        height=360,
        duration_us=1_200_000,
        enter_us=200_000,
        exit_us=200_000,
    )


@pytest.mark.parametrize("template", ["callout", "lower_third", "chapter"])
def test_motion_alpha_duration_and_immutable_editable_source(project, tmp_path, template):
    root, path, config = project
    dry = build_motion(config, spec(template), dry_run=True)
    assert not dry.path.exists()
    built = build_motion(config, spec(template))
    saved, manifest = verify_motion(config, built.path)
    assert manifest.frame_count == 30 and manifest.duration_us == 1_200_000
    assert saved.text == "Keep source editable"
    with Image.open(built.path / "poster.png") as poster:
        alpha = np.asarray(poster.getchannel("A"))
        assert alpha.min() == 0 and alpha.max() > 200
    edited = revise_motion(config, built.path, {"text": "Changed source text", "accent": "#FF9955"})
    assert edited.path != built.path
    assert verify_motion(config, built.path)[0].text == saved.text
    assert verify_motion(config, edited.path)[0].text == "Changed source text"
    # Decode the movie alpha itself, not just the PNG source.
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "0.4",
            "-i",
            str(built.path / "render.mov"),
            "-frames:v",
            "1",
            "-vf",
            "alphaextract",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    pixels = np.frombuffer(result.stdout, dtype=np.uint8)
    assert pixels.size == 640 * 360 and pixels.min() == 0 and pixels.max() > 200


def test_motion_attach_render_keeps_background_and_rejects_mutated_asset(project, tmp_path):
    root, path, config = project
    motion = build_motion(config, spec())
    document = load_cutlist(path)
    item = document.acts[0].items[0]
    revised = attach_motion(
        config, document, path, item_id=item.item_id, asset_path=motion.path, duration_us=800_000
    )
    cut = load_cutlist(revised.output_path)
    rendered = render_cutlist(
        RenderRequest(
            config=config,
            project_root=root,
            cutlist=cut,
            cutlist_path=revised.output_path,
            profile_name="preview",
        )
    )
    assert rendered.output.duration_us == 800_000
    qc = run_qc(QCRequest(config=config, project_root=root, run_id=rendered.run_id))
    assert qc.report_path is not None and qc.report.state == "passed", qc.report
    with pytest.raises(PreflightError) as unsupported:
        export_jianying(config, cut, revised.output_path, name="Motion handoff")
    assert unsupported.value.code == "jianying_motion_unsupported"
    image = tmp_path / "composite.png"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "0.4",
            "-i",
            rendered.output.path,
            "-frames:v",
            "1",
            str(image),
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    with Image.open(image) as source:
        pixels = np.asarray(source.convert("RGB"))
    assert (
        pixels[-10, -10, 2] > 180 and pixels[-10, -10, 0] < 30
    )  # blue source visible outside the motion
    assert (
        np.count_nonzero(np.max(pixels, axis=2) - np.min(pixels, axis=2) < 20) > 100
    )  # actual card pixels composited
    (motion.path / "render.mov").write_bytes(b"changed")
    with pytest.raises(PreflightError):
        verify_motion(config, motion.path)
    with pytest.raises(PreflightError):
        render_cutlist(
            RenderRequest(
                config=config,
                project_root=root,
                cutlist=cut,
                cutlist_path=revised.output_path,
                profile_name="preview",
            )
        )


def test_motion_cli_preserves_text_privacy_and_source_revision(project):
    root, path, config = project
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "motion",
            "build",
            "--project",
            str(root),
            "--font",
            str(font_path()),
            "--text",
            "Private source text",
            "--width",
            "640",
            "--height",
            "360",
            "--duration-us",
            "1200000",
            "--enter-us",
            "200000",
            "--exit-us",
            "200000",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Private source text" not in result.stdout
    asset = Path(json.loads(result.stdout)["data"]["assetPath"])
    result = runner.invoke(
        app,
        [
            "motion",
            "edit",
            "--project",
            str(root),
            "--asset",
            str(asset),
            "--text",
            "New wording",
            "--foreground",
            "#99FFCC",
            "--background",
            "#222222",
            "--font",
            str(font_path()),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert verify_motion(config, asset)[0].text == "Private source text"
    assert "New wording" not in result.stdout
    changed = Path(json.loads(result.stdout)["data"]["assetPath"])
    assert verify_motion(config, changed)[0].foreground == "#99FFCC"


def test_motion_failed_generation_preserves_existing_asset_and_no_partial_movie(project):
    from interview_edit.adapters.process import ProcessResult
    from interview_edit.errors import ProcessingError

    root, path, config = project
    old = build_motion(config, spec())

    class BrokenEncoder:
        def run(self, args, **kwargs):
            return ProcessResult(tuple(args), 1, "", "encode failed")

    with pytest.raises(ProcessingError):
        build_motion(config, spec(), runner=BrokenEncoder())
    assert list((config.artifact_root / "motion").iterdir()) == [old.path]


def test_motion_rejects_invalid_attachment_and_changed_source(project):
    from interview_edit.errors import UsageError

    root, path, config = project
    motion = build_motion(config, spec())
    doc = load_cutlist(path)
    with pytest.raises(UsageError):
        attach_motion(
            config,
            doc,
            path,
            item_id=doc.acts[0].items[0].item_id,
            asset_path=motion.path,
            duration_us=1_200_000,
        )
    original = (motion.path / "spec.json").read_bytes()
    (motion.path / "spec.json").write_bytes(original.replace(b"Keep source", b"Fake source"))
    with pytest.raises(PreflightError):
        revise_motion(config, motion.path, {"text": "Another revision"})


def test_motion_rejects_overflow_before_creating_files(project):
    root, path, config = project
    with pytest.raises(PreflightError) as overflow:
        build_motion(config, spec().model_copy(update={"text": "W" * 160}))
    assert overflow.value.code == "motion_text_overflow"
    assert not (config.artifact_root / "motion").exists()


def test_motion_inventory_rejects_escape_and_wrong_project(project):
    root, path, config = project
    motion = build_motion(config, spec())
    with pytest.raises(PreflightError):
        verify_motion(config.model_copy(update={"project_id": "prj_another-project"}), motion.path)
    manifest = json.loads((motion.path / "manifest.json").read_text())
    manifest["files"][0]["relative_path"] = "../other.mov"
    (motion.path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(PreflightError):
        verify_motion(config, motion.path)
