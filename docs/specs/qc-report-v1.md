# QC report protocol v1

Each real `qc` call creates an append-only directory at
`artifacts/qc/<report_id>/`. `report.json` is accompanied by `report.sha256`; evidence paths inside
the report resolve to files below the same directory. A dry run writes nothing.

## Identity and policy

The report binds these immutable observations:

- `report_id`, `project_id`, `run_id`, `policy`, terminal `state` and timestamps;
- render-manifest path and SHA-256;
- effective configuration, cut-list, and output hashes recorded by the render;
- render profile and the exact thresholds used by QC;
- FFmpeg/FFprobe versions and every executed argument array with return code.

`preview` and `release` use the same measurements. Integrity failures are `blocking` or `error` in
both policies. Sustained unplanned black/silent spans, loudness deviation, true-peak excess,
unsafe text, and missing glyphs are `warning` in preview and `error` in release. Release additionally
requires a master run. A report passes only when it contains no `blocking` or `error` finding.

## Findings

Every finding contains:

```json
{
  "severity": "info|warning|error|blocking",
  "code": "stable_machine_code",
  "message": "content-free summary",
  "item_id": "item_001",
  "timeline_time_us": 1200000,
  "source_id": "asset_...",
  "evidence_path": "/project/artifacts/qc/qc_.../evidence/example.jpg",
  "suggested_action": "Review the evidence and cut-list timing.",
  "details": {}
}
```

Reports never copy transcript, subtitle, title, note, or act-title text. Text findings expose only
placement, bounds, and counts.

## Measurements and stream checks

The report stores:

- video/audio stream metadata, including codec, dimensions, rational frame rate, pixel format,
  sample rate/channels, duration, and color metadata when FFprobe supplies it;
- black and silence intervals as integer microsecond ranges;
- integrated LUFS, true peak dBTP, and loudness range;
- A/V duration difference and selected-cut-list/output duration difference.

Default thresholds come from `interview-edit.yaml` and are documented in
`project-config-v1.md`. Missing/corrupt output, stale run inputs, missing streams, stream mismatch,
and excessive duration differences cannot be waived with `--force`.

## Evidence

For each bounded cut point, QC extracts JPEG frames before and after the cut. Black detections also
receive a representative frame. Every evidence entry records kind, absolute path, byte size,
SHA-256, integer timeline position, and item ID when available.

Cut points include selected-item boundaries plus camera-cut and overlay boundaries. The configured
maximum bounds evidence growth; truncation never changes a finding's severity.
