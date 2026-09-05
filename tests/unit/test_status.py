from pathlib import Path

from interview_edit.config.models import ProjectConfig
from interview_edit.status.service import read_project_status


def test_render_status_ignores_item_caches_and_failed_run_manifests(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    artifacts = tmp_path / "artifacts"
    cache = artifacts / "renders" / "cache" / "items"
    runs = artifacts / "renders" / "runs"
    cache.mkdir(parents=True)
    runs.mkdir(parents=True)
    (cache / "cached.mp4").write_bytes(b"cache")
    (runs / "failed.json").write_text('{"state":"failed"}', encoding="utf-8")
    config = ProjectConfig(
        project_id="prj_example01",
        name="Status",
        media_roots=[media],
        artifact_root=artifacts,
        privacy_mode="strict",
    )

    before = read_project_status(config)
    (artifacts / "renders" / "published.mp4").write_bytes(b"published")
    after = read_project_status(config)

    assert before.stages["render"]["state"] == "missing"
    assert before.stages["render"]["validity"] == "missing"
    assert before.stages["render"]["fileCount"] == 0
    assert after.stages["render"]["state"] == "present"
    assert after.stages["render"]["validity"] == "invalid"
    assert after.stages["render"]["reasonCodes"] == ["successful_render_required"]
    assert after.stages["render"]["fileCount"] == 1
