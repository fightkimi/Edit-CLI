# Media index and proxy artifact protocol v1

## Media index

The authoritative file is `artifacts/index/media-index.json`. JSON keys use `snake_case` to match project configuration and cut-list documents. Arrays are deterministically ordered by `asset_id`.

Top-level fields:

```json
{
  "schema_version": "1",
  "project_id": "prj_example",
  "generated_at": "2026-09-03T12:00:00Z",
  "probe_version": "ffprobe version ...",
  "media_roots": ["/absolute/source/root"],
  "extensions": [".mov", ".mp4"],
  "assets": [],
  "changes": {
    "added": [],
    "changed": [],
    "unchanged": [],
    "removed": []
  },
  "warnings": []
}
```

Each asset contains:

- `asset_id`, `canonical_path`, `media_root`, `relative_path`
- `size`, `mtime_ns`, `fingerprint`, optional `full_hash`
- `duration_us`, `stream_time_base`, optional `start_time_us`
- optional `video_stream`, zero or more `audio_streams`
- optional `camera_id`, `take_id`, `capture_time`
- `probe_version`

Video metadata retains codec, dimensions, pixel format, optional color range/space/transfer/primaries
and field order, stream time base, average and real frame-rate rationals, start and duration
microseconds, and rotation when reported. Audio metadata retains codec, sample rate,
channels/layout, stream time base, start and duration microseconds.

All persisted positions and durations are integers in microseconds. An absent or unknown value is null, not a guessed zero. Rational values remain strings.

## Camera map

`--camera-map` accepts YAML:

```yaml
schema_version: "1"
rules:
  - glob: "wide/**"
    camera_id: wide
  - glob: "take-02/camera-b/*.mov"
    camera_id: close-b
    take_id: take-02
```

Rules are evaluated in order against root-relative POSIX paths. Later matching rules override only the non-null values they provide. The CLI does not infer camera or take identity from filenames.

## Time map

Each video proxy has `<asset_id>.time-map.json`:

```json
{
  "schema_version": "1",
  "asset_id": "asset_...",
  "mapping": "normalized_identity",
  "source_start_us": 0,
  "source_duration_us": 1000000,
  "proxy_start_us": 0,
  "proxy_duration_us": 1000000,
  "source_time_base": "1/90000",
  "proxy_time_base": "1/12800"
}
```

`normalized_identity` means proxy timeline microseconds map one-to-one to elapsed source presentation time after subtracting `source_start_us`. VFR frame selection must later consult real source PTS; M2 does not claim a fixed-frame-number mapping.

## Proxy manifest

`<asset_id>.manifest.json` records:

- `schema_version`, `asset_id`, `source_fingerprint`, optional `source_full_hash`, `cache_key`
- `ffmpeg_version`, `ffprobe_version`, and complete proxy/audio/thumbnail settings
- each expected output's kind, absolute path, size, and SHA-256
- completion timestamp

A cache hit requires matching keys plus existing output size and SHA-256. Files from an older or failed run are never treated as valid solely because they exist.

## Contact sheets

Contact sheets are JPEG grids that can be opened by Codex image inspection. The manifest fixes page order and maps each row/column cell to its asset ID and relative path. Content-keyed filenames allow the manifest to switch atomically only after all new pages exist. No source pixels or proxies are written outside the artifact root.
