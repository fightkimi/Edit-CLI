# Source color diagnosis and controlled correction

Continue the existing editorial-quality PRs, preserving the first iteration and paused native
Jianying acceptance. Implement source-linked SDR image statistics, bounded declarative correction,
and before/after sample contact sheets. Use source originals and integer-microsecond ranges, no
uploads/new runtimes, no automatic changes to QC or approval gates.

Acceptance:
- New optional cut-list color policy defaults neutral. Brightness/contrast/gamma/saturation are
  finite bounded values, applied per actual visual source before overlay/text composition.
- A thin `cutlist color` command writes validated revisions and preserves prior values unless a
  parameter/reset was requested. Unknown sources and known HDR correction are rejected.
- `review color` samples a bounded source window, optionally compares the synchronized same-take
  reference camera, and publishes diagnostic JSON plus before/after images with provenance. A
  suggestion is labeled proposed, not an automatic quality verdict; no settings change silently.
- Frame sampling uses actual timestamps, source/controls are checked before publication, decoding
  failures preserve existing evidence, dry-run creates no files, source media stays read-only.
- Renderer cache depends on relevant source correction. Neutral policy keeps visuals unchanged;
  applying/resetting a source changes only dependent caches. Native Jianying export must fail clearly
  if a non-neutral correction cannot be preserved, rather than discard it.
- Verify brightening on underexposed synthetic gradients, unchanged audio/duration, text overlay
  colors, multicamera/B-roll applicability, invalid/HDR/stale inputs, reset, schema and CLI privacy.
  Run full Ruff/mypy/tests, inspect contact-sheet pixels, packaged CLI and both repositories' CI.

Official filter interface: https://ffmpeg.org/ffmpeg-filters.html#eq. Image statistics are bounded
sample heuristics, not scene semantics, calibrated color measurement, HDR tonemapping or a promised
skin-tone/white-balance solution. Automatic per-frame grading and new animation runtimes are excluded.
