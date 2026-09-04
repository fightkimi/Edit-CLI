# M3 transcription and multi-camera sync implementation plan

- Status: implemented and locally verified; see `docs/tests/m3-acceptance.md`
- Date: 2026-09-03

## Goal and acceptance

Implement local-only, resumable speech transcription and evidence-backed multi-camera audio
synchronization. The implementation remains useful for interviews, talking-head videos, tutorials,
reviews, and vlogs; it does not introduce documentary-only concepts.

M3 is accepted when:

- `transcribe` selects indexed assets or one take, requires a valid audio proxy, and never uploads
  audio or implicitly downloads a model;
- transcription checkpoints are committed per chunk, an interrupted run resumes completed chunks,
  and final segment/word timestamps are integer microseconds;
- raw recognition is preserved separately from deterministic dictionary corrections;
- transcription cache identity includes source/audio fingerprints, backend, model, device, language,
  parameters, and schema version;
- `sync` samples at least beginning/middle/end windows, reports fixed offset, drift, confidence, and
  per-window evidence for every non-reference camera in a take;
- manual offsets are parsed into integer microseconds and retain explicit provenance;
- low-confidence automatic sync writes its evidence but exits with preflight code 3 rather than
  silently claiming success;
- optional visual review creates local contact-sheet evidence from existing video proxies;
- lint, typing, tests, build, isolated-wheel smoke, a real FFmpeg sync fixture, and a host MLX run
  pass, or any unrun layer is reported explicitly.

## Public command surface

```text
interview-edit transcribe --project PATH
  [--asset ID ...] [--take ID]
  [--language CODE] [--model MODEL]
  [--device auto|cpu|cuda|metal]
  [--resume] [--force] [--json]

interview-edit sync --project PATH
  --take ID --reference-camera ID
  [--window-count N] [--visual-check]
  [--manual-offset CAMERA=VALUE ...]
  [--force] [--json]
```

`--asset` is repeatable. Without `--asset` or `--take`, transcription selects every indexed asset
with audio. `--asset` and `--take` are mutually exclusive so selection remains auditable. Offset
values accept signed `us`, `ms`, or `s` suffixes; a bare integer is interpreted as microseconds.

## Durable protocols

- `artifacts/transcripts/<asset_id>/raw.jsonl`: immutable recognition segments for one cache key.
- `artifacts/transcripts/<asset_id>/corrected.jsonl`: deterministic correction-layer view.
- `artifacts/transcripts/<asset_id>/raw.srt` and `corrected.srt`: operator-readable derivatives.
- `artifacts/transcripts/<asset_id>/manifest.json`: cache inputs, backend identity, correction
  fingerprint, output sizes, and SHA-256 values.
- `.interview-edit/cache/transcribe/<asset_id>/<cache_key>/chunk-*.json`: atomic chunk checkpoints.
- `dictionaries/corrections.yaml`: optional project-owned literal correction rules.
- `artifacts/sync/<take_id>/sync.json`: take-level offsets, drift estimates, confidence, provenance,
  and window measurements.
- `artifacts/sync/<take_id>/evidence/window-*.jpg`: optional local visual-review sheets.

The complete field-level contract is frozen in `docs/specs/transcript-and-sync-v1.md`.

## Technical choices from measured environment

- Python 3.11+ remains the runtime contract; verification targets the existing Python 3.12.13 and
  the available Python 3.11.15 runtime.
- MLX Whisper 0.4.3 is the preferred Apple Silicon adapter. Its actual signature accepts local
  `path_or_hf_repo`, `word_timestamps`, and `condition_on_previous_text`. Metal is unavailable in
  the Codex sandbox but a host run was established in M0, so sandbox and host evidence are separate.
- Faster-Whisper remains an optional adapter for CPU/CUDA. It is not installed on this machine and
  must fail with the dependency exit code when explicitly selected.
- A deterministic mock adapter supports tests only; it does not masquerade as real recognition.
- Five-minute chunks bound retry cost and make completed work resumable. Each chunk is extracted
  from the generated audio proxy, never from a modified source file.
- NumPy 2.x implements energy envelopes, normalized FFT cross-correlation, and robust linear drift
  estimation. The current lock already contains NumPy through MLX; M3 makes it a direct runtime
  dependency because sync is a base command.
- Automatic sync uses a 100 Hz log-energy envelope and multiple evenly distributed windows. The
  persisted convention is `camera_time = reference_time + offset`.

## File-level work

| Files | Responsibility | Verification |
|---|---|---|
| `src/interview_edit/models/transcript.py`, `sync.py` | strict v1 artifacts with integer time | model/unit tests |
| `src/interview_edit/adapters/transcription.py`, `tests/fixtures/transcription.py` | MLX and Faster-Whisper production adapters; injected deterministic test fake | adapter tests; host MLX smoke |
| `src/interview_edit/transcribe/service.py` | selection, proxy validation, checkpoints, cache, corrections, SRT | interruption/cache integration tests |
| `src/interview_edit/sync/analysis.py`, `service.py` | envelope correlation, drift, manual provenance, visual evidence | known-offset/drift tests and FFmpeg integration |
| `src/interview_edit/config/models.py` | bounded chunk and sync analysis settings | config tests |
| `src/interview_edit/cli/app.py` | thin M3 command routing and nonzero uncertain-sync result | CLI JSON/help tests |
| `src/interview_edit/status/service.py` | evidence-based next-stage recommendations | integration tests |
| `tests/fixtures/media_factory.py` | deterministic delayed/drifting audio fixtures | local FFmpeg integration |
| docs, README, project Skill reference | public operator flow and protocol | review and link checks |

## Ordered execution

1. Freeze this plan, the v1 artifact protocol, and ADR 0005.
2. Add failing model, correction, correlation, offset parser, and low-confidence tests.
3. Implement transcript models/adapters/service and expose `transcribe`.
4. Add interruption/resume and raw-versus-corrected integration coverage.
5. Implement sync analysis/service, manual provenance, and visual evidence.
6. Expose `sync`, update status/Skill/docs, then run full verification on Python 3.11 and 3.12.
7. Exercise the locally cached MLX tiny model on the host without network access.

## Acceptance commands

```bash
uv run ruff check .
uv run mypy src
uv run pytest --cov=interview_edit --cov-report=term-missing
uv build

interview-edit transcribe --project <synthetic-project> --resume --json
interview-edit sync --project <synthetic-project> --take take-01 \
  --reference-camera wide --visual-check --json
ffprobe -v error -show_format -show_streams <generated-sync-evidence-or-proxy>
```

The wheel is installed into a clean environment and exercised outside the source tree. Exact
commands and observed results belong in `docs/tests/m3-acceptance.md`; none are recorded as passing
until actually run.

## Assumptions and stop conditions

- A valid M2 audio proxy is required. M3 does not silently rebuild proxies.
- Camera and take IDs come only from the media index/camera map; filenames are not semantically
  guessed.
- Dictionary correction is literal text replacement in declared rule order. It never changes
  timestamps or overwrites raw recognition.
- Drift is measured and reported, not time-stretched in M3.
- Visual evidence is content-bearing and remains local. The Skill reads it only under the project's
  privacy rules.
- Stop and realign if implementation would require source writes, audio upload, implicit network or
  model download, float timestamps in durable edit data, or silent acceptance of uncertain sync.
