# Editorial review and pacing verification

Date: 2026-10-08. Implementation self-review. Reference baseline: merged main `3c8678d`.

- Ruff passed; mypy passed for 74 source files.
- Full suite: **195 passed, 1 skipped in 37.94 seconds**. Windows PE API is the platform-only skip.
- Nine new media integration cases and eight unit cases cover the approved first iteration.
- Wheel/source distribution built. A fresh isolated wheel installation passed command registration,
  actual-project evidence validation, dry-run behavior and content-safe JSON checks.
- Skill command/help/reference checks passed. Frozen cut-list JSON Schema matches its runtime model.

## Confirmed behavior

Phrase views preserve source word ranges and corrected text; mismatching corrected text is segment
aligned explicitly. Transcript content is absent from JSON stdout. Replaced corrected transcripts
and input mutation during review prevent publication, and existing evidence survives failure.

Source and output windows generate real frames, absolute PCM waveform, word/source maps, hashed
images/audio and listenable WAV. Clipped words remain visible and flagged. End-of-stream sampling
uses actual presentation timestamps. Missing audio and failed audio decode have different behavior;
failed decode cleans staging instead of fabricating silence. A repeated-source control hash cannot
be recaptured as a new baseline after it changes.

Caption tests preserve complete Chinese text/numeric terms, split measured pauses, extend display
within original bounds without overlap, and keep estimated timing explicit. Impossible display and
reading-speed constraints remain warnings.

Audio tests cover contiguous source joins, removed ranges and short-item fade bounds. Real FFmpeg
renders show reduced edge energy when smoothing is requested, unchanged output duration and cache
keys that incorporate neighbor context. Jianying exports matching volume keyframes, preserving
unity gain at continuous joins. This is structural evidence, not native app acceptance.

## Runtime discoveries fixed

The first cut-window demo showed an AAC concatenation window returning 88192 decoded samples when
86400 were requested. Presentation-clock resampling before trimming restores the exact review clock;
the PCM window is then checked, not silently stretched.

A stronger continuous-tone regression exposed an artificial silence near the join from independently
encoded AAC item padding. Before repair, minimum 5ms-window energy near the join was 298.8 against
mean window energy 3996278.15 (PCM sample squared units); the preservation assertion failed. Item and
assembly caches now hold PCM audio in MOV, and final preview/master audio is encoded once. The
same assertion passes after repair, with duration/cache/native-keyframe checks intact. Old AAC caches
are not reused. Extra PCM storage is the deliberate tradeoff; no disk/CPU speed-up is claimed.

## Synthetic example and visual inspection

A 2.4-second synthetic two-range preview was produced through actual CLI commands. Chinese mock
word timestamps/captions, discontinuous source ranges, 5ms smoothing, phrase view, source review and
rendered review were exercised. The output review PNG was inspected before and after the PCM fix:
frame labels, word labels, focus marker and absolute waveform are readable; the artificial padding
silence is removed. Frame times now align with the zero-start rendered timeline. Media and images
are local ignored artifacts, not committed fixtures. The audio is a synthetic tone, not human speech.

The isolated wheel also checked this actual synthetic project with dry-run commands and JSON output.
No source media or original cut-list was changed by review. No cloud ASR, model download, upstream
runtime or animation engine was installed.

## Remaining evidence limits

Windows/macOS CI includes these new cases in the existing platform jobs. CI state is attached to
both PRs; those OS jobs are not Jianying GUI tests. Real-video take selection, story quality and
natural speech need later viewing/listening with user footage. Native Jianying acceptance remains
paused as requested. QC/master/freeze approvals and severity thresholds remain unchanged.
