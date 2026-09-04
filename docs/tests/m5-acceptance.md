# M5 local acceptance record

- Date: 2026-09-04
- Package version: 0.5.0
- Result: locally verified on the detected Apple Silicon macOS host

## Automated verification

| Command or check | Actual result |
|---|---|
| `.venv/bin/ruff check .` | passed |
| `.venv/bin/ruff format --check .` | passed; 107 files already formatted |
| `.venv/bin/mypy src` | passed; no issues in 53 source files |
| `.venv/bin/pytest --cov=interview_edit --cov-report=term-missing` on Python 3.12.14 | 75 passed; 85% statement coverage |
| `python -m pytest -q` in Python 3.11.15 | 75 passed |
| `uv build --offline` | produced the 0.5.0 source distribution and wheel |
| Skill Creator `quick_validate.py` | `Skill is valid!` |

The suite uses real local FFmpeg and FFprobe processes for generated H.264/AAC media. M5 coverage
includes preview/release policy differences, black and silence detection, loudness and stream
measurements, cut evidence, safe-area and missing-glyph checks, stale evidence rejection, approval
gating, immutable snapshot creation, and tamper detection.

## QC and release-gate evidence

- A valid two-item master produced a passing release report with an integrated loudness observation,
  stream metadata, no black or silent intervals, and two local JPEG cut-point frames.
- A generated black/silent fixture produced warnings under preview policy and errors under release
  policy; the failed release report could not be frozen.
- A deliberately replaced render with mismatched stream parameters was rejected.
- A passing report modified after publication was rejected by its detached SHA-256 checksum.
- Release reports contain item IDs, timestamps, paths, measurements, and issue codes but do not copy
  title, subtitle, or transcript text.

## Version evidence

- Freeze without `--approve` returned usage exit code 2 and created no version.
- Approved freeze created `v0001` through a staging directory and atomic rename.
- The version manifest declares the output, render-run manifest, release report, detached report
  checksum, effective configuration, cut-list, and both QC evidence frames.
- `version list`, `version show`, and `version verify` succeeded; verification checked eight declared
  payload files.
- Appending bytes to the frozen output was detected as `frozen_file_modified`; replacing a declared
  payload with a symlink was detected as `frozen_file_symlink`.
- No existing version ID was reused or replaced in the exercised tests.

## Isolated final-wheel end-to-end smoke

The 0.5.0 wheel was installed from `dist/` into a new Python 3.12.13 environment and invoked from
`/private/tmp`, outside the source tree.

- `interview-edit --version` returned `0.5.0`.
- `init`, `ingest`, and `cutlist validate` succeeded for one generated source and a two-item master
  cut-list.
- Master render run `render_20260904T014638Z_0fb6f07e54` produced a 60,565-byte H.264/AAC MP4 with
  SHA-256 `e49c3d9ef43da849d26643b885131298f4982fc13978c84a34af70b850a3b9f8`.
- Release QC report `qc_20260904T014644Z_a47af4c7c1` passed with one non-blocking warning for absent
  color tags and copied two cut-point JPEGs.
- Approved freeze, list, show, and verify succeeded for `v0001`; verify checked eight payload files.
- Frozen `v0001` contains the QC report, its detached checksum, and both report-declared evidence
  frames, so the snapshot is self-contained.
- Source SHA-256 remained
  `d0593969a3abec5fd781ad0cbc228cc2b3d8f0f717832661dd47dd003a41f131` before and after the full
  render/QC/freeze flow.

The final built wheel SHA-256 was
`e540ac255a7c60ce126f163be8f3de68ba22567e2342ee7a9f9f8500db9ccbef`.

## Doctor result and environment limits

The development environment passed Python, Pillow, FFmpeg 8.1.2, FFprobe 8.1.2, portable H.264/AAC
encoders, all render/QC filters, path boundaries, source/artifact access, and the project-Skill check.
The aggregate command exits 4 in the Codex sandbox because the installed MLX backend cannot access a
Metal device. VideoToolbox also fails its real sandbox probe and correctly falls back to libx264.
No project font was configured in the synthetic smoke project, so doctor reported a font warning.

The isolated base-wheel environment intentionally had no optional transcription extra and reported
that backend as missing. This does not block the verified ingest, render, QC, or version paths.

## Safety and repository hygiene

- Source media remained read-only and byte-identical throughout all acceptance flows.
- External commands were executed as argument arrays without a shell.
- QC and version files were written below the configured artifact root and published atomically.
- Generated media and the acceptance project stayed under `/private/tmp`; build artifacts remain in
  the repository's ignored `dist/` directory.
- The reference repository remained read-only; no unlicensed source text was copied.
- The repository still has no commits. Nothing is staged, pushed, or published.

## Not verified

- Production customer media, editorial quality on a real approved cut, multi-hour performance,
  disk-pressure behavior, and production-size evidence volume.
- Windows, Linux, NVIDIA, network/removable media, and permission changes during QC or freeze.
- Host-side VideoToolbox behavior for this M5 probe; libx264 is the tested fallback.
- Cryptographic signing or defense against an administrator rewriting both payloads and their
  detached checksums.
- Remote GitHub Actions, because no commit or push was requested.

## Next milestone

M6 should complete the project Skill and references, natural-language end-to-end tests,
installation guidance, cross-directory invocation checks, and the full synthetic-media Beta
acceptance report.
