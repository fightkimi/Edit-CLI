# Real-media Beta intake checklist

- Status: ready for use; not yet executed
- Date: 2026-09-04

Use this gate when representative creator footage becomes available. Record actual values and
results in a new dated acceptance record; do not mark an unchecked item as passed by inference.

## 1. Scope and authorization

- [ ] Identify the format: interview, talking-head, tutorial, review, or vlog.
- [ ] Record the intended audience, target duration, aspect ratio, delivery resolution, and language.
- [ ] Record must-keep passages, protected ranges, required disclosures, and forbidden material.
- [ ] Confirm the operator is authorized to process the footage locally.
- [ ] Choose `strict` or `assisted` privacy deliberately; no upload is implied by either choice.
- [ ] Keep model/dependency downloads, master rendering, version freezing, and external publishing as
      separate approval gates.

## 2. Filesystem and source safety

- [ ] Put source media and the edit project in separate directories.
- [ ] Put the artifact root outside every media root.
- [ ] Confirm available disk space for proxies, transcripts, render caches, previews, QC evidence,
      and a possible master.
- [ ] Record source filenames, byte sizes, modification times, and full SHA-256 values.
- [ ] Confirm removable drives, network shares, or symlinks have the intended read/write and
      reconnect behavior.
- [ ] Preserve source files as read-only inputs; never rename, rewrite, normalize, or relink them as
      an implicit pipeline step.

## 3. Capture and editorial map

- [ ] Record the camera/take map, reference camera, primary audio source, frame rates, resolutions,
      codecs, time bases, channel layouts, and approximate durations.
- [ ] Identify variable-frame-rate footage, discontinuous timecode, dropped clips, dual-system
      audio, rotation metadata, HDR/color metadata, and screen recordings.
- [ ] Mark B-roll/stills and whether their audio should be used or ignored.
- [ ] Define the format-specific narrative priority before semantic cutting:
      - interview: preserve answer meaning and speaker context;
      - talking-head: prioritize hook, clarity, and concise progression;
      - tutorial: preserve prerequisite and step order;
      - review: preserve evidence, tradeoffs, disclosures, and verdict context;
      - vlog: preserve chronology or make intentional time jumps explicit.

## 4. Environment and transcription gate

- [ ] Run `interview-edit doctor --project PROJECT --json` and retain the exact JSON result.
- [ ] Confirm Python, Pillow, FFmpeg, FFprobe, encoders, filters, project font, and filesystem checks.
- [ ] Select one installed local transcription backend appropriate to the machine.
- [ ] Confirm the configured model is already local, or obtain explicit download authorization.
- [ ] Run a short representative transcription sample and review language detection, names,
      punctuation, mixed-language handling, and word timestamps before the full batch.
- [ ] Treat corrected transcripts as editorial evidence; do not infer semantic cuts from fixture text
      or an unreviewed low-quality model output.

## 5. Preview-first execution

- [ ] Run full-hash ingest twice; the second run should report the expected unchanged set.
- [ ] Build checksum-valid proxies and verify representative thumbnails/contact sheets.
- [ ] Transcribe with resume enabled, then review and correct names and material errors.
- [ ] For multi-camera takes, review synchronization confidence and drift; approve manual offsets only
      from recorded evidence.
- [ ] Create and review a cut-list using integer microseconds and current source/proxy evidence.
- [ ] Run `cutlist validate` before every render revision.
- [ ] Render a preview only; review pacing, continuity, captions, overlays, framing, and cut points.
- [ ] Run preview QC and inspect its warnings and visual evidence rather than treating exit code zero
      as editorial approval.

## 6. Real-media acceptance evidence

- [ ] Record input duration, total processing time, peak disk use, artifact sizes, retry/resume events,
      and tool/backend/model versions.
- [ ] Recompute source SHA-256 values and confirm they match intake.
- [ ] Record JSON envelopes and paths for the selected cut-list, preview render, run manifest, and QC
      report without committing private content or bulky generated evidence.
- [ ] List all unverified codecs, platforms, permissions, and editorial edge cases.
- [ ] Obtain a separate explicit approval before master rendering.
- [ ] After a passing release QC, obtain a separate explicit approval before freezing a version.

## Minimum pilot set

One real project can validate the first production path, but it must not be generalized to every
creator format. Promotion beyond the private Beta should eventually cover representative footage
for each format claimed as supported, at least one mixed Chinese/English sample, multi-camera sync
where applicable, production-duration media, and the target delivery platform's codec constraints.
