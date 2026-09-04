# Interview Edit Engineering Rules

These rules apply to the whole repository.

## Product boundary

- The CLI is the only execution engine and source of operational truth. The Codex Skill orchestrates it and must not duplicate media-processing logic.
- V1 serves speech-led creator videos: interviews, talking-head videos, tutorials, reviews, and vlogs. It is not a general nonlinear editor.
- Source media is read-only. Generated files must stay under the configured artifact root, which must not be inside a media root.
- Work is local-first and preview-first. Uploads, model downloads, master renders, and version freezes require the authorization defined by the product workflow.
- Invalid cut-lists must not render. Failed release QC must not freeze.
- Persistent edit time uses integer microseconds plus source time bases; do not persist untyped floating-point seconds.

## Architecture

- Keep Typer commands thin. Put testable behavior in domain or service modules.
- Use Pydantic v2 for durable configuration and protocol models.
- Invoke external programs with argument arrays and `shell=False`.
- Wrap filesystem, FFmpeg/FFprobe, and transcription boundaries behind adapters.
- Do not perform processing at import time.
- Preserve stable JSON envelopes and documented exit codes.

## Development

- Use Python 3.11 or newer and `uv`.
- Run `uv run ruff check .`, `uv run mypy src`, and `uv run pytest` before a ready claim.
- Add focused tests before or with behavior changes. Do not weaken validation or quality gates to make tests pass.
- Keep real media, downloaded models, caches, logs, and generated QC evidence out of Git.
- The reference repository `guang-tech/interview-edit-pipeline` is read-only evidence. Reimplement reusable methods behind the new interfaces; do not copy project paths, content data, Windows/NVENC assumptions, or source text without a recorded licensing decision.

## Documentation

- Product requirements live in `docs/prds/`.
- Stable interfaces live in `docs/specs/`.
- Architecture choices live in `docs/decisions/`.
- Execution and verification plans live in `docs/plans/` and `docs/tests/`.
- Update the relevant document when changing a frozen public contract.
