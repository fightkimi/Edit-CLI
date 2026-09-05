# V1 status-model and Beta UX hardening

- Status: implemented and self-verified
- Date: 2026-09-04

## Goal

Make continuation decisions depend on validated control evidence instead of arbitrary file
presence, make configured local transcription-model paths resolve consistently, reject safety
settings that contradict the product boundary, and correct the private-Beta guide's verified visual
and wording issues.

## Acceptance criteria

- `status` preserves the existing `state: present|missing` compatibility field and adds an
  evidence-derived `validity: current|partial|invalid|missing`, valid/expected counts, and
  content-safe reason codes.
- Invalid or empty media indexes cause `status.next` to recommend `ingest`, not a downstream stage.
- Downstream stage summaries do not call arbitrary files or failed run manifests current evidence.
- A relative configured local transcription-model path resolves from the editing-project root in
  both `doctor` and `transcribe`; a command-line model override remains relative to the caller's
  current directory.
- V1 safety invariants cannot be disabled through configuration.
- Nonfunctional global CLI flags are removed from the V1 public surface and its stable contract.
- The private-Beta guide no longer overstates `status`, the desktop toolbar does not overlap cover
  metadata, and the mobile page reaches its main purpose without a full navigation wall.
- Focused regression tests fail before the implementation and pass afterward. Full Ruff, mypy,
  pytest, touched-file format, and responsive visual checks pass before a ready claim. Historical
  formatter drift in untouched files remains outside this patch.

## Non-goals

- No source-media mutation, model or dependency download, master render, freeze, upload, or publish.
- No new media-processing logic in the Skill.
- No full run-log protocol or predictive disk-space estimator in this patch; those require a
  separate durable runtime protocol and real-media measurements.

## Planned changes

1. Add focused tests for status validity/routing, fixed safety invariants, CLI option exposure, and
   local-model base-directory behavior.
2. Implement status evidence inspection while reusing existing Pydantic models, checksums, and
   source/proxy validators.
3. Share model resolution between doctor and transcription execution.
4. Tighten configuration and remove unsupported CLI switches; update frozen specs.
5. Apply the narrow guide fixes and re-run desktop/mobile/dark-mode inspection.

## Verification evidence

- The focused red baseline produced eight expected failures across invalid status evidence, CLI
  placeholders, safety invariants, and model-path resolution.
- Focused status/transcription checks passed after implementation, including the five-format
  creator matrix, proxy corruption/config drift, passing render/QC, and frozen-version tampering.
- Full test suite: 104 passed on local Python 3.11.15.
- Statement coverage: 86% overall; the transcription adapter increased from 42% to 71%.
- `ruff check .`: passed.
- `mypy src`: passed for 53 source files.
- Ruff format check passed for every Python file touched by this patch. Four untouched historical
  files still have the formatter drift already recorded by M7.
- `uv build` produced the 0.6.0 sdist and wheel successfully.
- Fresh browser review passed at 1280 px desktop and 390 x 844 mobile in light and dark modes. The
  toolbar no longer overlaps the cover metadata, mobile has no page-level horizontal overflow, and
  the main cover now begins at 104.5 px instead of roughly 490 px.

## Remaining limits

- `status.validity` is a bounded control-evidence inspection. It deliberately does not re-hash large
  proxies, renders, or frozen master payloads; the owning commands remain the full-integrity gates.
- Predictive disk budgeting, cross-platform real transcription, and production-duration performance
  remain separate real-media hardening work. Proxy/transcribe/sync run observability is continued in
  `v1-operation-run-observability.md`.
