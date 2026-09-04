# M2 local acceptance record

- Date: 2026-09-03
- Package version: 0.2.0
- Result: locally verified on the detected macOS development host

## Automated verification

| Command or check | Actual result |
|---|---|
| `uv run ruff check .` | passed |
| `uv run mypy src` | passed; no issues in 29 source files |
| `uv run pytest --cov=interview_edit --cov-report=term-missing` on Python 3.12.13 | 32 passed; 86% statement coverage |
| `python -m pytest -q` in the existing Python 3.11.15 environment | 32 passed |
| `uv build` | produced the 0.2.0 sdist and wheel |
| Skill Creator `quick_validate.py` | `Skill is valid!` |
| Exact PRD comparison | byte-identical to the user attachment |

The integration suite invokes the detected local FFmpeg and FFprobe rather than mocking successful media generation. Its temporary synthetic media includes H.264/AAC video, Unicode and space-containing paths, camera-map assignment, malformed media, two independently changing assets, and an outside-root symlink.

## Ingest evidence

The final wheel was installed into `/private/tmp/interview-edit-m2-acceptance-20260903-01/venv` and run from `/private/tmp`, outside the source repository.

- `command -v interview-edit` resolved to the isolated environment and `--version` returned `0.2.0`.
- `init` created a project whose source path contains Chinese characters and spaces.
- First `ingest --full-hash --json` returned one added asset.
- The second identical ingest returned the same asset ID, zero added assets, and one unchanged asset.
- The index retained integer microseconds, source time bases, stream metadata, the camera/take map, the fast fingerprint, full SHA-256, and FFprobe version.
- A malformed `.mp4` returned exit 3 with `media_probe_failed`; an existing valid index remained byte-identical in the integration test.
- An outside-root source symlink was skipped with `source_symlink_outside_root`.
- The source SHA-256 before and after the installed-wheel flow remained `a25b1e746a57f87267e1086bba9da0c0939e05589618167009728a5f070a0b41`.
- When a source changed after ingest, proxy preflight returned `source_changed_since_ingest` and preserved the earlier proxy manifest.

## Proxy and recovery evidence

The installed wheel produced:

- H.264/yuv420p viewing proxy with AAC audio;
- PCM signed 16-bit, 16 kHz, mono WAV speech-analysis proxy;
- JPEG thumbnail;
- JSON time map;
- cache manifest containing source fingerprint/full hash, FFmpeg and FFprobe versions, complete settings, output sizes, and SHA-256 values;
- JPEG contact sheet plus a row/column-to-asset manifest.

FFprobe successfully read the generated proxy, WAV, thumbnail sheet, and their expected stream properties. Codex image inspection opened the JPEG contact sheet successfully. An earlier SVG draft was rejected by the actual image viewer and was replaced before acceptance.

The first installed-wheel proxy run built one asset; the next `--resume` run reported it as cached. The automated two-asset case changed only one source and observed exactly one rebuilt plus one cached asset. Tampering with a thumbnail invalidated its manifest and rebuilt that asset.

Interruption recovery was tested by injecting `KeyboardInterrupt` when the second asset's first FFmpeg job began. The first asset's completed manifest remained, the second manifest was absent, no temporary output remained, and the next `--resume` run reported the first asset cached and built only the second.

## Packaging and repository hygiene

- The wheel contains only package code and metadata.
- The sdist contains intentional source, tests, project docs, workflow, and repository Skill files.
- No generated `.mp4`, `.mov`, `.mkv`, `.wav`, or `.jpg` file exists outside ignored build/virtual-environment paths in the repository.
- The reference repository remained read-only at commit `95c0a93dbf3c9823317b459ad06b86bcf3a0e029`; no source text was copied.
- No files are staged or committed, and nothing was pushed.

## Not verified

- GitHub Actions has not run remotely because no commit or push was requested.
- Windows, Linux, NVIDIA, network volumes, removable drives, and permission changes during a run are untested.
- Hundreds-of-gigabytes throughput, more than 20 thumbnails across multiple contact-sheet pages, and production camera codecs are unbenchmarked.
- Real VFR footage and nonzero/negative source start PTS have model coverage but not a live production-media fixture.
- Recovery semantics were exercised with an injected `KeyboardInterrupt`; an OS-level terminal SIGINT during a long encode was not separately timed.
- M3 transcription quality, incremental model execution, multi-camera offset accuracy, and drift detection remain intentionally outside M2.

## Next milestone

M3 adds local transcription and multi-camera synchronization: backend adapters, segmented/resumable transcript artifacts with word timestamps, correction layers, multi-window audio offset estimation, confidence/drift reporting, and manual offsets.
