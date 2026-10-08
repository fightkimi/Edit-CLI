from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import typer

from interview_edit import __version__
from interview_edit.adapters.jianying_app import host_platform, inspect_jianying, launch_jianying
from interview_edit.cli.output import emit, emit_expected_error
from interview_edit.config.loader import config_path_for, load_project_config
from interview_edit.config.models import ProjectConfig
from interview_edit.cutlist.editing import (
    RevisionResult,
    attach_motion,
    check_speech,
    set_audio_policy,
    set_source_color,
    set_source_range,
    split_captions,
)
from interview_edit.cutlist.service import (
    ScaffoldRequest,
    inspect_cutlist,
    load_cutlist,
    resolve_cutlist_path,
    scaffold_cutlist,
)
from interview_edit.cutlist.validation import validate_cutlist
from interview_edit.doctor.service import run_doctor
from interview_edit.errors import DependencyError, InterviewEditError, PathSafetyError, UsageError
from interview_edit.exit_codes import ExitCode
from interview_edit.export.jianying import export_jianying, verify_draft
from interview_edit.export.jianying_install import install_draft
from interview_edit.export.jianying_output import check_output
from interview_edit.ingest.service import IngestRequest, ingest_media, read_media_index
from interview_edit.models.cutlist import CutList
from interview_edit.models.motion import MotionSpec
from interview_edit.models.protocol import (
    ArtifactReference,
    ErrorPayload,
    JsonEnvelope,
    WarningPayload,
)
from interview_edit.models.qc import QCFindingSeverity, QCPolicy
from interview_edit.motion.service import MotionResult, build_motion, revise_motion, verify_motion
from interview_edit.project.service import InitRequest, initialize_project
from interview_edit.proxy.service import ProxyRequest, build_proxies
from interview_edit.qc.service import QCRequest, run_qc
from interview_edit.render.service import RenderRequest, render_cutlist
from interview_edit.review.color import review_color
from interview_edit.review.service import ReviewResult, phrase_view, timeline_review
from interview_edit.status.service import read_project_status
from interview_edit.sync.service import SyncRequest, parse_manual_offset, sync_take
from interview_edit.transcribe.service import TranscribeRequest, transcribe_assets
from interview_edit.version.service import (
    FreezeRequest,
    freeze_version,
    list_versions,
    load_version,
    verify_version,
)


@dataclass(frozen=True)
class GlobalOptions:
    project: Path | None
    json_output: bool
    quiet: bool
    dry_run: bool
    force: bool
    no_color: bool


app = typer.Typer(
    name="interview-edit",
    help="Local-first, cut-list-driven editing for speech-led creator videos.",
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
proxy_app = typer.Typer(
    name="proxy",
    help="Build cached viewing and speech-analysis proxies from the media index.",
    no_args_is_help=True,
)
app.add_typer(proxy_app, name="proxy")
cutlist_app = typer.Typer(
    name="cutlist",
    help="Create, inspect, and strictly validate versioned edit decisions.",
    no_args_is_help=True,
)
app.add_typer(cutlist_app, name="cutlist")
version_app = typer.Typer(
    name="version",
    help="Freeze, inspect, and verify immutable release versions.",
    no_args_is_help=True,
)
app.add_typer(version_app, name="version")
export_app = typer.Typer(help="Export editable native projects.", no_args_is_help=True)
app.add_typer(export_app, name="export")
jianying_app = typer.Typer(
    help="Inspect and install local Jianying draft packages.", no_args_is_help=True
)
app.add_typer(jianying_app, name="jianying")
review_app = typer.Typer(
    help="Build source phrase and timeline evidence views.", no_args_is_help=True
)
app.add_typer(review_app, name="review")
motion_app = typer.Typer(
    help="Build and revise editable motion source assets.", no_args_is_help=True
)
app.add_typer(motion_app, name="motion")


def _show_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit(ExitCode.SUCCESS)


@app.callback()
def global_options(
    ctx: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Suppress nonessential output.")
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n", help="Plan without writing.")] = False,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Allow documented overwrite.")
    ] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="Disable ANSI color.")] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_show_version,
            is_eager=True,
            help="Show the installed version.",
        ),
    ] = False,
) -> None:
    del version
    if no_color:
        ctx.color = False
    ctx.obj = GlobalOptions(
        project=project,
        json_output=json_output,
        quiet=quiet,
        dry_run=dry_run,
        force=force,
        no_color=no_color,
    )


def _options(ctx: typer.Context) -> GlobalOptions:
    value = ctx.find_root().obj
    if not isinstance(value, GlobalOptions):
        raise RuntimeError("Global CLI options were not initialized.")
    return value


def _selected_project(local: Path | None, global_value: Path | None) -> Path:
    project = local or global_value
    if project is None:
        raise UsageError(
            "project_required",
            "Provide an editing project with --project PATH.",
        )
    return project


def _fail(error: InterviewEditError, *, command: str, json_output: bool) -> None:
    emit_expected_error(error, command=command, json_output=json_output)
    raise typer.Exit(error.exit_code)


def _emit_progress(message: str) -> None:
    typer.echo(message, err=True)


@app.command("init")
def init_command(
    ctx: typer.Context,
    project: Annotated[
        Path | None, typer.Option("--project", help="New editing project directory.")
    ] = None,
    name: Annotated[str | None, typer.Option("--name", help="Human-readable project name.")] = None,
    media_root: Annotated[
        list[Path] | None,
        typer.Option("--media-root", help="Existing read-only source-media directory; repeatable."),
    ] = None,
    privacy: Annotated[
        str | None, typer.Option("--privacy", help="Required: strict or assisted.")
    ] = None,
    artifact_root: Annotated[
        Path | None,
        typer.Option(
            "--artifact-root",
            help="Generated artifact directory; defaults inside project.",
        ),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Overwrite existing config only.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """Create configuration and writable artifact directories without touching source media."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected_project = _selected_project(project, options.project)
        if name is None:
            raise UsageError("name_required", "Provide a project name with --name NAME.")
        if privacy is None:
            raise UsageError(
                "privacy_required",
                "Explicitly choose --privacy strict or --privacy assisted.",
            )
        result = initialize_project(
            InitRequest(
                project=selected_project,
                name=name,
                media_roots=list(media_root or []),
                privacy=privacy,
                artifact_root=artifact_root,
                force=force or options.force,
                dry_run=options.dry_run,
            )
        )
    except InterviewEditError as error:
        _fail(error, command="init", json_output=machine)
        return

    project_arg = shlex.quote(str(result.config_path.parent))
    artifacts = [
        ArtifactReference(kind="config", path=str(result.config_path)),
        ArtifactReference(kind="state", path=str(result.state_path)),
    ]
    envelope = JsonEnvelope(
        ok=True,
        command="init",
        data={
            "projectId": result.config.project_id,
            "projectRoot": str(result.config_path.parent),
            "configPath": str(result.config_path),
            "artifactRoot": str(result.config.artifact_root),
            "privacyMode": result.config.privacy_mode.value,
            "dryRun": result.dry_run,
            "directoryCount": len(result.created_directories),
        },
        artifacts=artifacts,
        next=[f"interview-edit doctor --project {project_arg}"],
    )
    action = "Would initialize" if result.dry_run else "Initialized"
    emit(
        envelope,
        json_output=machine,
        human_lines=[
            f"{action} project: {result.config.name}",
            f"Configuration: {result.config_path}",
            f"Artifacts: {result.config.artifact_root}",
            f"Privacy: {result.config.privacy_mode.value}",
        ],
    )


@app.command("doctor")
def doctor_command(
    ctx: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """Check runtime, media tools, local transcription, paths, and the Codex Skill."""
    options = _options(ctx)
    machine = json_output or options.json_output
    selected = project or options.project
    try:
        config = load_project_config(selected) if selected is not None else None
    except InterviewEditError as error:
        _fail(error, command="doctor", json_output=machine)
        return

    root = config_path_for(selected).parent if selected is not None else None
    report = run_doctor(config, project_root=root)
    warnings = [
        WarningPayload(code=check.name, message=check.message, details=check.details)
        for check in report.checks
        if check.status == "warning"
    ]
    error_payload = None
    if not report.ok:
        error_payload = ErrorPayload(
            code="doctor_failed",
            message="One or more required checks failed.",
            details={"exitCode": int(report.exit_code)},
        )
    envelope = JsonEnvelope(
        ok=report.ok,
        command="doctor",
        data=report.as_dict(),
        warnings=warnings,
        error=error_payload,
    )
    lines = [f"Doctor status: {report.status}"]
    if not options.quiet:
        lines.extend(f"[{check.status}] {check.name}: {check.message}" for check in report.checks)
    emit(envelope, json_output=machine, human_lines=lines)
    if not report.ok:
        raise typer.Exit(report.exit_code)


@app.command("status")
def status_command(
    ctx: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """Report artifact presence and validated control evidence without changing the project."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected = _selected_project(project, options.project)
        config = load_project_config(selected)
        project_root = config_path_for(selected).parent
        status = read_project_status(config, project_root=project_root)
    except InterviewEditError as error:
        _fail(error, command="status", json_output=machine)
        return

    next_commands = [
        f"interview-edit doctor --project {shlex.quote(str(config_path_for(selected).parent))}"
    ]
    project_arg = shlex.quote(str(config_path_for(selected).parent))
    if status.stages["ingest"]["validity"] != "current":
        next_commands.append(f"interview-edit ingest --project {project_arg}")
    elif status.stages["proxy"]["validity"] != "current":
        next_commands.append(f"interview-edit proxy build --project {project_arg}")
    elif status.stages["transcribe"]["validity"] != "current":
        next_commands.append(f"interview-edit transcribe --project {project_arg} --resume")
    else:
        cutlists = sorted(
            [
                path
                for directory in (
                    project_root / "cutlists" / "revisions",
                    config.artifact_root / "cutlists" / "revisions",
                )
                for pattern in ("*.yaml", "*.yml")
                for path in directory.glob(pattern)
            ],
            key=lambda path: (path.stat().st_mtime_ns, str(path)),
        )
        if not cutlists:
            next_commands.append(f"interview-edit cutlist scaffold --project {project_arg}")
        elif status.stages["render"]["validity"] != "current":
            next_commands.append(
                f"interview-edit cutlist validate --project {project_arg} "
                f"--cutlist {shlex.quote(str(cutlists[-1]))}"
            )
        elif status.stages["qc"]["validity"] != "current":
            next_commands.append(f"interview-edit qc --project {project_arg} --policy preview")
        elif status.stages["version"]["validity"] != "current":
            next_commands.append(f"interview-edit version list --project {project_arg}")
    envelope = JsonEnvelope(
        ok=True,
        command="status",
        data=status.as_dict(),
        artifacts=[
            ArtifactReference(kind="config", path=str(config_path_for(selected))),
        ],
        next=next_commands,
    )
    lines = [
        f"Project: {status.name} ({status.project_id})",
        f"Privacy: {status.privacy_mode}",
        f"Artifacts: {status.artifact_root}",
    ]
    if not options.quiet:
        for name, value in status.stages.items():
            lines.append(
                f"- {name}: {value['validity']} ({value['validCount']}/"
                f"{value['expectedCount']} valid, {value['fileCount']} files)"
            )
            latest_run = value.get("latestRun")
            if isinstance(latest_run, dict):
                lines.append(
                    f"  latest run: {latest_run['runId']} ({latest_run['state']}, "
                    f"{latest_run['completedCount']} completed, "
                    f"{latest_run['cachedCount']} cached)"
                )
    emit(envelope, json_output=machine, human_lines=lines)


@app.command("ingest")
def ingest_command(
    ctx: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    media_root: Annotated[
        list[Path] | None,
        typer.Option(
            "--media-root",
            help="Override a source-media root for this run; repeatable.",
        ),
    ] = None,
    camera_map: Annotated[
        Path | None,
        typer.Option("--camera-map", help="YAML camera/take glob mapping."),
    ] = None,
    extensions: Annotated[
        list[str] | None,
        typer.Option(
            "--extensions",
            help="Media extension or comma-separated list; repeatable.",
        ),
    ] = None,
    full_hash: Annotated[
        bool,
        typer.Option("--full-hash", help="Stream every source to compute full SHA-256."),
    ] = False,
    build_proxy_artifacts: Annotated[
        bool,
        typer.Option("--build-proxies", help="Build proxies after a successful index."),
    ] = False,
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume by reusing valid completed asset work."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Re-probe and rebuild selected assets."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """Recursively index source media without copying or modifying it."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected = _selected_project(project, options.project)
        config = load_project_config(selected)
        result = ingest_media(
            IngestRequest(
                config=config,
                media_roots=list(media_root) if media_root else None,
                camera_map=camera_map,
                extensions=list(extensions) if extensions else None,
                full_hash=full_hash,
                resume=resume,
                force=force or options.force,
                dry_run=options.dry_run,
            ),
            progress=None if options.quiet else _emit_progress,
        )
        proxy_result = None
        if build_proxy_artifacts:
            proxy_result = build_proxies(
                ProxyRequest(
                    config=config,
                    index=result.index,
                    resume=resume,
                    force=force or options.force,
                    dry_run=options.dry_run,
                ),
                progress=None if options.quiet else _emit_progress,
            )
    except InterviewEditError as error:
        _fail(error, command="ingest", json_output=machine)
        return

    artifacts = [ArtifactReference(kind="media-index", path=str(result.index_path))]
    if proxy_result is not None:
        artifacts.extend(
            ArtifactReference(kind="proxy-artifact", path=str(path))
            for path in proxy_result.artifacts
        )
        if proxy_result.run_manifest_path is not None:
            artifacts.append(
                ArtifactReference(kind="operation-run", path=str(proxy_result.run_manifest_path))
            )
    warnings = [
        WarningPayload(code=item.code, message=item.message, details=item.details)
        for item in result.index.warnings
    ]
    data = {
        "assetCount": len(result.index.assets),
        "indexPath": str(result.index_path),
        "changes": result.index.changes.model_dump(mode="json"),
        "fullHash": full_hash,
        "resumed": result.resumed,
        "dryRun": result.dry_run,
    }
    if proxy_result is not None:
        data["proxy"] = {
            "built": proxy_result.built,
            "cached": proxy_result.cached,
            "planned": proxy_result.planned,
            "skipped": proxy_result.skipped,
            "runId": proxy_result.run_id,
        }
    project_arg = shlex.quote(str(config_path_for(selected).parent))
    next_commands = (
        [f"interview-edit status --project {project_arg}"]
        if build_proxy_artifacts
        else [f"interview-edit proxy build --project {project_arg}"]
    )
    envelope = JsonEnvelope(
        ok=True,
        command="ingest",
        data=data,
        warnings=warnings,
        artifacts=artifacts,
        next=next_commands,
    )
    action = "Would index" if result.dry_run else "Indexed"
    lines = [
        f"{action} {len(result.index.assets)} assets: {result.index_path}",
        (
            "Changes: "
            f"{len(result.index.changes.added)} added, "
            f"{len(result.index.changes.changed)} changed, "
            f"{len(result.index.changes.unchanged)} unchanged, "
            f"{len(result.index.changes.removed)} removed"
        ),
    ]
    if proxy_result is not None:
        lines.append(f"Proxies: {len(proxy_result.built)} built, {len(proxy_result.cached)} cached")
    emit(envelope, json_output=machine, human_lines=lines)


@proxy_app.command("build")
def proxy_build_command(
    ctx: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    asset: Annotated[
        list[str] | None,
        typer.Option("--asset", help="Build one indexed asset; repeatable."),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume by reusing valid completed asset work."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Rebuild selected assets atomically."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """Build low-bitrate video, normalized audio, thumbnails, and contact sheets."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected = _selected_project(project, options.project)
        config = load_project_config(selected)
        index = read_media_index(config)
        if index is None:
            raise RuntimeError("required media index unexpectedly absent")
        result = build_proxies(
            ProxyRequest(
                config=config,
                index=index,
                asset_ids=list(asset) if asset else None,
                resume=resume,
                force=force or options.force,
                dry_run=options.dry_run,
            ),
            progress=None if options.quiet else _emit_progress,
        )
    except InterviewEditError as error:
        _fail(error, command="proxy build", json_output=machine)
        return

    artifacts = [
        ArtifactReference(kind="proxy-artifact", path=str(path)) for path in result.artifacts
    ]
    if result.run_manifest_path is not None:
        artifacts.append(
            ArtifactReference(kind="operation-run", path=str(result.run_manifest_path))
        )
    project_arg = shlex.quote(str(config_path_for(selected).parent))
    envelope = JsonEnvelope(
        ok=True,
        command="proxy build",
        runId=result.run_id,
        data={
            "built": result.built,
            "cached": result.cached,
            "planned": result.planned,
            "skipped": result.skipped,
            "contactSheetManifest": str(result.contact_sheet_manifest),
            "resumed": result.resumed,
            "dryRun": result.dry_run,
        },
        artifacts=artifacts,
        next=[f"interview-edit status --project {project_arg}"],
    )
    action = "Would build" if result.dry_run else "Proxy build"
    emit(
        envelope,
        json_output=machine,
        human_lines=[
            f"{action}: {len(result.built)} built, {len(result.cached)} cached, "
            f"{len(result.planned)} planned, {len(result.skipped)} skipped",
            f"Contact sheets: {result.contact_sheet_manifest}",
        ],
    )


@app.command("transcribe")
def transcribe_command(
    ctx: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    asset: Annotated[
        list[str] | None,
        typer.Option("--asset", help="Transcribe one indexed asset; repeatable."),
    ] = None,
    take: Annotated[
        str | None, typer.Option("--take", help="Transcribe every audio asset in one take.")
    ] = None,
    language: Annotated[
        str | None, typer.Option("--language", help="Recognition language code.")
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="Local model path or configured model name.")
    ] = None,
    device: Annotated[
        str | None, typer.Option("--device", help="auto, cpu, cuda, or metal.")
    ] = None,
    resume: Annotated[
        bool, typer.Option("--resume", help="Reuse valid completed chunk checkpoints.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Re-run selected recognition work.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """Run local-only, chunked speech recognition and a separate correction layer."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected = _selected_project(project, options.project)
        project_root = config_path_for(selected).parent
        config = load_project_config(selected)
        index = read_media_index(config)
        if index is None:
            raise RuntimeError("required media index unexpectedly absent")
        result = transcribe_assets(
            TranscribeRequest(
                config=config,
                project_root=project_root,
                index=index,
                asset_ids=list(asset) if asset else None,
                take_id=take,
                language=language,
                model=model,
                device=device,
                resume=resume,
                force=force or options.force,
                dry_run=options.dry_run,
            ),
            progress=None if options.quiet else _emit_progress,
        )
    except InterviewEditError as error:
        _fail(error, command="transcribe", json_output=machine)
        return
    artifacts = [
        ArtifactReference(kind="transcript-artifact", path=str(path)) for path in result.artifacts
    ]
    if result.run_manifest_path is not None:
        artifacts.append(
            ArtifactReference(kind="operation-run", path=str(result.run_manifest_path))
        )
    project_arg = shlex.quote(str(config_path_for(selected).parent))
    envelope = JsonEnvelope(
        ok=True,
        command="transcribe",
        runId=result.run_id,
        data={
            "built": result.built,
            "cached": result.cached,
            "corrected": result.corrected,
            "planned": result.planned,
            "resumedChunks": result.resumed_chunks,
            "dryRun": result.dry_run,
        },
        artifacts=artifacts,
        next=[f"interview-edit status --project {project_arg}"],
    )
    action = "Would transcribe" if result.dry_run else "Transcription"
    emit(
        envelope,
        json_output=machine,
        human_lines=[
            f"{action}: {len(result.built)} built, {len(result.cached)} cached, "
            f"{len(result.corrected)} correction-only, {len(result.planned)} planned",
            f"Resumed chunks: {result.resumed_chunks}",
        ],
    )


@app.command("sync")
def sync_command(
    ctx: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    take: Annotated[str | None, typer.Option("--take", help="Mapped take ID.")] = None,
    reference_camera: Annotated[
        str | None,
        typer.Option("--reference-camera", help="Camera ID used as the zero-time reference."),
    ] = None,
    window_count: Annotated[
        int | None,
        typer.Option("--window-count", min=3, help="Beginning/middle/end analysis windows."),
    ] = None,
    visual_check: Annotated[
        bool,
        typer.Option("--visual-check", help="Generate local side-by-side review screenshots."),
    ] = False,
    manual_offset: Annotated[
        list[str] | None,
        typer.Option(
            "--manual-offset",
            help="Override one camera with CAMERA=VALUE; accepts us, ms, or s; repeatable.",
        ),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Recompute analysis and visual evidence.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """Estimate multi-camera offsets and clock drift from local audio proxies."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected = _selected_project(project, options.project)
        if take is None:
            raise UsageError("take_required", "Provide a mapped take with --take ID.")
        if reference_camera is None:
            raise UsageError(
                "reference_camera_required",
                "Provide the reference camera with --reference-camera ID.",
            )
        config = load_project_config(selected)
        index = read_media_index(config)
        if index is None:
            raise RuntimeError("required media index unexpectedly absent")
        result = sync_take(
            SyncRequest(
                config=config,
                index=index,
                take_id=take,
                reference_camera_id=reference_camera,
                window_count=window_count,
                visual_check=visual_check,
                manual_offsets=tuple(parse_manual_offset(value) for value in (manual_offset or [])),
                force=force or options.force,
                dry_run=options.dry_run,
            ),
            progress=None if options.quiet else _emit_progress,
        )
    except InterviewEditError as error:
        _fail(error, command="sync", json_output=machine)
        return

    artifacts = [
        ArtifactReference(kind="sync-artifact", path=str(path)) for path in result.artifacts
    ]
    if result.run_manifest_path is not None:
        artifacts.append(
            ArtifactReference(kind="operation-run", path=str(result.run_manifest_path))
        )
    report_data = result.report.model_dump(mode="json") if result.report is not None else {}
    ok = not result.uncertain_cameras
    error_payload = None
    if not ok:
        error_payload = ErrorPayload(
            code="sync_confidence_insufficient",
            message="One or more cameras require manual sync review.",
            details={
                "cameraIds": result.uncertain_cameras,
                "reportPath": str(result.report_path),
            },
        )
    project_arg = shlex.quote(str(config_path_for(selected).parent))
    envelope = JsonEnvelope(
        ok=ok,
        command="sync",
        runId=result.run_id,
        data={
            "takeId": take,
            "reportPath": str(result.report_path),
            "cached": result.cached,
            "dryRun": result.dry_run,
            "uncertainCameras": result.uncertain_cameras,
            "report": report_data,
        },
        artifacts=artifacts,
        next=[f"interview-edit status --project {project_arg}"],
        error=error_payload,
    )
    emit(
        envelope,
        json_output=machine,
        human_lines=[
            ("Would analyze" if result.dry_run else "Sync analysis")
            + f": {take}; cached={result.cached}",
            f"Report: {result.report_path}",
            f"Uncertain cameras: {', '.join(result.uncertain_cameras) or 'none'}",
        ],
    )
    if not ok:
        raise typer.Exit(ExitCode.PREFLIGHT_FAILED)


@cutlist_app.command("scaffold")
def cutlist_scaffold_command(
    ctx: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    asset: Annotated[
        str | None,
        typer.Option("--asset", help="Build a chronological skeleton from this transcript."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Project-local YAML output path."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Replace an existing scaffold atomically.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """Create a blank cut-list or a deterministic skeleton from one corrected transcript."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected = _selected_project(project, options.project)
        project_root = config_path_for(selected).parent
        config = load_project_config(selected)
        result = scaffold_cutlist(
            ScaffoldRequest(
                config=config,
                project_root=project_root,
                asset_id=asset,
                output=output,
                force=force or options.force,
                dry_run=options.dry_run,
            )
        )
    except InterviewEditError as error:
        _fail(error, command="cutlist scaffold", json_output=machine)
        return

    cutlist_arg = shlex.quote(str(result.output_path))
    project_arg = shlex.quote(str(project_root))
    envelope = JsonEnvelope(
        ok=True,
        command="cutlist scaffold",
        data={
            "cutlistPath": str(result.output_path),
            "fromTranscript": result.from_transcript,
            "estimatedSubtitleCount": result.estimated_subtitle_count,
            "actCount": len(result.cutlist.acts),
            "itemCount": sum(len(act.items) for act in result.cutlist.acts),
            "dryRun": result.dry_run,
        },
        artifacts=[ArtifactReference(kind="cutlist", path=str(result.output_path))],
        next=[
            f"interview-edit cutlist inspect --project {project_arg} --cutlist {cutlist_arg}",
            f"interview-edit cutlist validate --project {project_arg} --cutlist {cutlist_arg}",
        ],
    )
    action = "Would scaffold" if result.dry_run else "Scaffolded"
    emit(
        envelope,
        json_output=machine,
        human_lines=[
            f"{action} cut-list: {result.output_path}",
            f"Items: {sum(len(act.items) for act in result.cutlist.acts)}",
        ],
    )


@cutlist_app.command("inspect")
def cutlist_inspect_command(
    ctx: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    cutlist: Annotated[Path | None, typer.Option("--cutlist", help="Cut-list YAML path.")] = None,
    act: Annotated[str | None, typer.Option("--act", help="Inspect one act ID.")] = None,
    item: Annotated[str | None, typer.Option("--item", help="Inspect one item ID.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """Show structure and timing without emitting content-bearing editorial text."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected = _selected_project(project, options.project)
        if cutlist is None:
            raise UsageError("cutlist_required", "Provide a cut-list with --cutlist PATH.")
        project_root = config_path_for(selected).parent
        cutlist_path = resolve_cutlist_path(project_root, cutlist)
        document = load_cutlist(cutlist_path)
        data = inspect_cutlist(
            document,
            cutlist_path=cutlist_path,
            act_id=act,
            item_id=item,
        )
    except InterviewEditError as error:
        _fail(error, command="cutlist inspect", json_output=machine)
        return

    envelope = JsonEnvelope(
        ok=True,
        command="cutlist inspect",
        data=data,
        artifacts=[ArtifactReference(kind="cutlist", path=str(cutlist_path))],
    )
    emit(
        envelope,
        json_output=machine,
        human_lines=[
            f"Cut-list: {cutlist_path}",
            f"Acts: {data['actCount']}; items: {data['itemCount']}",
            f"Timeline duration: {data['timelineDurationUs']} us",
        ],
    )


@cutlist_app.command("validate")
def cutlist_validate_command(
    ctx: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    cutlist: Annotated[Path | None, typer.Option("--cutlist", help="Cut-list YAML path.")] = None,
    profile: Annotated[
        str | None, typer.Option("--profile", help="Configured preview or master profile.")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """Run schema and render preflight checks without creating render artifacts."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected = _selected_project(project, options.project)
        if cutlist is None:
            raise UsageError("cutlist_required", "Provide a cut-list with --cutlist PATH.")
        project_root = config_path_for(selected).parent
        config = load_project_config(selected)
        cutlist_path = resolve_cutlist_path(project_root, cutlist)
        document = load_cutlist(cutlist_path)
        report = validate_cutlist(
            config,
            document,
            cutlist_path=cutlist_path,
            profile_name=profile,
        )
    except InterviewEditError as error:
        _fail(error, command="cutlist validate", json_output=machine)
        return

    warnings = [
        WarningPayload(code=issue.code, message=issue.message, details=issue.details)
        for issue in report.issues
        if issue.severity == "warning"
    ]
    error_payload = None
    if not report.ok:
        error_payload = ErrorPayload(
            code="cutlist_validation_failed",
            message="Cut-list failed render preflight validation.",
            details={
                "issueCount": sum(issue.severity == "error" for issue in report.issues),
                "cutlistPath": str(cutlist_path),
            },
        )
    envelope = JsonEnvelope(
        ok=report.ok,
        command="cutlist validate",
        data=report.model_dump(mode="json"),
        warnings=warnings,
        artifacts=[ArtifactReference(kind="cutlist", path=str(cutlist_path))],
        error=error_payload,
    )
    lines = [
        f"Cut-list validation: {'passed' if report.ok else 'failed'}",
        f"Acts: {report.act_count}; items: {report.item_count}",
    ]
    if not options.quiet:
        lines.extend(f"[{issue.severity}] {issue.code}: {issue.message}" for issue in report.issues)
    emit(envelope, json_output=machine, human_lines=lines)
    if not report.ok:
        raise typer.Exit(ExitCode.PREFLIGHT_FAILED)


def _editing_context(
    options: GlobalOptions,
    project: Path | None,
    cutlist: Path | None,
) -> tuple[ProjectConfig, Path, CutList, Path]:
    selected = _selected_project(project, options.project)
    if cutlist is None:
        raise UsageError("cutlist_required", "Provide a cut-list with --cutlist PATH.")
    root = config_path_for(selected).parent
    path = resolve_cutlist_path(root, cutlist)
    return load_project_config(selected), path, load_cutlist(path), root


def _emit_revision(result: RevisionResult, command: str, project: Path, machine: bool) -> None:
    path = shlex.quote(str(result.output_path))
    project_arg = shlex.quote(str(project))
    envelope = JsonEnvelope(
        ok=True,
        command=command,
        data={
            "cutlistPath": str(result.output_path),
            "itemIds": result.item_ids,
            "dryRun": result.dry_run,
        },
        warnings=[WarningPayload.model_validate(w) for w in result.warnings],
        artifacts=[]
        if result.dry_run
        else [ArtifactReference(kind="cutlist", path=str(result.output_path))],
        next=[f"interview-edit render --project {project_arg} --cutlist {path} --profile preview"],
    )
    emit(
        envelope,
        json_output=machine,
        human_lines=[
            f"{'Would write' if result.dry_run else 'Wrote'} revision: {result.output_path}",
            *[f"Warning [{w['code']}]: {w['message']}" for w in result.warnings],
        ],
    )


@cutlist_app.command("set-range")
def cutlist_set_range_command(
    ctx: typer.Context,
    item: Annotated[str, typer.Option("--item", help="Item whose source range should change.")],
    in_us: Annotated[
        int, typer.Option("--in-us", min=0, help="New source start in integer microseconds.")
    ],
    out_us: Annotated[
        int, typer.Option("--out-us", min=1, help="New source end in integer microseconds.")
    ],
    project: Annotated[Path | None, typer.Option("--project")] = None,
    cutlist: Annotated[Path | None, typer.Option("--cutlist")] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="New YAML name under artifact cutlists/revisions."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Write a validated revision while keeping child timing anchored to the source."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        config, path, document, root = _editing_context(options, project, cutlist)
        result = set_source_range(
            config,
            document,
            path,
            item_id=item,
            source_in_us=in_us,
            source_out_us=out_us,
            output=output,
            dry_run=options.dry_run,
        )
    except InterviewEditError as error:
        _fail(error, command="cutlist set-range", json_output=machine)
        return
    _emit_revision(result, "cutlist set-range", root, machine)


@cutlist_app.command("captions")
def cutlist_captions_command(
    ctx: typer.Context,
    project: Annotated[Path | None, typer.Option("--project")] = None,
    cutlist: Annotated[Path | None, typer.Option("--cutlist")] = None,
    item: Annotated[str | None, typer.Option("--item")] = None,
    max_chars: Annotated[int, typer.Option("--max-chars", min=2, max=80)] = 18,
    min_duration_us: Annotated[int, typer.Option("--min-duration-us", min=0, max=5_000_000)] = 0,
    pause_us: Annotated[int, typer.Option("--pause-us", min=0, max=5_000_000)] = 0,
    max_cps: Annotated[int, typer.Option("--max-cps", min=1, max=80)] = 20,
    style: Annotated[
        Literal["standard", "minimal"] | None,
        typer.Option("--style", help="Whole cut-list subtitle preset."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="New YAML name under artifact cutlists/revisions."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Split existing captions without losing text; report estimated timing explicitly."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        config, path, document, root = _editing_context(options, project, cutlist)
        result = split_captions(
            config,
            document,
            path,
            item_id=item,
            max_chars=max_chars,
            min_duration_us=min_duration_us,
            pause_us=pause_us,
            max_chars_per_second=max_cps,
            style=style,
            output=output,
            dry_run=options.dry_run,
        )
    except InterviewEditError as error:
        _fail(error, command="cutlist captions", json_output=machine)
        return
    _emit_revision(result, "cutlist captions", root, machine)


def _emit_motion(result: MotionResult, command: str, machine: bool) -> None:
    emit(
        JsonEnvelope(
            ok=True,
            command=command,
            data={
                "assetPath": str(result.path),
                "assetId": result.manifest.asset_id if result.manifest else None,
                "template": result.spec.template,
                "frameCount": result.frame_count,
                "durationUs": result.spec.duration_us,
                "dryRun": result.dry_run,
            },
            artifacts=[]
            if result.dry_run
            else [ArtifactReference(kind="motion-asset", path=str(result.path))],
            warnings=[
                WarningPayload(
                    code="motion_source_editability",
                    message=(
                        "Edit the retained source spec and generate a new asset; "
                        "movie pixels are not native text layers."
                    ),
                )
            ],
        ),
        json_output=machine,
        human_lines=[f"{'Would build' if result.dry_run else 'Built'} motion: {result.path}"],
    )


@motion_app.command("build")
def motion_build_command(
    ctx: typer.Context,
    text: Annotated[str, typer.Option("--text")],
    project: Annotated[Path | None, typer.Option("--project")] = None,
    template: Annotated[
        Literal["callout", "lower_third", "chapter"], typer.Option("--template")
    ] = "callout",
    secondary: Annotated[str, typer.Option("--secondary")] = "",
    font: Annotated[Path | None, typer.Option("--font")] = None,
    width: Annotated[int | None, typer.Option("--width", min=320, max=3840)] = None,
    height: Annotated[int | None, typer.Option("--height", min=180, max=3840)] = None,
    duration_us: Annotated[
        int, typer.Option("--duration-us", min=800_000, max=10_000_000)
    ] = 3_000_000,
    enter_us: Annotated[int, typer.Option("--enter-us", min=0, max=2_000_000)] = 300_000,
    exit_us: Annotated[int, typer.Option("--exit-us", min=0, max=2_000_000)] = 250_000,
    accent: Annotated[str, typer.Option("--accent")] = "#76A9FA",
    foreground: Annotated[str, typer.Option("--foreground")] = "#FFFFFF",
    background: Annotated[str, typer.Option("--background")] = "#151B24",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Generate a transparent local motion clip with retained source parameters."""
    from pydantic import ValidationError

    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        config = load_project_config(_selected_project(project, options.project))
        selected_font = font or (config.fonts[0] if config.fonts else None)
        if selected_font is None:
            raise UsageError("motion_font_required", "Declare a project font or pass --font.")
        spec = MotionSpec(
            template=template,
            text=text,
            secondary=secondary,
            font_path=str(selected_font),
            width=width or config.timeline.width,
            height=height or config.timeline.height,
            frame_rate=config.timeline.frame_rate,
            duration_us=duration_us,
            enter_us=enter_us,
            exit_us=exit_us,
            accent=accent,
            foreground=foreground,
            background=background,
        )
        result = build_motion(
            config,
            spec,
            dry_run=options.dry_run,
            progress=None if options.quiet else _emit_progress,
        )
    except ValidationError:
        _fail(
            UsageError(
                "motion_spec_invalid",
                "Motion layout, timing or palette is outside supported bounds.",
            ),
            command="motion build",
            json_output=machine,
        )
        return
    except InterviewEditError as error:
        _fail(error, command="motion build", json_output=machine)
        return
    except OSError:
        _fail(
            PathSafetyError("motion_io_failed", "Could not read or write motion resources."),
            command="motion build",
            json_output=machine,
        )
        return
    _emit_motion(result, "motion build", machine)


@motion_app.command("edit")
def motion_edit_command(
    ctx: typer.Context,
    asset: Annotated[Path, typer.Option("--asset")],
    project: Annotated[Path | None, typer.Option("--project")] = None,
    text: Annotated[str | None, typer.Option("--text")] = None,
    secondary: Annotated[str | None, typer.Option("--secondary")] = None,
    template: Annotated[
        Literal["callout", "lower_third", "chapter"] | None, typer.Option("--template")
    ] = None,
    duration_us: Annotated[
        int | None, typer.Option("--duration-us", min=800_000, max=10_000_000)
    ] = None,
    enter_us: Annotated[int | None, typer.Option("--enter-us", min=0, max=2_000_000)] = None,
    exit_us: Annotated[int | None, typer.Option("--exit-us", min=0, max=2_000_000)] = None,
    accent: Annotated[str | None, typer.Option("--accent")] = None,
    foreground: Annotated[str | None, typer.Option("--foreground")] = None,
    background: Annotated[str | None, typer.Option("--background")] = None,
    font: Annotated[Path | None, typer.Option("--font")] = None,
    width: Annotated[int | None, typer.Option("--width", min=320, max=3840)] = None,
    height: Annotated[int | None, typer.Option("--height", min=180, max=3840)] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Retain old motion assets and generate a new asset after source edits."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        config = load_project_config(_selected_project(project, options.project))
        values = {
            key: value
            for key, value in dict(
                text=text,
                secondary=secondary,
                template=template,
                duration_us=duration_us,
                enter_us=enter_us,
                exit_us=exit_us,
                accent=accent,
                foreground=foreground,
                background=background,
                font_path=str(font) if font is not None else None,
                width=width,
                height=height,
            ).items()
            if value is not None
        }
        result = revise_motion(
            config,
            asset,
            values,
            dry_run=options.dry_run,
            progress=None if options.quiet else _emit_progress,
        )
    except InterviewEditError as error:
        _fail(error, command="motion edit", json_output=machine)
        return
    except OSError:
        _fail(
            PathSafetyError("motion_io_failed", "Could not read or write motion resources."),
            command="motion edit",
            json_output=machine,
        )
        return
    _emit_motion(result, "motion edit", machine)


@motion_app.command("verify")
def motion_verify_command(
    ctx: typer.Context,
    asset: Annotated[Path, typer.Option("--asset")],
    project: Annotated[Path | None, typer.Option("--project")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    machine = json_output or _options(ctx).json_output
    try:
        config = load_project_config(_selected_project(project, _options(ctx).project))
        _, manifest = verify_motion(config, asset)
    except InterviewEditError as error:
        _fail(error, command="motion verify", json_output=machine)
        return
    emit(
        JsonEnvelope(
            ok=True,
            command="motion verify",
            data={"assetId": manifest.asset_id, "packageValidation": "passed"},
        ),
        json_output=machine,
        human_lines=["Motion asset validation passed."],
    )


@cutlist_app.command("motion")
def cutlist_motion_command(
    ctx: typer.Context,
    item: Annotated[str, typer.Option("--item")],
    asset: Annotated[Path, typer.Option("--asset")],
    project: Annotated[Path | None, typer.Option("--project")] = None,
    cutlist: Annotated[Path | None, typer.Option("--cutlist")] = None,
    start_us: Annotated[int, typer.Option("--start-us", min=0)] = 0,
    duration_us: Annotated[int | None, typer.Option("--duration-us", min=1)] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        config, path, document, root = _editing_context(options, project, cutlist)
        result = attach_motion(
            config,
            document,
            path,
            item_id=item,
            asset_path=asset,
            start_us=start_us,
            duration_us=duration_us,
            output=output,
            dry_run=options.dry_run,
        )
    except InterviewEditError as error:
        _fail(error, command="cutlist motion", json_output=machine)
        return
    _emit_revision(result, "cutlist motion", root, machine)


@cutlist_app.command("color")
def cutlist_color_command(
    ctx: typer.Context,
    asset: Annotated[str, typer.Option("--asset")],
    project: Annotated[Path | None, typer.Option("--project")] = None,
    cutlist: Annotated[Path | None, typer.Option("--cutlist")] = None,
    brightness: Annotated[float | None, typer.Option("--brightness", min=-0.15, max=0.15)] = None,
    contrast: Annotated[float | None, typer.Option("--contrast", min=0.75, max=1.25)] = None,
    gamma: Annotated[float | None, typer.Option("--gamma", min=0.75, max=1.25)] = None,
    saturation: Annotated[float | None, typer.Option("--saturation", min=0, max=1.5)] = None,
    reset: Annotated[bool, typer.Option("--reset")] = False,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Write a source-specific SDR correction revision with finite, bounded parameters."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        config, path, document, root = _editing_context(options, project, cutlist)
        values = {
            name: value
            for name, value in dict(
                brightness=brightness, contrast=contrast, gamma=gamma, saturation=saturation
            ).items()
            if value is not None
        }
        result = set_source_color(
            config,
            document,
            path,
            asset_id=asset,
            values=values,
            reset=reset,
            output=output,
            dry_run=options.dry_run,
        )
    except InterviewEditError as error:
        _fail(error, command="cutlist color", json_output=machine)
        return
    _emit_revision(result, "cutlist color", root, machine)


@review_app.command("color")
def review_color_command(
    ctx: typer.Context,
    asset: Annotated[str, typer.Option("--asset")],
    project: Annotated[Path | None, typer.Option("--project")] = None,
    cutlist: Annotated[Path | None, typer.Option("--cutlist")] = None,
    reference: Annotated[str | None, typer.Option("--reference")] = None,
    in_us: Annotated[int, typer.Option("--in-us", min=0)] = 0,
    out_us: Annotated[int | None, typer.Option("--out-us", min=1)] = None,
    samples: Annotated[int, typer.Option("--samples", min=2, max=8)] = 4,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Create an original/corrected comparison and numerical pixel statistics for an SDR source."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected = _selected_project(project, options.project)
        config = load_project_config(selected)
        root = config_path_for(selected).parent
        path = resolve_cutlist_path(root, cutlist) if cutlist else None
        result = review_color(
            config,
            asset_id=asset,
            start_us=in_us,
            end_us=out_us,
            reference_id=reference,
            cutlist_path=path,
            samples=samples,
            dry_run=options.dry_run,
        )
    except InterviewEditError as error:
        _fail(error, command="review color", json_output=machine)
        return
    except OSError:
        _fail(
            PathSafetyError("color_io_failed", "Could not read or write color evidence."),
            command="review color",
            json_output=machine,
        )
        return
    report = result.report
    emit(
        JsonEnvelope(
            ok=True,
            command="review color",
            data={
                "reviewPath": str(result.path),
                "sampleCount": result.count,
                "dryRun": result.dry_run,
                "qualityVerified": False,
                "correctionStatus": report.correction_status if report else "planned",
                "correction": report.correction.model_dump() if report else None,
                "before": report.before.model_dump() if report else None,
                "after": report.after.model_dump() if report else None,
            },
            artifacts=[]
            if result.dry_run
            else [ArtifactReference(kind="color-review", path=str(result.path))],
            warnings=[
                WarningPayload(
                    code=code,
                    message="Inspect color evidence and scene intent before applying changes.",
                )
                for code in result.warnings
            ],
        ),
        json_output=machine,
        human_lines=[
            f"{'Would create' if result.dry_run else 'Created'} color review: {result.path}"
        ],
    )


@cutlist_app.command("audio")
def cutlist_audio_command(
    ctx: typer.Context,
    project: Annotated[Path | None, typer.Option("--project")] = None,
    cutlist: Annotated[Path | None, typer.Option("--cutlist")] = None,
    edge_fade_us: Annotated[int, typer.Option("--edge-fade-us", min=0, max=50_000)] = 5_000,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Write a revision with bounded audio smoothing at discontinuous source joins."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        config, path, document, root = _editing_context(options, project, cutlist)
        result = set_audio_policy(
            config,
            document,
            path,
            edge_fade_us=edge_fade_us,
            output=output,
            dry_run=options.dry_run,
        )
    except InterviewEditError as error:
        _fail(error, command="cutlist audio", json_output=machine)
        return
    _emit_revision(result, "cutlist audio", root, machine)


def _emit_review(result: ReviewResult, command: str, machine: bool) -> None:
    emit(
        JsonEnvelope(
            ok=True,
            command=command,
            data={
                "reviewPath": str(result.path),
                "entryCount": result.count,
                "dryRun": result.dry_run,
                "listeningVerified": False,
            },
            artifacts=[]
            if result.dry_run
            else [ArtifactReference(kind="editorial-review", path=str(result.path))],
            warnings=[
                WarningPayload(
                    code="review_contains_content",
                    message="Review files contain text/images/audio; observe project privacy mode.",
                ),
                *[
                    WarningPayload(
                        code=code,
                        message="Review report includes evidence limits; inspect its warnings.",
                    )
                    for code in result.warnings
                ],
            ],
        ),
        json_output=machine,
        human_lines=[f"{'Would create' if result.dry_run else 'Created'} review: {result.path}"],
    )


@review_app.command("transcript")
def review_transcript_command(
    ctx: typer.Context,
    project: Annotated[Path | None, typer.Option("--project")] = None,
    asset: Annotated[
        list[str] | None,
        typer.Option(
            "--asset", help="Repeat for selected assets; defaults to transcribed sources."
        ),
    ] = None,
    pause_us: Annotated[int, typer.Option("--pause-us", min=1, max=5_000_000)] = 500_000,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Create a source-linked phrase reading view without exposing text in CLI output."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        config = load_project_config(_selected_project(project, options.project))
        result = phrase_view(config, asset_ids=asset, pause_us=pause_us, dry_run=options.dry_run)
    except InterviewEditError as error:
        _fail(error, command="review transcript", json_output=machine)
        return
    except OSError:
        _fail(
            PathSafetyError("review_io_failed", "Could not read or write review evidence."),
            command="review transcript",
            json_output=machine,
        )
        return
    _emit_review(result, "review transcript", machine)


@review_app.command("timeline")
def review_timeline_command(
    ctx: typer.Context,
    focus_us: Annotated[int, typer.Option("--focus-us", min=0)],
    project: Annotated[Path | None, typer.Option("--project")] = None,
    asset: Annotated[str | None, typer.Option("--asset")] = None,
    run: Annotated[str | None, typer.Option("--run")] = None,
    window_us: Annotated[int, typer.Option("--window-us", min=1, max=5_000_000)] = 1_500_000,
    frames: Annotated[int, typer.Option("--frames", min=2, max=16)] = 8,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Review source or rendered cut windows with filmstrip, PCM waveform and word timing."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        config = load_project_config(_selected_project(project, options.project))
        result = timeline_review(
            config,
            asset_id=asset,
            run_id=run,
            focus_us=focus_us,
            window_us=window_us,
            frame_count=frames,
            dry_run=options.dry_run,
        )
    except InterviewEditError as error:
        _fail(error, command="review timeline", json_output=machine)
        return
    except OSError:
        _fail(
            PathSafetyError("review_io_failed", "Could not read or write review evidence."),
            command="review timeline",
            json_output=machine,
        )
        return
    _emit_review(result, "review timeline", machine)


@cutlist_app.command("speech-check")
def cutlist_speech_check_command(
    ctx: typer.Context,
    project: Annotated[Path | None, typer.Option("--project")] = None,
    cutlist: Annotated[Path | None, typer.Option("--cutlist")] = None,
    item: Annotated[str | None, typer.Option("--item")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect transcript word boundaries without writing or exposing recognized text."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        config, _, document, _ = _editing_context(options, project, cutlist)
        data = check_speech(config, document, item)
    except InterviewEditError as error:
        _fail(error, command="cutlist speech-check", json_output=machine)
        return
    warnings = (
        [
            WarningPayload(
                code="speech_timing_unavailable",
                message="Some items have no usable word timing; listening is still required.",
                details={"itemIds": data["unverifiedItemIds"]},
            )
        ]
        if data["unverifiedItemIds"]
        else []
    )
    envelope = JsonEnvelope(
        ok=data["ok"],
        command="cutlist speech-check",
        data=data,
        warnings=warnings,
        error=None
        if data["ok"]
        else ErrorPayload(
            code="speech_boundary_invalid", message="One or more cuts land inside a word."
        ),
    )
    emit(
        envelope,
        json_output=machine,
        human_lines=[
            f"Checked items: {data['checkedItemCount']}; suspect cuts: {len(data['findings'])}",
            f"Unverified items: {len(data['unverifiedItemIds'])}; listening not verified.",
        ],
    )
    if not data["ok"]:
        raise typer.Exit(ExitCode.PREFLIGHT_FAILED)


@app.command("render")
def render_command(
    ctx: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    cutlist: Annotated[
        Path | None, typer.Option("--cutlist", help="Validated cut-list YAML path.")
    ] = None,
    act: Annotated[str | None, typer.Option("--act", help="Render one act ID.")] = None,
    item: Annotated[str | None, typer.Option("--item", help="Render one item ID.")] = None,
    context_items: Annotated[
        int,
        typer.Option(
            "--context-items",
            min=0,
            max=2,
            help="Neighbor items on each side of --item; preview only.",
        ),
    ] = 0,
    profile: Annotated[
        str | None,
        typer.Option("--profile", help="Configured preview or master render profile."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Output path inside the configured artifact root."),
    ] = None,
    resume: Annotated[
        bool, typer.Option("--resume", help="Reuse checksum-validated item caches.")
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Rebuild item caches and replace output atomically."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """Render a full cut-list, one act, or one item after strict preflight validation."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected = _selected_project(project, options.project)
        if cutlist is None:
            raise UsageError("cutlist_required", "Provide a cut-list with --cutlist PATH.")
        project_root = config_path_for(selected).parent
        config = load_project_config(selected)
        cutlist_path = resolve_cutlist_path(project_root, cutlist)
        document = load_cutlist(cutlist_path)
        result = render_cutlist(
            RenderRequest(
                config=config,
                project_root=project_root,
                cutlist=document,
                cutlist_path=cutlist_path,
                act_id=act,
                item_id=item,
                context_items=context_items,
                profile_name=profile,
                output=output,
                resume=resume,
                force=force or options.force,
                dry_run=options.dry_run,
            ),
            progress=None if options.quiet else _emit_progress,
        )
    except InterviewEditError as error:
        _fail(error, command="render", json_output=machine)
        return

    artifacts = [
        ArtifactReference(kind="render-cache", path=entry.path)
        for entry in result.cache
        if entry.path
    ]
    if result.output is not None:
        artifacts.append(ArtifactReference(kind="render", path=result.output.path))
    if result.manifest_path is not None:
        artifacts.append(ArtifactReference(kind="render-run", path=str(result.manifest_path)))
    envelope = JsonEnvelope(
        ok=True,
        command="render",
        runId=result.run_id,
        data={
            "outputPath": str(result.output_path),
            "output": result.output.model_dump(mode="json") if result.output else None,
            "manifestPath": str(result.manifest_path) if result.manifest_path else None,
            "cache": [entry.model_dump(mode="json") for entry in result.cache],
            "dryRun": result.dry_run,
        },
        artifacts=artifacts,
        next=[
            f"interview-edit cutlist validate --project {shlex.quote(str(project_root))} "
            f"--cutlist {shlex.quote(str(cutlist_path))}"
        ],
    )
    action = "Would render" if result.dry_run else "Rendered"
    emit(
        envelope,
        json_output=machine,
        human_lines=[
            f"{action}: {result.output_path}",
            "Item cache: " + ", ".join(f"{entry.item_id}={entry.state}" for entry in result.cache),
            f"Run manifest: {result.manifest_path or 'dry-run'}",
        ],
    )


@app.command("qc")
def qc_command(
    ctx: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    run: Annotated[
        str | None,
        typer.Option("--run", help="Render run ID; defaults to the latest successful run."),
    ] = None,
    policy: Annotated[
        QCPolicy,
        typer.Option("--policy", help="QC policy: preview or release."),
    ] = QCPolicy.PREVIEW,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """Inspect one successful render and write checksum-bearing QC evidence."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected = _selected_project(project, options.project)
        project_root = config_path_for(selected).parent
        config = load_project_config(selected)
        result = run_qc(
            QCRequest(
                config=config,
                project_root=project_root,
                run_id=run,
                policy=policy,
                dry_run=options.dry_run,
            )
        )
    except InterviewEditError as error:
        _fail(error, command="qc", json_output=machine)
        return

    blocking_count = sum(
        finding.severity is QCFindingSeverity.BLOCKING for finding in result.report.findings
    )
    error_count = sum(
        finding.severity is QCFindingSeverity.ERROR for finding in result.report.findings
    )
    warnings = [
        WarningPayload(code=finding.code, message=finding.message, details=finding.details)
        for finding in result.report.findings
        if finding.severity is QCFindingSeverity.WARNING
    ]
    artifacts = []
    if result.report_path is not None:
        artifacts.append(ArtifactReference(kind="qc-report", path=str(result.report_path)))
    if result.checksum_path is not None:
        artifacts.append(ArtifactReference(kind="qc-checksum", path=str(result.checksum_path)))
    artifacts.extend(
        ArtifactReference(kind="qc-evidence", path=evidence.path)
        for evidence in result.report.evidence
    )
    passed = result.report.state in {"planned", "passed"}
    error_payload = None
    if not passed:
        error_payload = ErrorPayload(
            code="qc_failed",
            message="QC found blocking or error findings.",
            details={
                "reportPath": str(result.report_path) if result.report_path else None,
                "blockingCount": blocking_count,
                "errorCount": error_count,
            },
        )
    envelope = JsonEnvelope(
        ok=passed,
        command="qc",
        runId=result.report.run_id,
        data={
            "report": result.report.model_dump(mode="json"),
            "reportPath": str(result.report_path) if result.report_path else None,
            "dryRun": result.dry_run,
        },
        warnings=warnings,
        artifacts=artifacts,
        error=error_payload,
    )
    action = "Would inspect" if result.dry_run else "QC"
    emit(
        envelope,
        json_output=machine,
        human_lines=[
            f"{action}: {result.report.run_id}",
            f"Policy: {result.report.policy.value}; state: {result.report.state}",
            f"Findings: blocking={blocking_count}; error={error_count}; warnings={len(warnings)}",
            f"Report: {result.report_path or 'dry-run'}",
        ],
    )
    if not passed:
        raise typer.Exit(ExitCode.PREFLIGHT_FAILED)


@version_app.command("freeze")
def version_freeze_command(
    ctx: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    run: Annotated[
        str | None, typer.Option("--run", help="Successful master render run ID.")
    ] = None,
    approve: Annotated[
        bool,
        typer.Option("--approve", help="Record separate explicit approval to freeze this version."),
    ] = False,
    note: Annotated[
        str | None,
        typer.Option("--note", help="Short release note stored with the frozen version."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """Freeze a successful master only after current passing release QC."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected = _selected_project(project, options.project)
        if run is None:
            raise UsageError(
                "render_run_required", "Provide the approved master run with --run ID."
            )
        project_root = config_path_for(selected).parent
        config = load_project_config(selected)
        result = freeze_version(
            FreezeRequest(
                config=config,
                project_root=project_root,
                run_id=run,
                approved=approve,
                note=note,
                dry_run=options.dry_run,
            )
        )
    except InterviewEditError as error:
        _fail(error, command="version freeze", json_output=machine)
        return

    envelope = JsonEnvelope(
        ok=True,
        command="version freeze",
        runId=result.manifest.source_run_id,
        data={
            "version": result.manifest.model_dump(mode="json"),
            "versionPath": str(result.version_path),
            "dryRun": result.dry_run,
        },
        artifacts=[]
        if result.dry_run
        else [ArtifactReference(kind="frozen-version", path=str(result.version_path))],
        next=[
            f"interview-edit version verify --project {shlex.quote(str(project_root))} "
            f"{result.manifest.version_id}"
        ],
    )
    emit(
        envelope,
        json_output=machine,
        human_lines=[
            f"{'Would freeze' if result.dry_run else 'Frozen'}: {result.manifest.version_id}",
            f"Master run: {result.manifest.source_run_id}",
            f"Release QC: {result.manifest.source_report_id}",
            f"Version path: {result.version_path}",
        ],
    )


@version_app.command("list")
def version_list_command(
    ctx: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """List frozen versions without reading their content-bearing inputs."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected = _selected_project(project, options.project)
        config = load_project_config(selected)
        versions = list_versions(config)
    except InterviewEditError as error:
        _fail(error, command="version list", json_output=machine)
        return

    envelope = JsonEnvelope(
        ok=True,
        command="version list",
        data={"versions": [version.model_dump(mode="json") for version in versions]},
    )
    lines = [f"Frozen versions: {len(versions)}"]
    lines.extend(f"{version.version_id}: {version.source_run_id}" for version in versions)
    emit(envelope, json_output=machine, human_lines=lines)


@version_app.command("show")
def version_show_command(
    ctx: typer.Context,
    version_id: Annotated[str, typer.Argument(help="Frozen version ID such as v0001.")],
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """Show one frozen version manifest without opening copied content files."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected = _selected_project(project, options.project)
        config = load_project_config(selected)
        version, version_path = load_version(config, version_id)
    except InterviewEditError as error:
        _fail(error, command="version show", json_output=machine)
        return

    emit(
        JsonEnvelope(
            ok=True,
            command="version show",
            data={"version": version.model_dump(mode="json"), "versionPath": str(version_path)},
            artifacts=[
                ArtifactReference(kind="version-manifest", path=str(version_path / "version.json"))
            ],
        ),
        json_output=machine,
        human_lines=[
            f"Version: {version.version_id}",
            f"Master run: {version.source_run_id}",
            f"Release QC: {version.source_report_id}",
            f"Files: {len(version.files)}",
        ],
    )


@version_app.command("verify")
def version_verify_command(
    ctx: typer.Context,
    version_id: Annotated[str, typer.Argument(help="Frozen version ID such as v0001.")],
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Editing project directory or configuration file."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit one JSON document.")] = False,
) -> None:
    """Verify every declared file and reject extra payloads in a frozen version."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        selected = _selected_project(project, options.project)
        config = load_project_config(selected)
        verification = verify_version(config, version_id)
    except InterviewEditError as error:
        _fail(error, command="version verify", json_output=machine)
        return

    passed = verification.state == "passed"
    error_payload = None
    if not passed:
        error_payload = ErrorPayload(
            code="version_verification_failed",
            message="Frozen version contains missing, modified, or unexpected files.",
            details={"issueCount": len(verification.issues), "versionId": version_id},
        )
    emit(
        JsonEnvelope(
            ok=passed,
            command="version verify",
            data={"verification": verification.model_dump(mode="json")},
            error=error_payload,
        ),
        json_output=machine,
        human_lines=[
            f"Version: {version_id}",
            f"Verification: {verification.state}",
            f"Checked files: {verification.checked_file_count}",
        ],
    )
    if not passed:
        raise typer.Exit(ExitCode.PREFLIGHT_FAILED)


@export_app.command("jianying")
def jianying_export_command(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help="Name for the new editable draft.")],
    project: Annotated[Path | None, typer.Option("--project")] = None,
    cutlist: Annotated[Path | None, typer.Option("--cutlist")] = None,
    target: Annotated[Literal["macos", "windows", "both"], typer.Option("--platform")] = "both",
    bundle_media: Annotated[
        bool,
        typer.Option(
            "--bundle-media/--reference-media",
            help="Copy original media/fonts for a portable editable project.",
        ),
    ] = True,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume",
            help="Reuse complete cached media copies; requires extra disk space.",
        ),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Create an experimental editable Jianying draft, never a flattened video."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        config, path, document, _ = _editing_context(options, project, cutlist)
        result = export_jianying(
            config,
            document,
            path,
            name=name,
            target=target,
            bundle_media=bundle_media,
            dry_run=options.dry_run,
            resume=resume,
            progress=None if options.quiet else _emit_progress,
        )
    except InterviewEditError as error:
        _fail(error, command="export jianying", json_output=machine)
        return
    except OSError:
        _fail(
            PathSafetyError("jianying_io_failed", "Could not read or write draft resources."),
            command="export jianying",
            json_output=machine,
        )
        return
    emit(
        JsonEnvelope(
            ok=True,
            command="export jianying",
            data={
                "draftPath": str(result.draft_path),
                "platform": target,
                "bundledMedia": bundle_media,
                "resourceBytes": result.resource_bytes,
                "cachedResources": result.cached_resources,
                "dryRun": result.dry_run,
                "nativeValidation": "not_run",
                "exportId": result.manifest.export_id if result.manifest else None,
            },
            warnings=[
                WarningPayload(
                    code="jianying_client_unverified",
                    message="Native app import, editing and rendering have not been verified.",
                ),
                WarningPayload(
                    code="jianying_style_approximation",
                    message="Review native text/audio; CLI master processing is not applied.",
                ),
            ],
            artifacts=[]
            if result.dry_run
            else [ArtifactReference(kind="jianying-draft", path=str(result.draft_path))],
            next=["interview-edit jianying doctor --json"],
        ),
        json_output=machine,
        human_lines=[
            f"{'Would export' if result.dry_run else 'Exported'} draft: {result.draft_path}",
            "Native app validation: not run; open and review it in Jianying.",
        ],
    )


@jianying_app.command("doctor")
def jianying_doctor_command(
    ctx: typer.Context,
    draft_root: Annotated[Path | None, typer.Option("--draft-root")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Check the local client and draft location without installation or network use."""
    try:
        data = inspect_jianying(draft_root=draft_root) if draft_root else inspect_jianying()
    except InterviewEditError as error:
        _fail(
            error, command="jianying doctor", json_output=json_output or _options(ctx).json_output
        )
        return
    ok = data["installed"]
    emit(
        JsonEnvelope(
            ok=ok,
            command="jianying doctor",
            data=data,
            error=None
            if ok
            else ErrorPayload(
                code="jianying_missing", message="Jianying is not installed in a detected location."
            ),
        ),
        json_output=json_output or _options(ctx).json_output,
        human_lines=[f"Jianying installed: {ok}", f"Draft location: {data['draftRoot']}"],
    )
    if not ok:
        raise typer.Exit(ExitCode.DEPENDENCY_MISSING)


@jianying_app.command("open")
def jianying_open_command(
    ctx: typer.Context,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Launch the detected client; select the installed draft in its project list."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        data = launch_jianying(dry_run=options.dry_run)
    except InterviewEditError as error:
        _fail(error, command="jianying open", json_output=machine)
        return
    emit(
        JsonEnvelope(
            ok=True,
            command="jianying open",
            data=data,
            warnings=[
                WarningPayload(
                    code="jianying_client_unverified",
                    message="Select the new draft and verify editable tracks in the app.",
                )
            ],
        ),
        json_output=machine,
        human_lines=[
            "Would launch Jianying."
            if options.dry_run
            else "Launch requested. Select the new draft in Jianying."
        ],
    )


@jianying_app.command("verify")
def jianying_verify_command(
    ctx: typer.Context,
    draft: Annotated[Path, typer.Option("--draft")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Check an unedited export package's files, timeline and input snapshot."""
    machine = json_output or _options(ctx).json_output
    try:
        manifest = verify_draft(draft)
    except InterviewEditError as error:
        _fail(error, command="jianying verify", json_output=machine)
        return
    emit(
        JsonEnvelope(
            ok=True,
            command="jianying verify",
            data={
                "exportId": manifest.export_id,
                "packageValidation": "passed",
                "nativeValidation": "not_run",
            },
        ),
        json_output=machine,
        human_lines=["Draft package validation passed; native app acceptance is still required."],
    )


@jianying_app.command("check-output")
def jianying_check_output_command(
    ctx: typer.Context,
    draft: Annotated[Path, typer.Option("--draft", help="Original unedited export package.")],
    video: Annotated[
        Path, typer.Option("--video", help="Completed video exported from the editor.")
    ],
    expected_duration_us: Annotated[
        int | None, typer.Option("--expected-duration-us", min=1)
    ] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Check decoding, dimensions, duration and audio; visual review is separate."""
    machine = json_output or _options(ctx).json_output
    try:
        result = check_output(draft, video, expected_duration_us=expected_duration_us)
    except InterviewEditError as error:
        _fail(error, command="jianying check-output", json_output=machine)
        return
    except OSError:
        _fail(
            PathSafetyError("jianying_io_failed", "Could not read the output or draft package."),
            command="jianying check-output",
            json_output=machine,
        )
        return
    emit(
        JsonEnvelope(
            ok=True,
            command="jianying check-output",
            data=result.model_dump(mode="json"),
            warnings=[
                WarningPayload(
                    code="jianying_visual_review_required",
                    message="App provenance, editability, picture and sound still need review.",
                )
            ],
        ),
        json_output=machine,
        human_lines=[
            "Output media checks passed. Review picture, subtitles and sound in the editor."
        ],
    )


@jianying_app.command("install")
def jianying_install_command(
    ctx: typer.Context,
    draft: Annotated[
        Path, typer.Option("--draft", help="Exported package, before editing in Jianying.")
    ],
    draft_root: Annotated[
        Path | None, typer.Option("--draft-root", help="Explicit existing native draft library.")
    ] = None,
    target: Annotated[Literal["macos", "windows"] | None, typer.Option("--platform")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Install a verified bundled package as a new local project without touching old drafts."""
    options = _options(ctx)
    machine = json_output or options.json_output
    try:
        if draft_root is None:
            client = inspect_jianying()
            if not client["installed"]:
                raise DependencyError(
                    "jianying_missing", "Install Jianying and create its draft directory first."
                )
            draft_root = Path(client["draftRoot"])
        result = install_draft(
            draft, draft_root, target or host_platform(), dry_run=options.dry_run
        )
    except InterviewEditError as error:
        _fail(error, command="jianying install", json_output=machine)
        return
    except OSError:
        _fail(
            PathSafetyError("jianying_io_failed", "Could not install the draft package."),
            command="jianying install",
            json_output=machine,
        )
        return
    emit(
        JsonEnvelope(
            ok=True,
            command="jianying install",
            data={
                "draftPath": str(result),
                "nativeValidation": "not_run",
                "dryRun": options.dry_run,
            },
            artifacts=[]
            if options.dry_run
            else [ArtifactReference(kind="installed-jianying-draft", path=str(result))],
            warnings=[
                WarningPayload(
                    code="jianying_client_unverified",
                    message="Open the new draft in Jianying and verify editable tracks.",
                )
            ],
        ),
        json_output=machine,
        human_lines=[
            f"{'Would install' if options.dry_run else 'Installed'}: {result}",
            "Open Jianying to review this new draft; restart it if the list is stale.",
        ],
    )


def main() -> None:
    try:
        app(prog_name="interview-edit")
    except KeyboardInterrupt:
        raise SystemExit(ExitCode.INTERRUPTED) from None


if __name__ == "__main__":
    main()
