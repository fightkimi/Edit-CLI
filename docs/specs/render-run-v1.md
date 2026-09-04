# Render run protocol v1

Every non-dry render that passes cut-list preflight writes
`artifacts/renders/runs/<run_id>.json`. This manifest is execution evidence; it is not an editable
project-status flag.

## Lifecycle

- The first atomic write uses `state: running` before item FFmpeg work starts.
- The same run ID is updated after each completed or reused item cache.
- Exactly one terminal state is written: `succeeded`, `failed`, or `interrupted`.
- `succeeded` requires a published output with size and SHA-256. Failure/interruption has no output
  unless a complete prior output already existed; that prior file is never attributed to the failed
  run.
- `--dry-run` creates no run manifest and reports planned entries only in the command envelope.

## Required evidence

```json
{
  "schema_version": "1",
  "run_id": "render_20260903T000000Z_0123456789",
  "state": "succeeded",
  "project_id": "prj_example01",
  "cutlist_path": "/project/cutlists/revisions/v001.yaml",
  "cutlist_sha256": "...",
  "config_sha256": "...",
  "profile": "preview",
  "selection": {
    "actId": null,
    "itemId": null,
    "itemIds": ["item_001"]
  },
  "invocation": {
    "resume": true,
    "force": false,
    "output": "/project/artifacts/renders/v001-preview.mp4"
  },
  "input_fingerprints": {},
  "ffmpeg_version": "ffmpeg version ...",
  "encoder": "libx264",
  "environment": {
    "python": "3.12.13",
    "platform": "macOS-...",
    "gitCommit": null
  },
  "cache": [],
  "commands": [],
  "output": {
    "path": "/project/artifacts/renders/v001-preview.mp4",
    "size": 1234,
    "sha256": "...",
    "duration_us": 1000000
  },
  "error": null,
  "started_at": "2026-09-03T00:00:00Z",
  "completed_at": "2026-09-03T00:00:01Z"
}
```

`input_fingerprints` contains indexed source identities plus proxy, sync, image, and font SHA-256
values used by the selected items. `commands` contains argument arrays and return codes, never shell
strings. It records the encoder capability probe, each item render actually run, final assembly, and
both master loudness passes when applicable. Cache hits have no new item FFmpeg command and remain
explicit in `cache[].state`.

## Item cache

Each normalized item output has a sibling JSON manifest under
`artifacts/renders/cache/items/`. The cache key covers:

- strict item data and subtitle policy;
- resolved render profile and selected encoder;
- source/index identities and preview-proxy SHA-256 values;
- sync-report SHA-256 when camera mapping is used;
- referenced image and font SHA-256 values;
- the render-item schema identifier.

A hit requires key equality plus matching output path, size, and SHA-256. File existence alone is
never sufficient.
