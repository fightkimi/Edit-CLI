from __future__ import annotations

import math
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import ValidationError

from interview_edit.adapters.filesystem import sha256_file
from interview_edit.adapters.media import probe_media
from interview_edit.adapters.motion import card, frame
from interview_edit.adapters.process import ProcessRunner, SubprocessRunner
from interview_edit.adapters.render import run_render_command
from interview_edit.config.models import ProjectConfig
from interview_edit.errors import PreflightError, UsageError
from interview_edit.models.motion import MotionFile, MotionManifest, MotionSpec
from interview_edit.project.layout import (
    artifact_path,
    atomic_write_text,
    canonical,
    validate_artifact_path,
)


@dataclass(frozen=True)
class MotionResult:
    path: Path
    manifest: MotionManifest | None
    spec: MotionSpec
    frame_count: int
    dry_run: bool


def verify_motion(config: ProjectConfig, path: Path) -> tuple[MotionSpec, MotionManifest]:
    root = validate_artifact_path(path, config.artifact_root)
    try:
        control = validate_artifact_path(root / "manifest.json", config.artifact_root)
        source = validate_artifact_path(root / "spec.json", config.artifact_root)
        if control.stat().st_size > 1024 * 1024 or source.stat().st_size > 256 * 1024:
            raise ValueError("motion control too large")
        manifest = MotionManifest.model_validate_json(control.read_text(encoding="utf-8"))
        spec = MotionSpec.model_validate_json(source.read_text(encoding="utf-8"))
        if (
            manifest.project_id != config.project_id
            or sha256_file(root / "spec.json") != manifest.spec_sha256
        ):
            raise ValueError("motion belongs to another project or spec changed")
        expected = set()
        for record in manifest.files:
            relative = PurePosixPath(record.relative_path)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "\\" in record.relative_path
                or record.relative_path in expected
            ):
                raise ValueError("motion file path invalid")
            file = validate_artifact_path(root / record.relative_path, config.artifact_root)
            if (
                not file.is_file()
                or file.stat().st_size != record.size
                or sha256_file(file) != record.sha256
            ):
                raise ValueError("motion file changed")
            expected.add(record.relative_path)
        actual = {
            p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() or p.is_symlink()
        }
        if expected != {"spec.json", "render.mov", "poster.png"} or actual != expected | {
            "manifest.json"
        }:
            raise ValueError("motion file inventory differs")
        rate = Fraction(spec.frame_rate)
        count = math.ceil(Fraction(spec.duration_us) * rate / 1_000_000)
        if (
            count != manifest.frame_count
            or abs(manifest.duration_us - round(Fraction(count * 1_000_000) / rate)) > 1
        ):
            raise ValueError("motion timing differs")
        if not (
            0 <= manifest.bounds[0] < manifest.bounds[2] <= spec.width
            and 0 <= manifest.bounds[1] < manifest.bounds[3] <= spec.height
        ):
            raise ValueError("motion geometry invalid")
        return spec, manifest
    except (OSError, ValueError, ValidationError) as exc:
        raise PreflightError(
            "motion_package_invalid", "Motion asset is missing, modified or invalid."
        ) from exc


def build_motion(
    config: ProjectConfig,
    spec: MotionSpec,
    *,
    dry_run: bool = False,
    runner: ProcessRunner | None = None,
    progress: Callable[[str], None] | None = None,
) -> MotionResult:
    spec = MotionSpec.model_validate(spec.model_dump())
    font = canonical(Path(spec.font_path))
    if not font.is_file():
        raise PreflightError("motion_font_required", "Motion needs a readable declared local font.")
    spec.font_path = str(font)
    font_hash = sha256_file(font)
    base, bounds = card(spec)
    rate = Fraction(spec.frame_rate)
    count = math.ceil(Fraction(spec.duration_us) * rate / 1_000_000)
    identifier = f"motion_{uuid4().hex}"
    final = artifact_path(config.artifact_root, "motion", identifier)
    if dry_run:
        return MotionResult(final, None, spec, count, True)
    final.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".motion-", dir=final.parent))
    active = runner or SubprocessRunner()
    try:
        frames = stage / "frames"
        frames.mkdir()
        for i in range(count):
            time_us = i * 1_000_000 * rate.denominator // rate.numerator
            frame(base, spec, time_us).save(frames / f"frame-{i:06d}.png")
            if progress is not None and (i % 10 == 0 or i == count - 1):
                progress(f"Motion frames: {i + 1}/{count}")
        # QTRLE argb preserves alpha; image2 timestamps derive from the declared rational rate.
        run_render_command(
            [
                "-nostdin",
                "-v",
                "error",
                "-framerate",
                spec.frame_rate,
                "-start_number",
                "0",
                "-i",
                str(frames / "frame-%06d.png"),
                "-frames:v",
                str(count),
                "-an",
                "-c:v",
                "qtrle",
                "-pix_fmt",
                "argb",
                "-y",
                str(stage / "render.mov"),
            ],
            active,
            purpose="render transparent motion",
        )
        metadata = probe_media(stage / "render.mov", active)
        video = metadata.video_stream
        expected_duration = round(Fraction(count * 1_000_000) / rate)
        if (
            video is None
            or video.codec_name != "qtrle"
            or video.pixel_format != "argb"
            or (video.width, video.height) != (spec.width, spec.height)
            or metadata.audio_streams
            or abs(metadata.duration_us - expected_duration) > 1
        ):
            raise PreflightError(
                "motion_render_invalid", "Motion render lost alpha, geometry or timing."
            )
        base.save(stage / "poster.png")
        shutil.rmtree(frames)
        atomic_write_text(stage / "spec.json", spec.model_dump_json(indent=2))
        files = [
            MotionFile(relative_path=p.name, size=p.stat().st_size, sha256=sha256_file(p))
            for p in sorted(stage.iterdir())
            if p.is_file()
        ]
        manifest = MotionManifest(
            asset_id=identifier,
            project_id=config.project_id,
            spec_sha256=sha256_file(stage / "spec.json"),
            font_sha256=font_hash,
            duration_us=metadata.duration_us,
            frame_count=count,
            bounds=bounds,
            files=files,
            created_at=datetime.now(UTC).isoformat(),
        )
        atomic_write_text(stage / "manifest.json", manifest.model_dump_json(indent=2))
        if sha256_file(font) != font_hash:
            raise PreflightError("motion_font_changed", "Motion font changed during generation.")
        verify_motion(config, stage)
        os.rename(stage, final)
        return MotionResult(final, manifest, spec, count, False)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def revise_motion(
    config: ProjectConfig,
    path: Path,
    values: Mapping[str, object],
    *,
    dry_run: bool = False,
    progress: Callable[[str], None] | None = None,
) -> MotionResult:
    spec, _ = verify_motion(config, path)
    if not values:
        raise UsageError("motion_values_required", "Provide at least one motion source change.")
    try:
        revised = MotionSpec.model_validate({**spec.model_dump(), **values})
    except ValidationError as exc:
        raise UsageError(
            "motion_values_invalid", "Motion values exceed supported layout/timing bounds."
        ) from exc
    return build_motion(config, revised, dry_run=dry_run, progress=progress)


def import_motion_spec(
    config: ProjectConfig,
    path: Path,
    *,
    font: Path | None = None,
    dry_run: bool = False,
    progress: Callable[[str], None] | None = None,
) -> MotionResult:
    try:
        with path.open("rb") as source:
            raw = source.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise ValueError("source too large")
        spec = MotionSpec.model_validate_json(raw)
    except (OSError, ValueError) as exc:
        raise PreflightError(
            "motion_source_invalid", "Select a bounded valid motion source specification."
        ) from exc
    if font is not None:
        spec.font_path = str(font)
    return build_motion(config, spec, dry_run=dry_run, progress=progress)
