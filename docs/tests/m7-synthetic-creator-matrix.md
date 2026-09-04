# M7 synthetic creator matrix acceptance record

- Date: 2026-09-04
- Package version: 0.6.0
- Result: synthetic mechanics accepted; real-media and current real-model acceptance remain pending

## Environment evidence

The current Apple-silicon development host reported Python 3.11.15, FFmpeg 8.1.2, FFprobe 8.1.2,
the required media filters/encoders, Pillow, and a successful real H.264 VideoToolbox probe.

`interview-edit doctor --json` returned exit code 4 because the current project environment contains
neither the optional MLX Whisper nor Faster-Whisper runtime. A search found cached Python wheels for
the optional packages but no reusable local Whisper model snapshot. M7 therefore did not install a
dependency, fetch a model, or claim a current real-transcription pass. Earlier M0/M3 records remain
historical evidence only.

## Creator-format matrix

`test_five_creator_formats_validate_render_and_pass_preview_qc` generated two temporary H.264/AAC
MP4 files with FFmpeg, ingested them with full hashes, and built checksum-validated proxies. It then
exercised the following distinct cut-list structures through the real CLI boundary:

| Format | Mechanical structure | Executed stages |
|---|---|---|
| interview | two non-contiguous primary ranges representing a context-preserving jump cut | validate, preview render, preview QC |
| talking-head | one concise primary hook/point range | validate, preview render, preview QC |
| tutorial | two ordered acts representing dependent steps | validate, preview render, preview QC |
| review | primary narration with a timed evidence B-roll overlay | validate, preview render, preview QC |
| vlog | chronological primary moment followed by standalone environmental B-roll | validate, preview render, preview QC |

Every command returned a successful JSON envelope, every output was an MP4, every preview QC report
reached `passed`, and the source files' SHA-256 values were unchanged after all five scenarios. All
media, render caches, run manifests, and QC evidence were created under pytest temporary directories
and were not added to Git.

This matrix proves deterministic mechanics only. Sine-wave audio has no editorial meaning, so it
does not prove transcript accuracy, hook quality, narrative coherence, disclosure preservation,
pacing, aesthetic judgment, or suitability for a publishing platform.

## Fresh verification

| Check | Actual result |
|---|---|
| focused M7 integration test with strict media dependency mode | passed: 1 test, five scenarios, 2.54 s |
| `uv run ruff check .` | passed |
| `uv run mypy src` | passed; 53 source files |
| full pytest with strict media dependency mode | passed: 96 tests in 20.38 s |
| format check for the new integration test | passed: 1 file already formatted |
| `git diff --check` before this record | passed |

A supplemental whole-repository `ruff format --check .` was also executed and did not pass: the
current formatter would reflow six pre-existing files (`cutlist/validation.py`, `render/service.py`,
`sync/service.py`, and three existing integration tests). None is modified by M7, Ruff lint passes,
and the required project verification does not include the format command. They were deliberately
left untouched to avoid unrelated formatting noise.

## Pending real-media gate

The checklist in `real-media-beta-checklist.md` is ready but unexecuted. When representative footage
arrives, the first pilot must record source integrity, codecs, runtime/storage behavior, real local
transcription quality, semantic cut review, preview QC, and operator approval. Master rendering,
version freezing, tagging, licensing, and distribution remain separate decisions and were not
authorized or performed in M7.
