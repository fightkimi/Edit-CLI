from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from interview_edit.adapters.filesystem import sha256_file
from interview_edit.config.models import ProjectConfig
from interview_edit.errors import PreflightError
from interview_edit.models.media import MediaAsset, ProxyManifest
from interview_edit.project.layout import artifact_path


@dataclass(frozen=True)
class ValidatedAudioProxy:
    path: Path
    sha256: str
    proxy_cache_key: str


def validated_audio_proxy(config: ProjectConfig, asset: MediaAsset) -> ValidatedAudioProxy:
    manifest_path = artifact_path(
        config.artifact_root, "proxies", f"{asset.asset_id}.manifest.json"
    )
    expected_path = artifact_path(config.artifact_root, "audio", f"{asset.asset_id}.wav")
    try:
        manifest = ProxyManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise PreflightError(
            "audio_proxy_required",
            "A valid audio proxy is required; run proxy build first.",
            details={"assetId": asset.asset_id, "manifestPath": str(manifest_path)},
        ) from exc
    if (
        manifest.asset_id != asset.asset_id
        or manifest.source_fingerprint != asset.fingerprint
        or manifest.source_full_hash != asset.full_hash
    ):
        raise PreflightError(
            "audio_proxy_stale",
            "The audio proxy does not match the current media index; rebuild proxies.",
            details={"assetId": asset.asset_id, "manifestPath": str(manifest_path)},
        )
    output = next(
        (
            item
            for item in manifest.outputs
            if item.kind == "audio" and Path(item.path) == expected_path
        ),
        None,
    )
    try:
        valid = (
            output is not None
            and expected_path.is_file()
            and expected_path.stat().st_size == output.size
            and sha256_file(expected_path) == output.sha256
        )
    except OSError:
        valid = False
    if not valid or output is None:
        raise PreflightError(
            "audio_proxy_invalid",
            "The indexed audio proxy is missing or fails checksum validation.",
            details={"assetId": asset.asset_id, "path": str(expected_path)},
        )
    return ValidatedAudioProxy(
        path=expected_path,
        sha256=output.sha256,
        proxy_cache_key=manifest.cache_key,
    )


def validated_video_proxy(config: ProjectConfig, asset: MediaAsset) -> Path:
    manifest_path = artifact_path(
        config.artifact_root, "proxies", f"{asset.asset_id}.manifest.json"
    )
    expected_path = artifact_path(config.artifact_root, "proxies", f"{asset.asset_id}.mp4")
    try:
        manifest = ProxyManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise PreflightError(
            "sync_visual_proxy_missing",
            "Visual sync evidence requires a valid video proxy for every selected camera.",
            details={"assetId": asset.asset_id, "manifestPath": str(manifest_path)},
        ) from exc
    output = next(
        (
            item
            for item in manifest.outputs
            if item.kind == "video" and Path(item.path) == expected_path
        ),
        None,
    )
    try:
        valid = (
            manifest.source_fingerprint == asset.fingerprint
            and manifest.source_full_hash == asset.full_hash
            and output is not None
            and expected_path.is_file()
            and expected_path.stat().st_size == output.size
            and sha256_file(expected_path) == output.sha256
        )
    except OSError:
        valid = False
    if not valid:
        raise PreflightError(
            "sync_visual_proxy_invalid",
            "A video proxy is missing, stale, or fails checksum validation.",
            details={"assetId": asset.asset_id, "path": str(expected_path)},
        )
    return expected_path
