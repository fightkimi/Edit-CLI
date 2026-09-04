# M3 local acceptance record

- Date: 2026-09-03
- Package version: 0.3.0
- Result: locally verified on the detected Apple Silicon development host

## Automated verification

| Command or check | Actual result |
|---|---|
| `uv run ruff check .` | passed |
| `uv run ruff format --check .` | passed; 77 files already formatted |
| `uv run mypy src` | passed; no issues in 38 source files |
| `uv run pytest --cov=interview_edit --cov-report=term-missing` on Python 3.12.13 | 47 passed; 84% statement coverage |
| `python -m pytest -q` in Python 3.11.15 with NumPy 2.4.6 | 47 passed |
| `uv build` | produced the 0.3.0 sdist and wheel |
| Isolated Python 3.11 wheel install | installed 0.3.0 and base dependencies; CLI reported 0.3.0 |
| Skill Creator `quick_validate.py` | `Skill is valid!` |

The final wheel is 59,108 bytes with SHA-256
`651ff02b3c49cf56773ce457e204849919a6f9eff024a9f1859f08c7ca9007f3`. Wheel metadata declares
NumPy, Pydantic, PyYAML, and Typer as base dependencies; MLX and Faster-Whisper remain explicit
extras. The source distribution includes the intentional docs, tests, workflow, and project Skill.

NumPy 2.4.6 and missing cached packaging metadata were downloaded only after explicit approval for
dependency verification. No transcription model was downloaded during M3.

## Local transcription evidence

The M0 synthetic Chinese speech WAV and the previously authorized local
`mlx-community/whisper-tiny` snapshot were used with `HF_HUB_OFFLINE=1`. The real command ran on the
host because the Codex sandbox does not expose Metal:

```text
interview-edit transcribe --project <acceptance-project>
  --asset asset_ac0a4147d63d5a912aeada00 --language zh
  --model <existing-local-snapshot> --device metal --resume --json
```

Observed results:

- first run: exit 0, backend `mlx-whisper` 0.4.3 on `metal`, one asset built;
- artifact validation: 2 segments, 23 words, every segment/word time an integer microsecond;
- raw JSONL contained no correction-layer field;
- second identical run: exit 0 and the asset was reported as cached;
- source SHA-256 before and after remained
  `f95968cfb163b401e33c453556223f88884571705607cdf85ad3d1e6db3c83fa`;
- a nonexistent registry model under forced-offline execution returned exit 3 with
  `model_download_authorization_required` and stated that no download was attempted.

The integration suite also exercised a 61-second, three-chunk transcript. An injected
`KeyboardInterrupt` on chunk two left chunk one's atomic checkpoint. The next `--resume` reused one
chunk and called the backend only for the remaining two.

Changing `dictionaries/corrections.yaml` rebuilt only corrected JSONL/SRT derivatives; the raw JSONL
bytes remained identical. Word and segment evidence retained their original timestamps.

## Synchronization evidence

The final wheel was installed into an isolated Python 3.11 environment and invoked from
`/private/tmp`, outside the repository. A generated two-camera H.264/AAC take placed the same
nonrepeating audio 250 ms later on the close camera.

Observed installed-CLI result:

- `sync --take take-01 --reference-camera wide --visual-check --json` returned exit 0;
- reported convention: `camera_time = reference_time + offset`;
- close-camera offset: exactly 250,000 microseconds;
- estimated drift: 0 microseconds/hour and 0 ppm;
- aggregate confidence: 0.8244685, status `confirmed`, provenance
  `automatic_audio_correlation`;
- three beginning/middle/end measurements were retained, including one rejected low-quality edge
  measurement rather than hiding it;
- three checksum-bearing JPEG evidence files were written; FFprobe identified MJPEG 960x270, and
  Codex image inspection opened a sheet successfully;
- a second identical installed-wheel call reported `cached: true` after verifying evidence hashes.

Unrelated camera audio was exercised through the CLI and returned exit 3 with
`sync_confidence_insufficient` while preserving `sync.json`. Re-running with
`--manual-offset close=125ms` returned exit 0 and stored 125,000 microseconds with status `manual`
and provenance `manual_override`. A synthetic changing offset also verified positive drift
detection near 2,000 ppm.

## Safety and repository hygiene

- Source revision and audio/video proxy size/SHA-256 are checked before content analysis.
- Backend subprocesses use argument arrays with `shell=False`.
- Model lookup uses local paths or local-only Hugging Face resolution; missing names cannot trigger
  a model download.
- Raw recognition is separate from corrections; uncertain sync is separate from manual override.
- No generated media exists in the source tree outside ignored environments/build output.
- The reference repository remains read-only and clean at
  `95c0a93dbf3c9823317b459ad06b86bcf3a0e029`; no source text was copied.
- The new repository still has no commits. All project files are untracked; none are staged, pushed,
  or published.

## Not verified

- Production-size Whisper models, real interview accuracy, speaker diarization, and multi-hour
  thermal/throughput behavior.
- Faster-Whisper runtime behavior, because it is not installed on this development machine.
- Windows, Linux, NVIDIA CUDA, network/removable media, and permission changes during a run.
- Real-camera oscillator drift, strongly repetitive audio, more than one clip per camera/take, and
  production camera start-time edge cases.
- OS-level SIGINT timing during actual MLX inference; recovery is verified through an injected
  interruption at the service boundary.
- Remote GitHub Actions, because no commit or push was requested.

## Next milestone

M4 adds cut-list scaffold/inspect/strict validation, transcript-addressable clip selection, camera
switches, overlays/B-roll/stills, subtitles, and deterministic validation gates before rendering.
