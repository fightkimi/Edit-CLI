# Editorial review and pacing contract

The CLI owns all processing. Commands write new artifacts or validated cut-list revisions under the
configured artifact root. They never transcribe, download models, upload content or edit source files.

## Commands

```text
interview-edit review transcript --project PROJECT [--asset ID ...] [--pause-us 500000] [--json]
interview-edit review timeline --project PROJECT (--asset ID | --run RENDER_ID) \
  --focus-us INTEGER [--window-us 1500000] [--frames 8] [--json]
interview-edit cutlist audio --project PROJECT --cutlist CUTLIST [--edge-fade-us 5000] [--output NAME]
interview-edit cutlist captions --project PROJECT --cutlist CUTLIST \
  [--max-chars 18] [--pause-us 300000] [--min-duration-us 350000] [--max-cps 20] [--output NAME]
```

Global `--dry-run` validates/read-checks the selected evidence, but creates no files or FFmpeg review
jobs. Transcript view defaults to indexed sources with transcript manifests; explicit repeated
`--asset` selects a unique source list. Requested transcripts must be complete, checksum-valid
corrected outputs tied to the current source revision.

## Reading view

`artifact_root/review/phrases_<UUID>/` contains `phrases.md` and typed `phrases.json` (schema 1).
Phrases retain asset IDs, source integer-microsecond ranges, original words and text. Measured gaps
at least `pause-us` split aligned words within an ASR segment. Missing/nonmatching word evidence
retains the edited segment text and marks timing `segment`; no replacement timestamps are invented.
Speaker identity is `unknown` and audio events are `unavailable`, because current local transcript
models do not supply those labels. Source fingerprints and index/transcript hashes are recorded.

This is a reading surface for editorial judgment: it does not automatically select the best take,
score a hook or rewrite narrative meaning. The CLI stdout JSON returns only artifact paths, counts
and warnings, never recognized text.

## Timeline view

`--asset` reviews the source's verified video proxy on its normalized source-relative clock.
`--run` reviews an existing successful render on its output clock, requiring unchanged output,
cut-list, configuration and recorded source/proxy/sync/file evidence. It respects selected item
order and synchronized primary audio ranges. Words retain original source ranges and mapped output
ranges; words cut at item edges are clipped for display and explicitly flagged `clipped=true`.
Unavailable or nonmatching word evidence is not made up.

The window is centered on `focus-us`, clamped to timeline bounds. Radius must be 1–5000000us;
2–16 frames are sampled. Frame timestamps come from actual presentation times, so EOS/VFR windows
use available frames rather than seeking after the final image. The filmstrip connects samples to
the same time axis used by words, the focus marker and waveform. Duplicate samples near EOS are
permitted and their actual timestamps remain visible.

Each new review directory contains a `timeline.png`, individual JPEG frames, typed `report.json`
(schema 1), and a mono 48kHz PCM `window.wav` when audio exists. Image/frame/audio/source hashes and
control hashes are recorded. Audio is aligned to decoded presentation timestamps before trimming; WAVs record that time basis
and must cover the requested sample count. Audio amplitude uses absolute full-scale units, not per-window peak
normalization; peak and RMS dBFS are reported. All-zero PCM is decoded silence with null dBFS;
missing audio is `audio_status=missing`; decode failure or truncated audio fails the command and
publishes no review. No zeros are substituted for failed decoding. Words need a declared local
font for non-Latin labels. A waveform or level measurement is not listening or quality acceptance.

Every review captures inputs once and rejects revisions during the operation. Atomic publication
creates a unique directory; failure removes only its own staging directory. Existing evidence is
preserved. There is no review pass/fail replacing preview/release QC or native app acceptance.

## Audio boundary policy

Cut-list schema 1 adds optional `audio_policy.edge_fade_us`, a strict integer in 0–50000. Omitted
policy defaults to **0**, preserving old projects. `cutlist audio` writes a new validated revision;
its suggested starting setting is 5000us. The final value belongs to the user/project edit.

The shared audio-range mapper decides whether adjacent items share an uninterrupted source audio
clock. Those joins receive no new fades, including visual camera changes. Removed gaps, reordered
ranges, changed audio sources and outer render edges receive smoothing, bounded to one quarter of
item duration. Existing declared transitions take precedence when longer. Video transitions are
unchanged and smoothing adds no overlap or duration change. Intermediate MOV item caches use PCM
audio; final preview/master encode audio once, avoiding per-item AAC priming gaps.

Render item cache keys include the effective in/out fades, so an item rendered alone cannot reuse
its full-timeline neighbor context incorrectly. Jianying serialization uses the same mapping and
exports matching volume keyframes. Native application behavior remains unverified per the existing
paused acceptance scope.

## Caption timing

The new caption options default to 0/0/20 at the CLI, retaining earlier split/timing behavior unless
pacing is selected. Recommended initial preview settings are `--pause-us 300000
--min-duration-us 350000 --max-cps 20` and must be reviewed for the content/language.

Aligned cues split at measured pauses. Very short neighboring parts may merge within the character
budget without crossing a pause; display time may extend within original cue bounds and leave the
configured pause before the next cue. Text is preserved, timing remains integer microseconds and
parts never overlap or extend beyond the original cue. Existing manually edited text without full
word agreement uses proportional timing marked estimated. Constraints that cannot fit return
`subtitle_display_too_short` or `subtitle_readability_review` warnings instead of deleting text,
stretching the timeline or weakening render validation.

## Privacy and evidence limits

Review artifacts contain transcript text, frames and audio, even though the CLI envelope is
content-safe. Creating local artifacts is separate from exposing their contents to the coding agent.
The existing `strict`/`assisted` Skill policy governs reading them; neither command uploads content.
Use the JSON report for complete text/timing if labels collide on the PNG. Actual hook selection,
continuity, intelligibility and natural speech still need editorial judgment and viewing/listening.
The implementation adapts ideas from the recorded video-use assessment; no upstream code or new
runtime dependency is bundled.
