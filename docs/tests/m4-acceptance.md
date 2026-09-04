# M4 local acceptance record

- Date: 2026-09-04
- Package version: 0.4.0
- Result: locally verified on the detected Apple Silicon macOS host

## Automated verification

| Command or check | Actual result |
|---|---|
| `.venv/bin/ruff check .` | passed |
| `.venv/bin/ruff format --check .` | passed; 92 files already formatted |
| `.venv/bin/mypy src` | passed; no issues in 46 source files |
| `.venv/bin/pytest --cov=interview_edit --cov-report=term-missing` on Python 3.12.13 | 65 passed; 85% statement coverage |
| `python -m pytest -q` in Python 3.11.15 | 65 passed |
| `uv build --offline` | produced the 0.4.0 source distribution and wheel |
| Skill Creator `quick_validate.py` | `Skill is valid!` |

The integration suite calls the detected FFmpeg and FFprobe binaries for successful media jobs. It
uses generated H.264/AAC sources and verifies actual stream properties, durations, representative
frame colors, output bytes, source bytes, and run manifests rather than treating argument
construction alone as render success.

## Cut-list and preflight evidence

- The committed JSON Schema is compared exactly with the strict Pydantic runtime model.
- Unknown fields and floating-point edit times are rejected. Persisted edit boundaries use integer
  microseconds.
- Scaffold emits a blank deterministic cut-list or a chronological skeleton only from a current,
  checksum-valid corrected transcript.
- Inspect reports counts and timing without returning act titles, notes, subtitle text, or transcript
  text.
- Invalid schema/domain data returns exit 3 and creates no render-run manifest or output.
- A still path that exists but is not a readable image now returns `image_asset_invalid` during
  preflight rather than failing inside rendering.
- Validation covers source freshness and bounds, preview-proxy checksums, fonts and images, subtitle
  and overlay ranges, globally unique IDs, synchronized camera evidence, paired transitions, and
  profile compatibility.

## Render evidence

Real synthetic-media tests verified:

- complete-timeline rendering plus combined `--act` and `--item` selection;
- preview rendering from verified M2 proxies and master rendering from indexed originals;
- measured first-pass and applied second-pass EBU R128 loudness normalization for master output;
- continuous primary audio while a synchronized camera cut changes blue video to red and a B-roll
  overlay changes it to green;
- paired fade-out/fade-in filters at adjacent item boundaries;
- a still timeline item, Chinese subtitle, and independent Chinese title item;
- two deterministic 1280x720 RGBA text rasters with non-empty alpha channels;
- checksum-validated item-cache hits on `--resume`;
- terminal `succeeded`, `failed`, and `interrupted` run states, including return code 130 for the
  interrupted FFmpeg job;
- atomic publication and preservation of a previous successful output when a differing replacement
  is attempted without `--force`;
- unchanged bytes for every source-media file exercised by the camera/B-roll test.

## Isolated final-wheel smoke

The 0.4.0 wheel was force-reinstalled without source-tree imports into a temporary Python 3.12.13
environment and invoked from `/private/tmp`.

- `interview-edit --version` returned `0.4.0`.
- A two-item cut-list with a Chinese subtitle and independent Chinese title passed
  `cutlist validate`.
- A forced render rebuilt both normalized item caches and atomically published a 24,446-byte MP4.
- FFprobe reported H.264/yuv420p video at 1280x720 and AAC audio at 48 kHz stereo; observed container
  duration was 1.221333 seconds for the 1.2-second edit timeline.
- Output SHA-256 was
  `2663e1976d572317e2813759b576f226116ebcb527c4431c220648a3fc9a9377`.
- A following `--resume` render reported both items as `cached` and retained the same output SHA-256.

## Doctor result and environment limits

The current project environment passed Python, Pillow, FFmpeg 8.1.2, FFprobe 8.1.2, portable H.264
and AAC encoders, required render filters, path boundaries, source/artifact access, configured font,
and project-Skill checks. Pillow 12.3.0 is installed and locked through the declared
`Pillow>=11.3,<13` constraint.

The aggregate doctor command exits 4 inside the Codex sandbox because MLX cannot access a Metal
device there. VideoToolbox also fails its real sandbox probe and correctly selects libx264. M3
separately established that the installed MLX backend and the existing local model run on the host
with Metal. A base-only isolated wheel intentionally has no optional transcription backend, so its
doctor result also reports that missing extra; neither condition blocks the verified M4 render
path.

## Safety and repository hygiene

- Source files are resolved through the media index and are never written by the render service.
- Text, image, font, proxy, sync, source, configuration, and cut-list identities feed render evidence
  or cache keys as applicable.
- FFmpeg commands are stored as argument arrays with return codes, not shell strings.
- Generated media and temporary acceptance projects stayed outside the repository or in ignored
  build paths.
- The reference repository remained read-only; its production methods informed the design, but no
  unlicensed source text was copied.
- The new repository still has no commits. Nothing is staged, pushed, or published.

## Not verified

- Production customer media, multi-hour performance, disk-pressure behavior, and production-size
  render throughput.
- Visual and audio quality judgments for a real approved creator-video cut.
- Windows, Linux, NVIDIA, network/removable media, and permission changes during an encode.
- Host-side VideoToolbox behavior for this M4 encoder probe; the portable libx264 path is the tested
  fallback, while M0 separately verified VideoToolbox on the host.
- Remote GitHub Actions, because no commit or push was requested.
- M5 automatic QC, release gating, and version freeze commands.

## Next milestone

M5 adds automatic media QC and evidence, the release gate, and immutable version operations:
`freeze`, `list`, `show`, and `verify`.
