from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from typer.testing import CliRunner

from interview_edit import __version__
from interview_edit.cli.app import app

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / ".agents" / "skills" / "interview-edit"
SKILL_PATH = SKILL_ROOT / "SKILL.md"
EVALS_PATH = SKILL_ROOT / "evals" / "evals.json"
CLI_REFERENCE = SKILL_ROOT / "references" / "cli-reference.md"
RUNNER = CliRunner()


def _frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(?P<yaml>.*?)\n---(?:\n|\Z)", text, flags=re.DOTALL)
    assert match is not None, "SKILL.md must start with YAML frontmatter"
    value = yaml.safe_load(match.group("yaml"))
    assert isinstance(value, dict)
    return value


def test_skill_metadata_matches_the_package() -> None:
    metadata = _frontmatter(SKILL_PATH)

    assert metadata["name"] == "interview-edit"
    assert "speech-led creator-video" in metadata["description"]
    assert "Do not use" in metadata["description"]
    assert metadata["metadata"]["version"] == __version__
    assert "Python 3.11+" in SKILL_PATH.read_text(encoding="utf-8")


def test_every_local_markdown_reference_exists_inside_the_skill() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    links = re.findall(r"\[[^\]]+\]\(([^)]+\.md)\)", text)

    assert links
    root = SKILL_ROOT.resolve()
    for link in links:
        target = (SKILL_ROOT / link).resolve()
        assert target.is_relative_to(root), f"reference escapes the Skill package: {link}"
        assert target.is_file(), f"missing Skill reference: {link}"


def test_eval_corpus_covers_required_workflows_and_near_misses() -> None:
    payload = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
    evals = payload["evals"]

    assert payload["skill_name"] == "interview-edit"
    assert len(evals) >= 8
    assert len({case["id"] for case in evals}) == len(evals)
    for case in evals:
        assert isinstance(case["id"], int)
        assert case["prompt"].strip()
        assert case["expected_output"].strip()
        assert isinstance(case["files"], list)
        assert len(case["expectations"]) >= 2

    corpus = json.dumps(payload, ensure_ascii=False).lower()
    for required in (
        "status --project",
        "cutlist validate",
        "render --profile preview",
        "qc --policy preview",
        "render --profile master",
        "qc --policy release",
        "version freeze",
        "version verify",
    ):
        assert required in corpus

    near_misses = [case for case in evals if case["expected_output"].startswith("Do not activate")]
    assert len(near_misses) >= 3


def test_documented_command_paths_exist_in_the_installed_cli_contract() -> None:
    command_paths = [
        ("init",),
        ("doctor",),
        ("status",),
        ("ingest",),
        ("proxy", "build"),
        ("transcribe",),
        ("sync",),
        ("cutlist", "scaffold"),
        ("cutlist", "inspect"),
        ("cutlist", "audio"),
        ("cutlist", "color"),
        ("review", "color"),
        ("review", "transcript"),
        ("review", "timeline"),
        ("cutlist", "validate"),
        ("render",),
        ("qc",),
        ("version", "freeze"),
        ("version", "list"),
        ("version", "show"),
        ("version", "verify"),
    ]
    reference = CLI_REFERENCE.read_text(encoding="utf-8")

    for path in command_paths:
        result = RUNNER.invoke(app, [*path, "--help"])
        assert result.exit_code == 0, f"missing CLI path {' '.join(path)}: {result.output}"
        documented = rf"interview-edit(?: \[GLOBAL OPTIONS\])? {re.escape(' '.join(path))}"
        assert re.search(documented, reference), f"undocumented CLI path: {' '.join(path)}"


def test_skill_keeps_master_and_freeze_as_separate_approvals() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")
    recovery = (SKILL_ROOT / "references" / "review-and-recovery.md").read_text(encoding="utf-8")

    assert "A preview approval authorizes neither a master nor a freeze" in skill
    assert "freeze approval binds to the exact successful master run" in skill
    assert "After two equivalent failures" in recovery
