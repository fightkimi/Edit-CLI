# Operation run protocol v1

Proxy building, transcription, and synchronization write one local operation manifest per non-dry
invocation at `artifacts/logs/<run_id>.json`. Run IDs begin with `proxy_`, `transcribe_`, or `sync_`
and are returned as the CLI envelope's `runId`.

## Lifecycle

- The first atomic write uses `state: running` before dependency/model/media work begins.
- Proxy updates progress after every built, cached, or skipped asset.
- Transcription updates progress after every completed/resumed chunk and completed/cached asset.
- Sync reaches `review_required` when evidence was produced but one or more cameras remain uncertain.
- Every handled invocation terminates as `succeeded`, `review_required`, `failed`, or `interrupted`.
- Dry runs create no operation manifest and return a null/omitted run ID.
- Expected command failures promote the operation run ID into the error envelope and include the
  local manifest path in error details, so the failure can be correlated without scanning logs.

An interrupted process that cannot execute cleanup, such as a machine power loss or force kill, may
leave `running`. Status reports the recorded state without claiming the process is still alive.

## Manifest

```json
{
  "schema_version": "1",
  "run_id": "proxy_20260904T000000Z_0123456789",
  "command": "proxy_build",
  "state": "succeeded",
  "project_id": "prj_example01",
  "invocation": {
    "assetIds": ["asset_0123456789abcdef01234567"],
    "resume": true,
    "force": false
  },
  "config_sha256": "...",
  "input_fingerprints": {
    "asset_0123456789abcdef01234567": "quick-sha256-v1:..."
  },
  "tools": {
    "ffmpeg": "ffmpeg version ...",
    "ffprobe": "ffprobe version ..."
  },
  "environment": {
    "package_version": "0.6.0",
    "python": "3.11.15",
    "platform": "macOS-...",
    "git_commit": null
  },
  "progress": {
    "expected_items": ["asset_0123456789abcdef01234567"],
    "completed_items": ["asset_0123456789abcdef01234567"],
    "cached_items": [],
    "skipped_items": [],
    "metrics": {}
  },
  "artifacts": [
    {"kind": "control", "path": "...manifest.json", "size": 1, "sha256": "..."}
  ],
  "warning_codes": [],
  "error": null,
  "parent_run_id": null,
  "started_at": "2026-09-04T00:00:00Z",
  "completed_at": "2026-09-04T00:00:01Z"
}
```

`status.data.stages.proxy|transcribe|sync.latestRun` exposes only the run ID/state, progress counts,
stable error code, timestamps, and manifest path. It does not copy invocation details into the
status summary.

## Privacy and size boundary

Operation logs are local control evidence. They may contain project, asset, camera, take, backend,
device, and run IDs, plus artifact paths already exposed by the CLI. They must not contain transcript,
subtitle, title, or note text; source bytes; model output; raw stderr; or arbitrary exception details.

Only `.json` and `.sha256` control files up to 16 MiB are checksummed into the operation manifest.
Large MP4/WAV/JPEG payloads and content-bearing JSONL/SRT files remain referenced by their owning
stage manifests and are not redundantly hashed or copied into the log.
