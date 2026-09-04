# Transcript and synchronization protocols v1

## Shared rules

- JSON object keys use `snake_case` inside durable artifacts.
- All durable time positions and durations use signed or non-negative integer microseconds (`*_us`).
- Human-readable decimal seconds are presentation only.
- Paths are absolute at the execution boundary and source media remains read-only.
- Every cache hit validates its manifest inputs and output size/SHA-256.

## Transcript segment JSONL

`raw.jsonl` and `corrected.jsonl` contain one JSON object per line:

```json
{
  "schema_version": "1",
  "segment_id": "seg_00000001",
  "asset_id": "asset_0123456789abcdef01234567",
  "start_us": 1250000,
  "end_us": 3480000,
  "text": "这里是识别文本",
  "words": [
    {
      "start_us": 1250000,
      "end_us": 1680000,
      "text": "这里",
      "probability": 0.94
    }
  ]
}
```

`end_us >= start_us`. Word timestamps are clamped to their owning segment. Probability is optional
and is the only persisted float in this record; it is model evidence, not edit time. Empty segments
are omitted.

The corrected layer retains the same IDs/times/word evidence and changes only `text` plus individual
word text where a literal rule matches. It adds:

```json
{"correction_rule_ids": ["brand-name"]}
```

The raw layer never contains this field and is never overwritten by correction logic.

## Correction dictionary

`dictionaries/corrections.yaml` is optional:

```yaml
schema_version: "1"
rules:
  - id: brand-name
    find: 光厂
    replace: Guang Tech
    enabled: true
```

Rules are applied literally, case-sensitively, and in file order. IDs are unique. Empty `find`
values are invalid. Changing this file invalidates only corrected derivatives, not raw recognition.

## Transcript manifest

`artifacts/transcripts/<asset_id>/manifest.json` contains:

```json
{
  "schema_version": "1",
  "asset_id": "asset_0123456789abcdef01234567",
  "source_fingerprint": "quick-sha256-v1:...",
  "audio_proxy_sha256": "...",
  "transcription_cache_key": "...",
  "backend": "mlx-whisper",
  "backend_version": "0.4.3",
  "model": "tiny",
  "resolved_model": "/local/cache/snapshot",
  "device": "metal",
  "language": "zh",
  "parameters": {
    "chunk_duration_seconds": 300,
    "condition_on_previous_text": false,
    "word_timestamps": true
  },
  "correction_fingerprint": "sha256:...",
  "segment_count": 42,
  "word_count": 318,
  "outputs": [
    {"kind": "raw_jsonl", "path": "...", "size": 1, "sha256": "..."}
  ],
  "completed_at": "2026-09-03T00:00:00Z"
}
```

Each chunk checkpoint repeats the schema/asset/cache key and stores chunk index, start/end
microseconds, detected language, and that chunk's globally adjusted segments. Checkpoints are
published atomically. `--resume` reuses only checkpoints whose identity and bounds validate.

## Sync report

`artifacts/sync/<take_id>/sync.json` contains:

```json
{
  "schema_version": "1",
  "take_id": "take-01",
  "reference_camera_id": "wide",
  "convention": "camera_time = reference_time + offset",
  "analysis": {
    "sample_rate": 8000,
    "envelope_hz": 100,
    "window_count": 3,
    "window_duration_us": 20000000,
    "max_offset_us": 30000000,
    "minimum_confidence": 0.7
  },
  "cameras": [
    {
      "camera_id": "close",
      "asset_id": "asset_0123456789abcdef01234567",
      "status": "confirmed",
      "offset_us": 125000,
      "drift_us_per_hour": 18000,
      "drift_ppm": 5,
      "confidence": 0.93,
      "provenance": "automatic_audio_correlation",
      "windows": [
        {
          "reference_center_us": 10000000,
          "offset_us": 125000,
          "confidence": 0.95,
          "peak_margin": 0.18
        }
      ]
    }
  ],
  "evidence": [
    {
      "kind": "visual_contact_sheet",
      "path": "...",
      "reference_time_us": 10000000,
      "size": 12345,
      "sha256": "..."
    }
  ],
  "completed_at": "2026-09-03T00:00:00Z"
}
```

The reference camera is included with zero offset and provenance `reference`. Other provenance
values are `automatic_audio_correlation` and `manual_override`. Automatic statuses are:

- `confirmed`: confidence meets threshold and no material drift was detected;
- `drifting`: confidence meets threshold and measured drift exceeds the configured tolerance;
- `uncertain`: confidence is below threshold or too few usable windows remain;
- `manual`: an explicit operator value replaced the automatic estimate.

An uncertain report is still written so evidence survives, but the CLI envelope has `ok: false` and
process exit 3. Manual offsets always include the original text value and command provenance.
For a short take, each analysis window is bounded to at most half the common duration so the report
still contains distinct beginning, middle, and end measurements.

## Cache invalidation

Transcript raw cache identity includes schema, source fingerprint/full hash, validated audio proxy
hash, backend and version, requested and resolved model identity, device, language, and recognition
parameters. Correction dictionary bytes are intentionally excluded from raw identity.

Sync identity includes schema, take/camera membership, validated audio proxy hashes, analysis
settings, manual offsets, and NumPy implementation version. Visual evidence is regenerated when the
sync identity changes or `--force` is used.
