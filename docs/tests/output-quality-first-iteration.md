# Output-quality first iteration verification

Date: 2026-09-08. Baseline `847bfcf`. This is implementation self-review, not independent acceptance.

## Observed results

- Before the fix, the targeted tests reproduced CRF zero becoming 20, long Chinese text being
  truncated, and the missing overflow diagnostic. Three tests failed and two passed.
- New CLI tests initially failed for the absent revision/check/context commands; the preflight
  overflow test passed once the text fix was connected to validation.
- Final `uv run ruff check .`: passed.
- Final `uv run mypy src`: passed for 58 source files.
- Final `uv run pytest`: **132 passed in 24.27 seconds**.
- All five project Skills passed metadata validation and local-reference checks. Actual CLI help
  exposes `cutlist set-range`, `cutlist captions`, `cutlist speech-check` and context preview.
- `uv build` produced a wheel and source distribution in a temporary directory.
- Installing that wheel in a separate temporary environment succeeded; caption and render help
  exposed the new options. This smoke check did not modify the globally installed CLI.

## Coverage

Text tests check complete long Chinese/mixed numeric text, measured line width, overflow rejection,
small-canvas overflow, preservation of an existing raster, CRF None/zero/normal handling, and different
standard/minimal outputs. Visual inspection of synthetic 1280×720 caption rasters confirmed the
standard box and smaller unboxed minimal preset, complete Chinese text and visible decimal/unit.
These flat-background samples do not establish contrast on all footage.

Timing tests cover shrinking/expanding an item, source-anchored camera and overlay timing, trimmed
B-roll source ranges, preserved original models, rejected partial subtitle text, whole-word boundary
suggestions, caption text/number preservation, exact matching-word times and explicit estimated
timing after transcript corrections.

CLI tests use generated video and mock transcription to verify successful revision/render paths,
dry-run without writes, out-of-bounds rejection, original-file preservation, no-overwrite publishing,
relative-image rebasing, symlink rejection, stale transcript checksums, private text omission,
generated-ID collision handling, unverified speech evidence and context selection. A context
preview renders three selected items to a 2,400,000 µs output with their IDs in the manifest.

One full-suite failure caught an extra default `contextItems: 0` field in the legacy manifest
selection. The implementation now emits that field only for nonzero context, preserving the original
assertion and JSON shape. No existing test assertion was weakened.

## Limits

Speech checks detect cuts inside known transcript words. They do not listen, measure nearby audio
activity, align phonemes, or automatically map separate audio transcripts. Missing timing is marked
unverified. Proportional caption timing is explicitly estimated, and the density heuristic requests
review rather than claiming universal readability. There is no new ASR/restoration model, automatic
crop, animated-caption renderer or external service.

No representative real editing project was supplied. Natural pacing, lip sync, actual voice quality,
visual storytelling and real-material before/after preference still require the project's real-media
intake and preview review. Generated media and environment artifacts remain outside Git.
