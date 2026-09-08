# Output-quality first implementation

User approval: proceed with the optimizations in the 2026-09-08 project benchmark.
Baseline: `847bfcf`; the benchmark report is an intentional uncommitted document to preserve.

This iteration implements the actionable first steps, within the existing CLI engine:

1. Preserve all text during wrapping and block overflowing text before rendering; fix CRF zero.
2. Add a source-range revision operation that keeps existing item-relative camera, overlay and
   subtitle timing anchored to source time. Reject partially cut subtitle text rather than silently
   showing words no longer heard. Never mutate the original revision.
3. Add read-only speech-boundary checks using current transcript word timestamps, with explicit
   unknown evidence and content-safe diagnostics. No new recognition models or automatic semantic cuts.
4. Add Chinese-aware caption segmentation, exact word timing when available, clearly marked
   estimated timing otherwise, and two restrained subtitle presets (standard/minimal).
5. Extend item previews with optional adjacent-item context so joins can be reviewed.

Acceptance: regression tests first for the reproduced bugs; unit tests for timestamp remapping,
caption content preservation and speech boundaries; CLI tests for dry-run, protected output paths,
failed-validation preservation and privacy-safe JSON; synthetic rendering for text and context
selection; current schema/docs/Skill references match commands; Ruff, mypy and pytest pass.

New machine-produced cut-list revisions stay under the configured artifact root in
`cutlists/revisions/`, preserving original files and rebasing relative font/image references.
Only fresh, validated revisions may be published. Source media, transcripts, frozen versions and
existing run records are never rewritten by these commands. No remote/media/model integration is added.

Out of scope for this iteration: actual automatic audio restoration, new alignment models,
subject-tracking crop, animated captions, Remotion, J/L cuts and NLE export. These were conditional
follow-ups in the research, not prerequisites for fixing current output behavior.

Verification is self-review plus automated/synthetic evidence; real-media listening and editorial
A/B remain unverified without a supplied representative editing project.
