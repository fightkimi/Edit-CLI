# M1 implementation plan

- Status: implemented and locally verified; see `docs/tests/m1-acceptance.md`
- Date: 2026-09-03

## Goal and acceptance

Provide an installable Python CLI with stable configuration and machine-output foundations. `init`, `doctor`, and `status` must work from outside the source tree, preserve source media, return documented exit codes, and have executable tests.

M1 does not ingest, transcribe, synchronize, render, run release QC, or freeze versions.

## Assumptions

- The public command remains `interview-edit` for V1.
- Python 3.12 is used for development; supported runtime floor is 3.11.
- V1 serves speech-led creator videos while keeping one primary spoken track as the first workflow.
- No open-source license is granted yet.
- Models and dependencies are downloaded only for an explicitly authorized development or user action.

## File-level work

| Files | Responsibility | Verification |
|---|---|---|
| `pyproject.toml`, `src/interview_edit/__init__.py`, `__main__.py` | package metadata and installed entry point | build wheel; install into isolated environment |
| `src/interview_edit/exit_codes.py`, `errors.py` | stable failure taxonomy | unit tests |
| `src/interview_edit/models/protocol.py`, `cli/output.py` | JSON envelope and stdout discipline | CLI JSON tests |
| `src/interview_edit/config/models.py`, `loader.py` | Pydantic configuration, YAML, environment priority | model and precedence tests |
| `src/interview_edit/project/layout.py`, `service.py` | safe initialization and atomic files | integration tests including boundary rejection |
| `src/interview_edit/doctor/service.py` | executable, codec, backend, model, path, and Skill checks | unit tests plus live doctor run |
| `src/interview_edit/status/service.py` | artifact-derived project status | integration tests |
| `src/interview_edit/cli/app.py` | thin Typer commands | help/init/status/doctor CLI tests |
| `.github/workflows/ci.yml` | Python 3.11/3.12 lint, type, test, and build checks | local command parity; remote run after push |
| `.agents/skills/interview-edit/` | Codex orchestration skeleton and references | skill quick validator |
| `docs/` | PRD, ADRs, public contracts, and evidence | manual review and link checks |

## Ordered execution

1. Establish documentation, rules, package metadata, and tests.
2. Implement configuration and project initialization.
3. Implement protocol output and CLI routing.
4. Implement environment doctor and artifact-derived status.
5. Fill and validate the project Skill.
6. Run static, unit, integration, build, and outside-source installation checks.

## Acceptance commands

```bash
uv sync --extra mlx --group dev
uv run ruff check .
uv run mypy src
uv run pytest
uv build

uv venv /private/tmp/interview-edit-wheel-venv --python 3.12
uv pip install --python /private/tmp/interview-edit-wheel-venv/bin/python dist/*.whl
cd /private/tmp
/private/tmp/interview-edit-wheel-venv/bin/interview-edit --help
```

A temporary media directory and project directory are then used to run `init`, `status --json`, and `doctor --json`. The Skill is checked with the bundled `quick_validate.py` validator.

## Stop conditions

Stop rather than silently changing the contract if implementation requires source-media writes, network upload, a hidden privacy default, a bypass of validation/QC gates, or direct source copying with unresolved licensing.
