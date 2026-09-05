# V1 operation-run observability

- Status: implemented and self-verified
- Date: 2026-09-04

## Goal

Make proxy, transcription, and synchronization work diagnosable after success, handled review,
failure, or interruption without logging transcript text or source content. Each real invocation
should have one correlation ID and one atomically updated terminal run manifest under
`artifacts/logs/`.

## Operator questions

1. Which command and content-safe asset/take IDs were selected?
2. How many selected items completed, hit cache, were skipped, or remain resumable?
3. Did the run succeed, require review, fail, or get interrupted, and what stable error code explains
   the outcome?
4. Which small control artifacts prove the result without duplicating or hashing large media files?

## Acceptance criteria

- Non-dry proxy, transcribe, and sync calls create unique `proxy_*`, `transcribe_*`, or `sync_*`
  run IDs and return them through the service result and CLI JSON envelope.
- The first manifest state is `running`; every handled exit becomes exactly one of `succeeded`,
  `review_required`, `failed`, or `interrupted`.
- Proxy checkpoints after each selected asset. Transcription checkpoints after each completed or
  resumed chunk and selected asset. Sync records the selected take/camera set and whether manual
  review remains.
- Logs contain stable IDs, normalized flags, config/input fingerprints, bounded environment/tool
  metadata, counts, stable error/warning codes, and checksums only for small control artifacts.
- Logs never contain transcript/subtitle/title text, model output, raw stderr, source bytes, or
  arbitrary exception details.
- `status` exposes a content-safe `latestRun` summary per proxy/transcribe/sync stage without making
  a failed retry invalidate an older current artifact.
- Dry runs write no log and return no run ID.
- Focused interruption/failure/success tests and the full project verification suite pass.

## Non-goals

- No remote telemetry, metrics backend, alerts, uploads, or network access.
- No logging of complete FFmpeg stderr or transcription text.
- No predictive disk-space blocking threshold in this patch. Current evidence lacks representative
  production bitrates, durations, and codec/output ratios; `doctor.freeBytes` and the real-media
  checklist remain the honest evidence until measurements exist.
- No change to render/QC/version evidence formats beyond linking the new generic operation-run
  protocol from documentation.

## Planned changes

1. Add a strict operation-run model and atomic local recorder.
2. Add failing lifecycle tests for success, review-required, failure, interruption, privacy, and dry
   run behavior.
3. Integrate the recorder at service boundaries and expose run IDs in CLI envelopes.
4. Extend status with latest-run summaries and update stable specs/Skill recovery guidance.
5. Run focused and full verification, build packages, and record residual limits.

## Verification evidence

- The initial focused run failed during collection because the operation-run model/service did not
  exist, establishing the expected red baseline.
- Recorder unit coverage verifies running-to-success transitions, stable failure identity, control-
  artifact size/type boundaries, transcript-text exclusion, and disabled/dry-run behavior.
- Integration coverage verifies proxy and transcription interruption checkpoints, resumed/cached
  progress, low-confidence sync as `review_required`, successful CLI `runId`/artifact linkage, and
  `status.latestRun` summaries.
- A failed proxy retry caused by unavailable media tools remains visible as the latest failed run
  while the prior checksum-bearing proxy artifacts remain `current`.
- Expected failures promote the operation ID into the JSON error envelope without copying private
  exception details into the operation manifest.
- Full test suite: 108 passed on local Python 3.11.15.
- Statement coverage: 86% overall; the new operation recorder is 90% covered.
- `ruff check .`: passed.
- `mypy src`: passed for 56 source files.
- `uv build`: produced the 0.6.0 sdist and wheel successfully.

## Residual limits

- Ingest does not yet emit a generic operation run; render and QC retain their existing specialized
  evidence formats.
- Operation logs are append-only and have no retention/cleanup command yet.
- A force-killed process can leave `state: running`; status deliberately reports recorded state and
  does not infer liveness.
- Predictive disk-space gating remains deferred until representative real-media measurements can
  justify output-ratio assumptions and thresholds.
