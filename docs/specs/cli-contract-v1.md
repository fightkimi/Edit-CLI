# CLI contract v1

## Global options

Global options may precede the command. `--project`, `--json`, and `--force` are also accepted after M1 commands where they are commonly needed.

```text
--project PATH
--json
--quiet, -q
--verbose, -v
--debug, -d
--dry-run, -n
--force, -f
--no-input
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

interview-edit render
interview-edit qc

interview-edit version freeze
interview-edit version list
interview-edit version show
interview-edit version verify
```

M5 implements every command shown above. No nonfunctional placeholder is exposed.

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

Reads configuration and reports concrete artifact presence. It does not write a fuzzy global completion flag. It recommends `ingest` when the index is absent and `proxy build` when index evidence exists but proxy evidence does not.

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

## M4 behavior

### `cutlist scaffold`

```text
interview-edit cutlist scaffold --project PATH
  [--asset ID] [--output PATH] [--force] [--json]
```

- Without `--asset`, creates one blank act at `cutlists/revisions/cutlist-v001.yaml`.
- With `--asset`, requires a current checksum-valid corrected transcript and creates chronological
  primary-item/subtitle placeholders. It makes no narrative or model decisions.
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
  [--act ID] [--item ID] [--profile preview|master]
  [--output PATH] [--resume] [--force] [--json]
```

- Re-runs complete cut-list validation before selecting a full timeline, act, or item.
- Preview reads checksum-valid M2 proxies; master reads indexed immutable sources.
- Keeps primary audio continuous across synchronized camera cuts and full-frame visual overlays.
- Applies declared title/subtitle rasters and paired fade transitions.
- `--resume` reuses only complete item cache objects with matching input/profile/edit hashes.
- Master uses measured two-pass EBU R128 loudness normalization. `auto` probes VideoToolbox with a
  real tiny encode and falls back to `libx264`.
- Publishes output atomically inside the artifact root. Different existing content requires
  `--force`; failure or interruption preserves the previous output.
- Writes one terminal run manifest with input fingerprints, cache decisions, environment, exact
  FFmpeg arguments/version, encoder, output checksum, and success/failure/interruption state.

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

| Code | Meaning |
|---:|---|
| 0 | success |
| 1 | general runtime failure |
| 2 | arguments, configuration, or schema error |
| 3 | preflight, validation, or QC failure |
| 4 | missing external dependency |
| 5 | permission or path-boundary failure |
| 130 | interrupted by user |
