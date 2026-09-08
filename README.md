# Interview Edit

`interview-edit` is a local-first CLI for reproducible editing of speech-led creator videos. It turns local media, transcripts, synchronization evidence, and a versioned cut-list into previews and release-gated masters without modifying source media.

V1 starts with interviews, talking-head videos, tutorials, reviews, and vlogs. The CLI remains the deterministic execution engine; the repository-level Codex Skill translates natural-language editing requests into reviewed CLI operations and cut-list changes.

## Installation

Python 3.11 or newer plus local `ffmpeg` and `ffprobe` are required. To work on the repository with
the locked dependency set:

```bash
uv sync --locked --group dev
uv run interview-edit --version
```

Build and install the base CLI as a standalone tool:

```bash
uv build
uv tool install ./dist/interview_edit-0.6.0-py3-none-any.whl
command -v interview-edit
interview-edit --version
```

The base package can inspect projects and execute every non-transcription stage, but it does not
bundle a speech-recognition runtime. For local transcription, install exactly one optional backend:

```bash
uv tool install '.[mlx]'             # Apple silicon
uv tool install '.[faster-whisper]'  # supported CPU/GPU environments
```

Installing dependencies or fetching a model may use the network. A model name in configuration is
not permission to download it; point the project at an already available local model unless the
download has been explicitly authorized. After installation, run `interview-edit doctor --project
/path/to/project --json` on the target machine.

The project Skill lives at `.agents/skills/interview-edit/`. Codex discovers it while working in
this repository or its descendants; the installed CLI itself works from any directory when given an
explicit `--project` path.

## Output-quality Skills

Four focused project Skills complement `interview-edit`: `edit-story-structure` for the editorial
script, `edit-speech-pacing` for natural cuts, `edit-caption-audio-review` for readable captions and
dialogue, and `edit-render-review` for composition and export review. Ask, for example:
“用这些 Skills 改善这版剪辑，先调整脚本和切点，再检查字幕与画面，给我预览。”

Three are MIT-licensed upstream adaptations with pinned source records and preserved notices;
the render-review Skill is written for this CLI. No alternate renderer or automatic cloud workflow
is installed. Skills guide decisions and review; they do not by themselves prove better output or
add unsupported effects. See the [selection and integration record](docs/research/2026-09-05-output-quality-skills.md).

The CLI provides `cutlist speech-check` for word-boundary diagnostics, `cutlist set-range` for
source-anchored timing revisions, and `cutlist captions` for Chinese-aware cue splitting and
standard/minimal subtitle presets. These write validated revisions under
`artifact_root/cutlists/revisions/`; `--dry-run` is available as a global option. Partial subtitle
cuts and overflowing text are rejected. Missing word evidence and estimated cue timing are reported
for review. `render --item ID --context-items 1 --profile preview` includes neighboring items for
reviewing a join. See the [quality command contract](docs/specs/cli-contract-v1.md).

## Implemented commands

```bash
interview-edit --help
interview-edit init --project /path/to/project --name "My video" \
  --media-root /path/to/source-media --privacy assisted
interview-edit doctor --project /path/to/project
interview-edit status --project /path/to/project
interview-edit ingest --project /path/to/project --full-hash
interview-edit proxy build --project /path/to/project --resume
interview-edit transcribe --project /path/to/project --resume
interview-edit sync --project /path/to/project --take take-01 \
  --reference-camera wide --visual-check
interview-edit cutlist scaffold --project /path/to/project --asset asset_ID
interview-edit cutlist inspect --project /path/to/project --cutlist cutlists/revisions/cutlist-v001.yaml
interview-edit cutlist validate --project /path/to/project --cutlist cutlists/revisions/cutlist-v001.yaml
interview-edit render --project /path/to/project --cutlist cutlists/revisions/cutlist-v001.yaml \
  --profile preview --resume
interview-edit qc --project /path/to/project --run render_RUN_ID --policy preview
interview-edit version freeze --project /path/to/project --run render_MASTER_RUN_ID --approve
interview-edit version verify --project /path/to/project v0001
```

Put editing projects and source media outside this code repository. `init` creates configuration and artifact directories but never copies or changes source media.

`ingest` recursively builds an atomic media index with stable asset IDs and bounded fast fingerprints. `proxy build` creates cached H.264 viewing proxies, 16 kHz mono WAV speech-analysis proxies, JPEG thumbnails and contact sheets, and source/proxy time maps. Generated files stay under the configured artifact root.

`transcribe` runs an installed local Whisper adapter in bounded resumable chunks, writes segment and
word timestamps in integer microseconds, and keeps raw recognition separate from optional
`dictionaries/corrections.yaml` rules. A model name never authorizes a download: use a model already
present in the local cache or pass an existing model directory.

`sync` compares beginning/middle/end audio windows, reports each camera's fixed offset, clock drift,
confidence, and provenance, and can create local side-by-side review screenshots. Low-confidence
automatic results retain their report but return exit 3; use an audited `--manual-offset` only after
review.

Every non-dry proxy, transcription, and synchronization invocation writes a content-safe operation
run under `artifacts/logs/`. The run ID correlates CLI output with completed/cached counts, stable
error codes, and small control artifacts without copying transcript text or large media payloads.

`cutlist scaffold` writes either a blank edit document or a chronological skeleton from one current
corrected transcript. `cutlist inspect` reports structure without exposing content-bearing text,
and `cutlist validate` checks schema, source bounds, camera/sync relationships, overlays, subtitles,
fonts/images, transitions, proxies, and render-profile compatibility before FFmpeg can start.

`render` supports full-timeline, act, and item previews from verified proxies. It keeps the chosen
audio continuous across camera cuts and visual overlays, reuses checksum-valid item caches, and
publishes the final MP4 atomically with a terminal run manifest. Master output reads indexed
originals and applies measured two-pass EBU R128 loudness normalization; request it only after a
preview is approved.

`qc` binds stream, duration, black/silence, loudness, true-peak, source-use, subtitle/font, and cut
evidence to one successful render run. Preview policy permits content warnings; release policy
requires a master and zero error/blocking findings. `version freeze` then copies the master,
cut-list, effective config, render/QC manifests, and checksums into a new immutable version only
after a separate `--approve`.

## Development

```bash
uv sync --extra mlx --group dev
uv run ruff check .
uv run mypy src
uv run pytest
```

See the [V1 product requirements](docs/prds/interview-edit-cli-skill-v1.md), [project configuration](docs/specs/project-config-v1.md), [CLI contract](docs/specs/cli-contract-v1.md), [cut-list contract](docs/specs/cutlist-schema-v1.md), [operation-run protocol](docs/specs/operation-run-v1.md), [render-run protocol](docs/specs/render-run-v1.md), [QC report protocol](docs/specs/qc-report-v1.md), [frozen-version protocol](docs/specs/version-manifest-v1.md), [media-index protocol](docs/specs/media-index-v1.md), [transcript/sync protocol](docs/specs/transcript-and-sync-v1.md), [M6 plan](docs/plans/m6-skill-and-beta-acceptance.md), [M7 synthetic-matrix plan](docs/plans/m7-synthetic-creator-matrix-and-intake.md), [M7 acceptance evidence](docs/tests/m7-synthetic-creator-matrix.md), [real-media Beta intake checklist](docs/tests/real-media-beta-checklist.md), [V1 release-readiness evidence](docs/tests/v1-release-readiness.md), [Skill benchmark](docs/research/2026-09-04-interview-edit-skill-benchmark.md), [Skill orchestration ADR](docs/decisions/0008-state-aware-skill-orchestration.md), and [artifact/evidence hardening ADR](docs/decisions/0009-artifact-boundaries-and-evidence-freshness.md).
