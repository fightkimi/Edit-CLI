from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError

from interview_edit.config.models import ProjectConfig
from interview_edit.errors import UsageError

CONFIG_FILENAME = "interview-edit.yaml"


def config_path_for(project: Path) -> Path:
    expanded = project.expanduser()
    if expanded.name == CONFIG_FILENAME or expanded.suffix.lower() in {".yaml", ".yml"}:
        return expanded.resolve(strict=False)
    return (expanded / CONFIG_FILENAME).resolve(strict=False)


def _read_yaml_mapping(path: Path, *, required: bool) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise UsageError(
                "config_not_found",
                f"Project configuration not found: {path}",
                details={"path": str(path)},
            )
        return {}
    if not path.is_file():
        raise UsageError(
            "config_not_file",
            f"Configuration path is not a file: {path}",
            details={"path": str(path)},
        )
    try:
        loaded: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise UsageError(
            "config_read_failed",
            f"Could not read configuration: {path}",
            details={"path": str(path), "reason": str(exc)},
        ) from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise UsageError(
            "config_not_mapping",
            f"Configuration must contain a YAML mapping: {path}",
            details={"path": str(path)},
        )
    return cast(dict[str, Any], loaded)


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            merged[key] = _deep_merge(cast(dict[str, Any], existing), value)
        else:
            merged[key] = value
    return merged


def _user_config_path(environ: Mapping[str, str]) -> Path | None:
    explicit = environ.get("INTERVIEW_EDIT_USER_CONFIG")
    if explicit == "":
        return None
    if explicit:
        return Path(explicit).expanduser().resolve(strict=False)
    config_home = environ.get("XDG_CONFIG_HOME")
    base = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return (base / "interview-edit" / "config.yaml").resolve(strict=False)


def _environment_overrides(environ: Mapping[str, str]) -> dict[str, Any]:
    routes: dict[str, tuple[str, ...]] = {
        "INTERVIEW_EDIT_ARTIFACT_ROOT": ("artifact_root",),
        "INTERVIEW_EDIT_LANGUAGE": ("language",),
        "INTERVIEW_EDIT_PRIVACY_MODE": ("privacy_mode",),
        "INTERVIEW_EDIT_TRANSCRIPTION__BACKEND": ("transcription", "backend"),
        "INTERVIEW_EDIT_TRANSCRIPTION__DEVICE": ("transcription", "device"),
        "INTERVIEW_EDIT_TRANSCRIPTION__MODEL": ("transcription", "model"),
        "INTERVIEW_EDIT_TRANSCRIPTION__MODEL_SOURCE": ("transcription", "model_source"),
    }
    result: dict[str, Any] = {}
    for variable, route in routes.items():
        if variable not in environ:
            continue
        target = result
        for part in route[:-1]:
            nested = target.setdefault(part, {})
            target = cast(dict[str, Any], nested)
        target[route[-1]] = environ[variable]
    return result


def _resolve_config_paths(data: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    resolved = dict(data)
    artifact = resolved.get("artifact_root")
    if artifact is not None:
        artifact_path = Path(str(artifact)).expanduser()
        resolved_artifact = (
            base_dir / artifact_path if not artifact_path.is_absolute() else artifact_path
        )
        resolved["artifact_root"] = str(resolved_artifact.resolve(strict=False))

    roots = resolved.get("media_roots")
    if isinstance(roots, list):
        resolved_roots: list[str] = []
        for root in roots:
            root_path = Path(str(root)).expanduser()
            resolved_roots.append(
                str(
                    (base_dir / root_path if not root_path.is_absolute() else root_path).resolve(
                        strict=False
                    )
                )
            )
        resolved["media_roots"] = resolved_roots

    fonts = resolved.get("fonts")
    if isinstance(fonts, list):
        resolved["fonts"] = [
            str(
                (
                    base_dir / Path(str(font)).expanduser()
                    if not Path(str(font)).expanduser().is_absolute()
                    else Path(str(font)).expanduser()
                ).resolve(strict=False)
            )
            for font in fonts
        ]
    return resolved


def load_project_config(
    project: Path,
    *,
    environ: Mapping[str, str] | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
) -> ProjectConfig:
    environment = os.environ if environ is None else environ
    path = config_path_for(project)
    user_path = _user_config_path(environment)
    merged: dict[str, Any] = {}
    if user_path is not None:
        merged = _deep_merge(merged, _read_yaml_mapping(user_path, required=False))
    merged = _deep_merge(merged, _read_yaml_mapping(path, required=True))
    merged = _deep_merge(merged, _environment_overrides(environment))
    if cli_overrides:
        merged = _deep_merge(merged, cli_overrides)
    merged = _resolve_config_paths(merged, path.parent)
    try:
        return ProjectConfig.model_validate(merged)
    except ValidationError as exc:
        raise UsageError(
            "config_invalid",
            f"Project configuration is invalid: {path}",
            details={"path": str(path), "errors": exc.errors(include_url=False)},
        ) from exc


def serialize_project_config(config: ProjectConfig) -> str:
    data = config.model_dump(mode="json")
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
