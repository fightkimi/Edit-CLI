from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from typer.testing import CliRunner

from interview_edit.adapters.process import SubprocessRunner
from interview_edit.cli.app import app
from interview_edit.cutlist.service import serialize_cutlist
from interview_edit.exit_codes import ExitCode
from interview_edit.ingest.service import IngestRequest, ingest_media
from interview_edit.models.cutlist import Act, CutList, Overlay, TimelineItem
from interview_edit.models.media import MediaAsset
from interview_edit.project.service import InitRequest, initialize_project
from interview_edit.proxy.service import ProxyRequest, build_proxies
from interview_edit.status.service import read_project_status
from tests.fixtures.media_factory import make_video, require_media_tools

runner = CliRunner()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _primary(
    item_id: str,
    asset: MediaAsset,
    *,
    role: str,
    source_in_us: int,
    source_out_us: int,
    overlays: list[Overlay] | None = None,
) -> TimelineItem:
    return TimelineItem(
        item_id=item_id,
        kind="primary",
        content_role=role,
        source_id=asset.asset_id,
        source_in_us=source_in_us,
        source_out_us=source_out_us,
        timeline_duration_us=source_out_us - source_in_us,
        audio_source=asset.asset_id,
        overlays=overlays or [],
    )


def _interview(source: MediaAsset, _: MediaAsset) -> list[Act]:
    return [
        Act(
            act_id="answer",
            items=[
                _primary(
                    "interview_context",
                    source,
                    role="interview",
                    source_in_us=0,
                    source_out_us=300_000,
                ),
                _primary(
                    "interview_answer",
                    source,
                    role="interview",
                    source_in_us=500_000,
                    source_out_us=900_000,
                ),
            ],
        )
    ]


def _talking_head(source: MediaAsset, _: MediaAsset) -> list[Act]:
    return [
        Act(
            act_id="hook_and_point",
            items=[
                _primary(
                    "talking_head_hook",
                    source,
                    role="talking-head",
                    source_in_us=100_000,
                    source_out_us=700_000,
                )
            ],
        )
    ]


def _tutorial(source: MediaAsset, _: MediaAsset) -> list[Act]:
    return [
        Act(
            act_id="step_1",
            items=[
                _primary(
                    "tutorial_step_1",
                    source,
                    role="tutorial",
                    source_in_us=0,
                    source_out_us=300_000,
                )
            ],
        ),
        Act(
            act_id="step_2",
            items=[
                _primary(
                    "tutorial_step_2",
                    source,
                    role="tutorial",
                    source_in_us=300_000,
                    source_out_us=700_000,
                )
            ],
        ),
    ]


def _review(source: MediaAsset, broll: MediaAsset) -> list[Act]:
    evidence_overlay = Overlay(
        overlay_id="review_evidence",
        kind="broll",
        start_us=200_000,
        duration_us=200_000,
        source_id=broll.asset_id,
        source_in_us=100_000,
        source_out_us=300_000,
    )
    return [
        Act(
            act_id="evidence_and_verdict",
            items=[
                _primary(
                    "review_claim",
                    source,
                    role="review",
                    source_in_us=0,
                    source_out_us=600_000,
                    overlays=[evidence_overlay],
                )
            ],
        )
    ]


def _vlog(source: MediaAsset, broll: MediaAsset) -> list[Act]:
    return [
        Act(
            act_id="chronology",
            items=[
                _primary(
                    "vlog_moment",
                    source,
                    role="vlog",
                    source_in_us=0,
                    source_out_us=400_000,
                ),
                TimelineItem(
                    item_id="vlog_environment",
                    kind="broll",
                    source_id=broll.asset_id,
                    source_in_us=400_000,
                    source_out_us=700_000,
                    timeline_duration_us=300_000,
                ),
            ],
        )
    ]


SCENARIOS: dict[str, Callable[[MediaAsset, MediaAsset], list[Act]]] = {
    "interview": _interview,
    "talking-head": _talking_head,
    "tutorial": _tutorial,
    "review": _review,
    "vlog": _vlog,
}


def test_five_creator_formats_validate_render_and_pass_preview_qc(tmp_path: Path) -> None:
    require_media_tools()
    media = tmp_path / "synthetic media"
    source_path = media / "speech source.mp4"
    broll_path = media / "reusable b-roll.mp4"
    make_video(source_path, color="blue", frequency=440, duration_seconds=1.2)
    make_video(broll_path, color="green", frequency=520, duration_seconds=1.2)
    source_hashes = {path: _sha256(path) for path in (source_path, broll_path)}

    initialized = initialize_project(
        InitRequest(
            project=tmp_path / "creator matrix project",
            name="M7 synthetic creator matrix",
            media_roots=[media],
            privacy="strict",
        )
    )
    indexed = ingest_media(
        IngestRequest(config=initialized.config, full_hash=True),
        runner=SubprocessRunner(),
    )
    build_proxies(
        ProxyRequest(config=initialized.config, index=indexed.index, resume=True),
        runner=SubprocessRunner(),
    )
    by_name = {Path(asset.canonical_path).name: asset for asset in indexed.index.assets}
    source = by_name[source_path.name]
    broll = by_name[broll_path.name]
    project = initialized.config.artifact_root.parent
    observed_roles: set[str] = set()

    for role, build_acts in SCENARIOS.items():
        document = CutList(
            project_id=initialized.config.project_id,
            timeline=initialized.config.timeline,
            acts=build_acts(source, broll),
            render_profile="preview",
        )
        observed_roles.update(
            item.content_role
            for act in document.acts
            for item in act.items
            if item.content_role is not None
        )
        cutlist_path = project / "cutlists" / "revisions" / f"{role}.yaml"
        cutlist_path.write_text(serialize_cutlist(document), encoding="utf-8")

        validated = runner.invoke(
            app,
            [
                "cutlist",
                "validate",
                "--project",
                str(project),
                "--cutlist",
                str(cutlist_path),
                "--profile",
                "preview",
                "--json",
            ],
        )
        assert validated.exit_code == ExitCode.SUCCESS, f"{role}: {validated.output}"
        validation_payload = json.loads(validated.stdout)
        assert validation_payload["ok"] is True, role
        assert validation_payload["data"]["profile"] == "preview", role

        rendered = runner.invoke(
            app,
            [
                "render",
                "--project",
                str(project),
                "--cutlist",
                str(cutlist_path),
                "--profile",
                "preview",
                "--resume",
                "--json",
            ],
        )
        assert rendered.exit_code == ExitCode.SUCCESS, f"{role}: {rendered.output}"
        render_payload = json.loads(rendered.stdout)
        assert render_payload["ok"] is True, role
        output_path = Path(render_payload["data"]["outputPath"])
        assert output_path.is_file(), role
        assert output_path.read_bytes()[4:8] == b"ftyp", role
        run_id = render_payload["runId"]
        assert isinstance(run_id, str), role

        checked = runner.invoke(
            app,
            [
                "qc",
                "--project",
                str(project),
                "--run",
                run_id,
                "--policy",
                "preview",
                "--json",
            ],
        )
        assert checked.exit_code == ExitCode.SUCCESS, f"{role}: {checked.output}"
        qc_payload = json.loads(checked.stdout)
        assert qc_payload["ok"] is True, role
        assert qc_payload["data"]["report"]["policy"] == "preview", role
        assert qc_payload["data"]["report"]["state"] == "passed", role

    assert observed_roles == set(SCENARIOS)
    assert all(_sha256(path) == digest for path, digest in source_hashes.items())
    status = read_project_status(initialized.config, project_root=project)
    assert status.stages["ingest"]["validity"] == "current"
    assert status.stages["proxy"]["validity"] == "current"
    assert status.stages["render"]["validity"] == "current"
    assert status.stages["qc"]["validity"] == "current"
