# M7 synthetic creator matrix and real-media intake plan

- Status: complete; synthetic acceptance passed, real-media gate remains pending
- Date: 2026-09-04

## Goal

Use deterministic, locally generated media to keep validating the V1 execution path while no real
creator footage is available. Prepare a repeatable intake gate for the later real-media Beta.

Synthetic evidence is limited to mechanics: schema handling, source safety, proxy generation,
preview rendering, QC execution, and JSON contracts. It does not establish transcript accuracy,
editorial quality, production-codec compatibility, long-media performance, or disk-pressure
behavior.

## Confirmed scope

1. Exercise interview, talking-head, tutorial, review, and vlog cut-list structures against the
   installed FFmpeg/FFprobe toolchain.
2. Generate all temporary MP4 inputs during tests and keep media, render outputs, and QC evidence
   outside Git.
3. Run each scenario through ingest, proxy, `cutlist validate`, preview `render`, and preview `qc`.
4. Assert that source SHA-256 values remain unchanged throughout the matrix.
5. Record a real-media intake checklist with privacy, source integrity, format, storage, editorial,
   transcription, preview, and authorization gates.

## Public-contract impact

None. The cut-list v1 contract already permits project-owned `content_role` labels and explicitly
documents the five target creator formats. M7 adds characterization and acceptance coverage rather
than a new CLI command, schema field, or content-specific execution branch.

## File-level implementation

| Files | Responsibility | Verification |
|---|---|---|
| `tests/integration/test_creator_format_matrix.py` | generated-media matrix for five creator formats | focused pytest, then full suite |
| `docs/tests/real-media-beta-checklist.md` | safe handoff when representative footage arrives | documentation review |
| `docs/tests/m7-synthetic-creator-matrix.md` | actual environment and command evidence | fresh command output |
| `README.md` | discoverability for the M7 evidence and intake gate | link check by review |

## Acceptance commands

```bash
INTERVIEW_EDIT_CI=1 uv run pytest tests/integration/test_creator_format_matrix.py -q
uv run ruff check .
uv run mypy src
INTERVIEW_EDIT_CI=1 uv run pytest
git status --short
git diff --cached --name-only --diff-filter=ACMRT
```

The commands above are planned verification until their actual results are recorded in the M7
acceptance document.

## Stop conditions

- Do not install a transcription dependency, fetch a model, upload footage, render a master,
  freeze a version, tag a release, or publish a package without the corresponding authorization.
- Do not treat sine-wave fixture audio or injected transcript text as semantic-editing evidence.
- Stop the real-media pilot if the project or artifact root overlaps a media root, source hashes
  change, storage is insufficient, required rights/privacy choices are unknown, or preview review
  identifies unresolved blocking issues.
