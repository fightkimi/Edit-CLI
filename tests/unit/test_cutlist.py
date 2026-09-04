from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from interview_edit.cutlist.service import inspect_cutlist, load_cutlist
from interview_edit.errors import PreflightError
from interview_edit.models.cutlist import (
    Act,
    CutList,
    Overlay,
    Subtitle,
    TimelineItem,
)

ASSET_ID = "asset_0123456789abcdef01234567"


def test_cutlist_rejects_float_times_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TimelineItem.model_validate(
            {
                "item_id": "item_001",
                "kind": "primary",
                "source_id": ASSET_ID,
                "source_in_us": 0.5,
                "source_out_us": 1_000_000,
                "timeline_duration_us": 1_000_000,
                "unexpected": True,
            }
        )


def test_overlay_requires_kind_specific_source_and_exact_duration() -> None:
    with pytest.raises(ValidationError, match="source range must equal duration_us"):
        Overlay(
            overlay_id="overlay_001",
            kind="broll",
            start_us=0,
            duration_us=500_000,
            source_id=ASSET_ID,
            source_in_us=0,
            source_out_us=600_000,
        )


def test_inspect_omits_content_bearing_text(tmp_path: Path) -> None:
    document = CutList(
        project_id="prj_example01",
        acts=[
            Act(
                act_id="act_001",
                title="Secret act title",
                items=[
                    TimelineItem(
                        item_id="item_001",
                        kind="primary",
                        source_id=ASSET_ID,
                        source_in_us=0,
                        source_out_us=1_000_000,
                        timeline_duration_us=1_000_000,
                        subtitles=[
                            Subtitle(
                                subtitle_id="subtitle_001",
                                start_us=0,
                                duration_us=1_000_000,
                                text="private transcript text",
                            )
                        ],
                        notes="private editorial note",
                    )
                ],
            )
        ],
    )

    result = inspect_cutlist(document, cutlist_path=tmp_path / "cutlist.yaml")

    rendered = str(result)
    assert "private transcript text" not in rendered
    assert "private editorial note" not in rendered
    assert "Secret act title" not in rendered
    assert result["items"][0]["subtitleCount"] == 1


def test_load_cutlist_reports_schema_failure_as_preflight(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump({"schema_version": "1", "project_id": "bad"}))

    with pytest.raises(PreflightError) as error:
        load_cutlist(path)

    assert error.value.code == "cutlist_invalid"


def test_committed_json_schema_matches_runtime_model() -> None:
    path = Path(__file__).parents[2] / "docs" / "specs" / "cutlist-v1.schema.json"
    committed = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://guang.tech/schemas/interview-edit/cutlist-v1.schema.json",
        **CutList.model_json_schema(),
    }

    assert committed == expected
