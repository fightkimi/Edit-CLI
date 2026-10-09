from __future__ import annotations

import json

import pytest

from interview_edit.adapters.filesystem import sha256_file
from interview_edit.config.loader import load_project_config
from interview_edit.cutlist.editing import attach_motion
from interview_edit.cutlist.service import load_cutlist, serialize_cutlist
from interview_edit.errors import PreflightError
from interview_edit.export.jianying import export_jianying, verify_draft
from interview_edit.export.jianying_install import install_draft
from interview_edit.models.cutlist import ColorCorrection
from interview_edit.motion.service import build_motion, import_motion_spec, verify_motion
from tests.integration.test_jianying_export import project_cut as project_cut
from tests.integration.test_motion_workflow import spec


def test_native_effects_keep_motion_sources_and_color_on_visual_only(project_cut, tmp_path):
    project, path = project_cut
    config = load_project_config(project)
    built = build_motion(config, spec())
    doc = load_cutlist(path)
    doc.color_policy.by_source[doc.acts[0].items[0].source_id] = ColorCorrection(
        brightness=0.03, contrast=0.9, saturation=1.1
    )
    path.write_text(serialize_cutlist(doc), encoding="utf-8")
    revision = attach_motion(
        config, doc, path, item_id="item_001", asset_path=built.path, duration_us=800000
    )
    doc = load_cutlist(revision.output_path)
    exported = export_jianying(
        config, doc, revision.output_path, name="Native effects", native_effects=True
    )
    manifest = verify_draft(exported.draft_path)
    assert manifest.schema_version == "3"
    motion = next(iter(manifest.motion_assets.values()))
    assert (exported.draft_path / motion.resources["spec.json"]).read_bytes() == (
        built.path / "spec.json"
    ).read_bytes()
    content = json.loads((exported.draft_path / "draft_info.json").read_text(encoding="utf-8"))
    track = next(t for t in content["tracks"] if t["name"] == "动效")
    assert track["segments"][0]["source_timerange"] == {"start": 0, "duration": 800000}
    video = next(t for t in content["tracks"] if t["name"] == "主画面")["segments"][0]
    values = {
        g["property_type"]: g["keyframe_list"][0]["values"][0] for g in video["common_keyframes"]
    }
    assert values == pytest.approx(
        {"KFTypeBrightness": 0.03, "KFTypeContrast": -0.1, "KFTypeSaturation": 0.1}
    )
    audio = next(t for t in content["tracks"] if t["type"] == "audio")["segments"][0]
    assert audio["common_keyframes"] == []
    root = tmp_path / "native-library"
    root.mkdir()
    installed = install_draft(exported.draft_path, root, "windows")
    assert verify_draft(installed, native_root=installed).schema_version == "3"
    restored = import_motion_spec(
        config,
        exported.draft_path / motion.resources["spec.json"],
        font=exported.draft_path / motion.resources["font"],
    )
    assert verify_motion(config, restored.path)[0].text == motion.spec.text


def test_native_color_rehashed_parameter_mutation_fails(project_cut):
    project, path = project_cut
    doc = load_cutlist(path)
    doc.color_policy.by_source[doc.acts[0].items[0].source_id] = ColorCorrection(brightness=0.03)
    path.write_text(serialize_cutlist(doc), encoding="utf-8")
    result = export_jianying(
        load_project_config(project), doc, path, name="Color", target="windows", native_effects=True
    )
    entry = result.draft_path / "draft_content.json"
    data = json.loads(entry.read_text(encoding="utf-8"))
    group = data["tracks"][0]["segments"][0]["common_keyframes"][0]
    for point in group["keyframe_list"]:
        point["values"] = [0.04]
    entry.write_text(json.dumps(data), encoding="utf-8")
    manifest_path = result.draft_path / "export-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = next(f for f in manifest["files"] if f["relative_path"] == entry.name)
    record.update(size=entry.stat().st_size, sha256=sha256_file(entry))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError):
        verify_draft(result.draft_path)


def test_native_gamma_not_silently_mapped(project_cut):
    project, path = project_cut
    doc = load_cutlist(path)
    doc.color_policy.by_source[doc.acts[0].items[0].source_id] = ColorCorrection(gamma=1.1)
    path.write_text(serialize_cutlist(doc), encoding="utf-8")
    with pytest.raises(PreflightError) as error:
        export_jianying(load_project_config(project), doc, path, name="Gamma", native_effects=True)
    assert error.value.code == "jianying_gamma_unsupported"
