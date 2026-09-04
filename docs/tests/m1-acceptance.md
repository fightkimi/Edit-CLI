# M1 local acceptance record

- Date: 2026-09-03
- Package version: 0.1.0
- Result: locally verified

## Automated verification

| Command or check | Actual result |
|---|---|
| `uv run ruff check .` | passed |
| `uv run mypy src` | passed; no issues in 22 source files |
| `uv run pytest --cov=interview_edit --cov-report=term-missing` on Python 3.12.13 | 21 passed; 85% statement coverage |
| `python -m pytest` in a temporary Python 3.11.15 environment | 21 passed |
| JSON parsing of `docs/specs/cutlist-v1.schema.json` | passed |
| YAML parsing of `.github/workflows/ci.yml` | passed |
| Skill Creator `quick_validate.py` | `Skill is valid!` |
| Exact PRD comparison | byte-identical; SHA-256 `dbe7924d0e25a06b1119fccb7a9e2267c2b1710f467f03a8191478db3f72ed18` |

## Build and outside-source installation

`uv build` produced:

- `dist/interview_edit-0.1.0.tar.gz`
- `dist/interview_edit-0.1.0-py3-none-any.whl`

The final wheel was installed into `/private/tmp/interview-edit-m1-acceptance-20260903-01/venv`. From `/private/tmp`, outside the source tree:

- `command -v interview-edit` resolved to the temporary environment's executable.
- `interview-edit --version` returned `0.1.0`.
- `interview-edit --help` displayed only the implemented `init`, `doctor`, and `status` commands.
- `init` succeeded with Chinese and space-containing project/media paths and emitted a parseable JSON envelope.
- `status --json` succeeded, reported all unproduced stages as `missing`, and recommended only the implemented `doctor` command.
- The source-media sentinel file was unchanged by the integration test.

## Live doctor result

The final installed wheel ran `doctor --json` from `/private/tmp` on the host and exited 0 with overall status `degraded`.

Passed checks:

- Python 3.12.13 arm64.
- FFmpeg and FFprobe 8.1.2.
- libx264 and AAC.
- Real VideoToolbox H.264 probe.
- MLX Whisper backend import.
- Media-root readability.
- Artifact/media non-overlap.
- Artifact-root write access and disk query.
- Explicit project Skill discovery.

Non-blocking warnings:

- The project config names a registry model (`tiny`), so its availability is not assumed and any first download still requires approval.
- The temporary test project has no configured subtitle fonts, so glyph coverage is not verified.

## Not verified

- The GitHub Actions workflow was parsed locally but has not run remotely because no commit or push was requested.
- M2-M6 commands and behavior are intentionally not implemented in M1.
- Real interview transcription quality and production model selection remain for a later data-backed test.
- Windows, Linux, NVIDIA CUDA, long-media throughput, and real multi-camera synchronization are untested.
- No repository license has been selected, and no reference source code was copied.
