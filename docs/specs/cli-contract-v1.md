# CLI contract v1

## Global options

Global options may precede the command. `--project`, `--json`, and `--force` are also accepted after M1 commands where they are commonly needed.

```text
--project PATH
--json
--quiet, -q
--dry-run, -n
--force, -f
--no-color
--version
--help, -h
```

Machine-readable content is written to stdout. Progress and diagnostics are written to stderr. JSON mode must not emit progress bars, decoration, or ANSI sequences to stdout.

## Commands

```text
interview-edit init
interview-edit doctor
interview-edit status

interview-edit ingest
interview-edit proxy build
interview-edit transcribe
interview-edit sync

interview-edit cutlist scaffold
interview-edit cutlist inspect
interview-edit cutlist validate
interview-edit cutlist set-range
interview-edit cutlist captions
interview-edit cutlist speech-check
interview-edit cutlist motion

interview-edit motion build
interview-edit motion edit
interview-edit motion verify

interview-edit render
interview-edit qc

interview-edit export jianying
interview-edit jianying doctor
interview-edit jianying install

interview-edit version freeze
interview-edit version list
interview-edit version show
interview-edit version verify
```

Every command shown above is implemented. No nonfunctional placeholder is exposed.

Local motion commands and the `motion` overlay extension are specified in
[motion-assets-v1.md](motion-assets-v1.md). Generated movies retain editable source specifications;
native Jianying motion mapping is explicitly unsupported.

## M1 behavior

### `init`

```text
interview-edit init --project PATH --name NAME --media-root PATH \
  --privacy strict|assisted [--artifact-root PATH] [--force] [--json]
```

- Privacy has no hidden default.
- Existing configuration is not overwritten without `--force`.
- Every media root must exist and be a directory.
- The artifact root may be relative to the project directory, but its canonical path must not be inside any media root.
- Dry-run reports intended paths without writing them.

### `doctor`

Checks Python, FFmpeg, FFprobe, required encoders, actual VideoToolbox availability, the selected local transcription backend, configured model semantics, project paths, disk space, and the project Skill. It never installs or downloads anything.

### `status`

Reads configuration and reports both concrete artifact presence and validated control evidence. It
does not write a fuzzy global completion flag. Every stage preserves `state: present|missing` for
protocol compatibility and adds `validity: current|partial|invalid|missing`, `validCount`, and
`expectedCount` plus content-safe `reasonCodes`. Status validates schemas, project/source identity, declared paths,
declared sizes, small control-file checksums, terminal run state, and downstream evidence links as
applicable. It intentionally avoids re-hashing large proxies, renders, and frozen outputs on every
inspection. Owning commands still enforce full payload checksums before reuse, QC, or release; the
master and release gates also enforce an available full source hash.

Suggested `next` commands use `validity`, not file presence. A corrupt or empty index therefore
recommends `ingest`; incomplete proxy/transcript evidence recommends the owning stage; an orphaned
MP4 without a successful current run manifest does not count as a current render.

Proxy, transcribe, and sync stages also expose a content-safe `latestRun` containing the run ID,
terminal state, expected/completed/cached/skipped counts, stable error code, timestamps, and local
manifest path. A failed retry is visible there but does not invalidate older current artifacts.

## M2 behavior

### `ingest`

```text
interview-edit ingest --project PATH
  [--media-root PATH ...] [--camera-map FILE]
  [--extensions EXT[,EXT...] ...] [--full-hash]
  [--build-proxies] [--resume] [--force] [--json]
```

- Recursively scans selected roots while keeping every source read-only.
- The default extension set and durable index protocol are defined in `media-index-v1.md`.
- A run-level media-root override does not mutate project configuration.
- Outside-root symlinks are skipped and reported; artifact/media overlap remains a hard path error.
- A failed source probe leaves the previous valid index untouched and returns exit 3.
- `--build-proxies` runs the same proxy service exposed by `proxy build` only after ingest succeeds.

### `proxy build`

```text
interview-edit proxy build --project PATH
  [--asset ID ...] [--resume] [--force] [--json]
```

- Builds every indexed asset by default or the repeatable `--asset` selection.
- Cache validity requires a matching manifest and output size/SHA-256, not only file existence.
- Completed per-asset outputs are reusable after interruption. New files replace published files only after all FFmpeg work for that asset succeeds; the manifest is committed last.
- `--force` rebuilds selected assets. `--dry-run` reports planned assets without creating artifacts.
- Every non-dry invocation returns a `proxy_*` run ID and checkpoints content-safe progress in the
  operation-run manifest.

## M3 behavior

### `transcribe`

```text
interview-edit transcribe --project PATH
  [--asset ID ...] [--take ID]
  [--language CODE] [--model MODEL]
  [--device auto|cpu|cuda|metal]
  [--resume] [--force] [--json]
```

- Selects every audio asset by default; `--asset` is repeatable and mutually exclusive with
  `--take`.
- Requires a valid M2 audio proxy and verifies its source identity, size, and SHA-256.
- Recognizes five-minute chunks locally and atomically checkpoints each completed chunk. `--resume`
  reuses only checkpoints with the same complete transcription cache identity.
- Writes raw/corrected JSONL and SRT derivatives plus a manifest. Dictionary changes rebuild only
  corrected derivatives.
- A local directory passed by `--model` is accepted. A missing model name never triggers an implicit
  download and returns exit 3.
- Every non-dry invocation returns a `transcribe_*` run ID and checkpoints completed/resumed chunks
  without logging recognized text.

### `sync`

```text
interview-edit sync --project PATH --take ID --reference-camera ID
  [--window-count N] [--visual-check]
  [--manual-offset CAMERA=VALUE ...] [--force] [--json]
```

- Requires at least two assets with unique camera IDs in the selected take.
- Measures at least beginning/middle/end windows and persists the convention
  `camera_time = reference_time + offset`.
- Reports fixed offset, drift per hour/ppm, confidence, peak evidence, status, and provenance.
- `--visual-check` verifies existing video proxies and creates local side-by-side JPEG evidence.
- Low-confidence automatic cameras produce an evidence-bearing JSON envelope with `ok: false` and
  exit 3. Manual values accept signed `us`, `ms`, or `s` suffixes and are recorded as overrides.
- Every non-dry invocation returns a `sync_*` run ID. A completed low-confidence analysis records
  `review_required`, not a false success or a processing failure.

## M4 behavior

### `cutlist scaffold`

```text
interview-edit cutlist scaffold --project PATH
  [--asset ID] [--output PATH] [--force] [--json]
```

- Without `--asset`, creates one blank act at `cutlists/revisions/cutlist-v001.yaml`.
- With `--asset`, requires a current checksum-valid corrected transcript and creates chronological
  primary items and Chinese-aware subtitle cues. Matching word timestamps are used when available;
  otherwise times are apportioned within the segment and `estimatedSubtitleCount` reports this.
  It makes no narrative or model decisions.
- Output remains inside the editing project. Existing content is not replaced without `--force`.

### `cutlist inspect`

```text
interview-edit cutlist inspect --project PATH --cutlist PATH
  [--act ID] [--item ID] [--json]
```

- Reports timeline, selection, IDs, kinds, durations, and component counts.
- Does not emit transcript, subtitle, title, act-title, note, or other content-bearing text.

### `cutlist validate`

```text
interview-edit cutlist validate --project PATH --cutlist PATH
  [--profile preview|master] [--json]
```

- Enforces the strict runtime schema and every project-evidence invariant in
  `cutlist-schema-v1.md`.
- Warnings remain visible but do not block. Any error returns exit 3 and creates no render output.

### `render`

```text
interview-edit render --project PATH --cutlist PATH
  [--act ID] [--item ID] [--context-items 0|1|2] [--profile preview|master]
  [--output PATH] [--resume] [--force] [--json]
```

- Re-runs complete cut-list validation before selecting a full timeline, act, or item.
- Preview reads checksum-valid M2 proxies; master reads indexed immutable sources and enforces an
  optional full source hash when the index contains one.
- Keeps primary audio continuous across synchronized camera cuts and full-frame visual overlays.
- Applies declared title/subtitle rasters and paired fade transitions.
- `--resume` reuses only complete item cache objects with matching input/profile/edit hashes.
- Master uses measured two-pass EBU R128 loudness normalization. `auto` probes VideoToolbox with a
  real tiny encode and falls back to `libx264`.
- Publishes output atomically inside the artifact root. Different existing content requires
  `--force`; failure or interruption preserves the previous output.
- Rechecks referenced source revisions and current sync identity before publication; stale evidence
  cannot render.
- Writes one terminal run manifest with input fingerprints, cache decisions, environment, exact
  FFmpeg arguments/version, encoder, output checksum, and success/failure/interruption state.
- `--context-items` requires `--item` and profile `preview`. It includes up to that many neighbors
  on each side in document order, limited by an optional `--act`. It does not write or alter the
  cut-list. The output filename includes `contextN`, and manifest `selection.itemIds` records the
  actual sequence. Nonzero context also adds `selection.contextItems`; zero preserves the old
  selection shape. This supports visual/listening review, not automatic quality approval.

### Output-quality revision commands

```text
interview-edit cutlist set-range --project PATH --cutlist PATH --item ID
  --in-us INTEGER --out-us INTEGER [--output NAME_OR_PATH] [--json]
interview-edit cutlist captions --project PATH --cutlist PATH [--item ID]
  [--max-chars 2..80] [--style standard|minimal] [--output NAME_OR_PATH] [--json]
interview-edit cutlist speech-check --project PATH --cutlist PATH [--item ID] [--json]
```

- `set-range` and `captions` create new validated YAML revisions under
  `artifact_root/cutlists/revisions/`. A relative `--output` is relative to that directory; absolute
  outputs must stay within it without symlinks. Existing outputs are never replaced, including with
  global `--force`. Global `--dry-run` validates the proposal and writes nothing; `artifacts` is empty.
- JSON returns `cutlistPath`, affected `itemIds`, `dryRun` and content-safe warnings. Relative image
  and font paths are rebased so they still resolve to the same assets. The original cut-list,
  transcripts, source files and frozen versions are preserved. Status considers both legacy
  project-local and new artifact-root revision directories when suggesting the latest cut-list.
- `set-range` preserves source-time anchors for subtitles, camera cuts and overlays. Ranges outside
  the new item disappear; overlapping camera/visual ranges are clipped, including corresponding
  B-roll source in/out. Partially clipped subtitles fail with `subtitle_partial_trim` rather than
  showing text that no longer matches audio. Split or revise the cue before retrying. Existing
  transitions remain declared and must still pass pair/duration validation.
- Word timing, when available for the same audio source, blocks a new boundary inside a word.
  Missing timing and separate audio mappings are explicitly unverified. No phoneme alignment,
  audio-activity refinement or automatic narrative decision is claimed.
- `captions` splits existing text at punctuation and a soft length target (default 18). Decimal
  numbers and common units remain intact. When word text matches the edited cue, whole-word times
  are preserved; otherwise `subtitle_timing_estimated` marks proportional timing within the existing
  cue. It never stretches the item or silently rewrites the spoken claim. Cue density above a
  20 characters/second review heuristic produces `subtitle_readability_review`; it is not a
  universal language standard or an approval gate. `--style` applies globally and cannot be combined
  with `--item`. Whitespace is normalized; all non-whitespace text must survive.
- `speech-check` is read-only. It returns `checkedItemCount`, `unverifiedItemIds`, `findings`,
  `wordBoundaryStatus` (`clear|unverified|needs_revision`) and `listeningVerified: false`. Findings
  contain IDs, source times and outward word-boundary suggestions, never recognized text. Missing
  timing is a warning; detected word-internal cuts return exit 3. Stale transcript checksums also
  fail with exit 3. `clear` means only that known word intervals do not cross the selected edges.
- Any validation failure prevents revision publication. Overflowing titles/subtitles fail preflight
  as `text_layout_overflow`, before FFmpeg starts. The same condition is represented in QC when
  reviewing an older output.

## M5 behavior

### `qc`

```text
interview-edit qc --project PATH
  [--run RUN_ID] [--policy preview|release] [--json]
```

- Uses the latest successful render when `--run` is omitted.
- Rejects stale or corrupt render/config/cut-list/output evidence before release.
- Records stream parameters, A/V and timeline duration deltas, black/silence ranges, loudness and
  true peak, duplicate source ranges, subtitle safe-area/glyph checks, and bounded cut evidence.
- Preview content findings are warnings. Release requires a master and promotes unexplained black,
  silence, loudness, true-peak, and text findings to errors.
- Writes a new append-only report plus detached checksum. `--dry-run` plans without executing media
  tools or writing evidence.

### `version freeze`

```text
interview-edit version freeze --project PATH --run RUN_ID --approve
  [--note TEXT] [--json]
```

- Requires a separate approval, successful master, and latest current passing release QC.
- Copies the master, render/QC evidence, exact cut-list, and effective merged config into the next
  immutable `vNNNN` directory.
- Creates through atomic directory publication and never overwrites an existing version. `--force`
  cannot bypass quality or integrity gates.

### `version list`, `show`, and `verify`

```text
interview-edit version list --project PATH [--json]
interview-edit version show --project PATH VERSION_ID [--json]
interview-edit version verify --project PATH VERSION_ID [--json]
```

- List/show return manifest metadata without opening copied content-bearing inputs.
- Verify checks the detached version-manifest checksum, all declared file sizes/hashes, path safety,
  symlinks, and unexpected payloads. Any integrity issue returns exit 3.

## Exit codes

Experimental editable-project export and native draft-library handoff are specified separately in
[jianying-draft-v1.md](jianying-draft-v1.md). These commands do not claim a successful native-app render.

| Code | Meaning |
|---:|---|
| 0 | success |
| 1 | general runtime failure |
| 2 | arguments, configuration, or schema error |
| 3 | preflight, validation, or QC failure |
| 4 | missing external dependency |
| 5 | permission or path-boundary failure |
| 130 | interrupted by user |

## Editorial review and pacing

`review transcript` builds a content-bearing local phrase index across verified selected sources.
`review timeline` builds filmstrip/absolute-waveform/word evidence for one indexed source or successful
render run at `--focus-us`. JSON output contains paths/counts/warnings, not transcript text. Both use
new directories under `artifact_root/review`; dry-run writes nothing. Invalid/stale evidence fails
with the existing envelope and exit codes. Audio decode failure is not reported as silence.

`cutlist audio --edge-fade-us 5000` writes a new validated audio-policy revision.
`cutlist captions` adds opt-in `--pause-us`, `--min-duration-us` and configurable `--max-cps`.
The complete additive command and artifact contract is [editorial-review-v1.md](editorial-review-v1.md).

`review color` adds bounded source sampling and original/corrected contact sheets with numeric
statistics. `cutlist color` creates validated source-correction revisions and supports reset.
See [color-quality-v1.md](color-quality-v1.md). Suggestions do not silently modify a cut-list;
unsupported native color export fails explicitly rather than omitting a setting.
