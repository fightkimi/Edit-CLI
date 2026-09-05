# Project configuration v1

Each editing project contains `interview-edit.yaml`. The code repository and editing projects are separate; source media may be anywhere the user has authorized.

```yaml
schema_version: "1"
project_id: prj_example_12345678
name: Example creator video
media_roots:
  - /Volumes/Media/Example
artifact_root: /Users/example/Editing/Example/artifacts
privacy_mode: assisted
language: zh
timeline:
  frame_rate: 25/1
  width: 1920
  height: 1080
transcription:
  backend: auto
  model: tiny
  model_source: registry
  device: auto
  language: zh
  download_policy: ask
  chunk_duration_seconds: 300
sync:
  window_count: 3
  minimum_confidence: 0.7
  sample_rate: 8000
  envelope_hz: 100
  window_duration_seconds: 20
  max_offset_seconds: 30
  drift_tolerance_us_per_hour: 40000
render_profiles:
  preview:
    video_codec: libx264
    width: 1280
    height: 720
    frame_rate: 25/1
    audio_codec: aac
    audio_sample_rate: 48000
    audio_channels: 2
    crf: 24
  master:
    video_codec: auto
    width: 1920
    height: 1080
    frame_rate: 25/1
    audio_codec: aac
    audio_sample_rate: 48000
    audio_channels: 2
    crf: 18
audio_targets:
  integrated_lufs: -16.0
  true_peak_dbtp: -1.0
  loudness_range_lu: 11.0
qc:
  black_min_duration_seconds: 0.5
  black_pixel_threshold: 0.1
  black_picture_ratio: 0.98
  silence_min_duration_seconds: 2.0
  silence_noise_db: -50.0
  max_av_duration_delta_us: 100000
  max_timeline_duration_delta_us: 100000
  integrated_lufs_tolerance: 1.0
  true_peak_tolerance_db: 0.1
  cut_evidence_offset_us: 100000
  max_evidence_cuts: 100
  max_detection_findings: 100
proxy:
  video_codec: libx264
  max_width: 1280
  crf: 28
  preset: veryfast
  audio_sample_rate: 16000
  audio_channels: 1
  thumbnail_width: 480
  contact_sheet_columns: 4
  contact_sheet_rows: 5
fonts: []
safety:
  source_media_read_only: true
  allow_network: false
  allow_source_symlinks_outside_root: false
```

## Priority

```text
command-specific override
> INTERVIEW_EDIT_* environment value
> project interview-edit.yaml
> user config
> Pydantic system default
```

The optional user config is `${XDG_CONFIG_HOME:-~/.config}/interview-edit/config.yaml`. Tests and controlled environments can set `INTERVIEW_EDIT_USER_CONFIG` to an explicit file or to an empty string to disable it.

Supported environment overrides:

- `INTERVIEW_EDIT_ARTIFACT_ROOT`
- `INTERVIEW_EDIT_LANGUAGE`
- `INTERVIEW_EDIT_PRIVACY_MODE`
- `INTERVIEW_EDIT_TRANSCRIPTION__BACKEND`
- `INTERVIEW_EDIT_TRANSCRIPTION__DEVICE`
- `INTERVIEW_EDIT_TRANSCRIPTION__MODEL`
- `INTERVIEW_EDIT_TRANSCRIPTION__MODEL_SOURCE`

`transcription.backend` accepts `auto`, `mlx-whisper`, or `faster-whisper`. Deterministic fake
transcription is available only as an injected test fixture, never as project configuration.

## Safety and path rules

- `privacy_mode` must be chosen explicitly at initialization.
- The three V1 `safety` values are invariants, not opt-out switches:
  `source_media_read_only` must be `true`, while `allow_network` and
  `allow_source_symlinks_outside_root` must be `false`. Opposite values make the configuration
  invalid instead of silently changing or pretending to change the product boundary.
- Relative media, artifact, and font paths resolve from the directory containing `interview-edit.yaml`.
- Canonical artifact and media roots must not contain one another.
- Generated artifact paths must remain under the artifact root without traversing an existing
  symbolic-link component.
- `init` requires existing readable media directories and does not copy or write into them.
- The project directory and explicit cut-list outputs must not be placed inside a media root.
- Existing configuration is preserved unless `--force` is explicit; force preserves the stable project ID.
- Model source `registry` never implies download permission. Model source `local` must resolve to an existing path before transcription.
- A relative model path with `model_source: local` resolves from the directory containing
  `interview-edit.yaml`, consistently in both `doctor` and `transcribe`. A relative `--model`
  command override resolves from the caller's current directory.
- M3 resolves registry identifiers from local caches only. `download_policy: ask` means report that
  authorization is required; it does not make a command prompt or download by itself.
- Transcription chunk duration and all sync-analysis settings participate in downstream cache keys.
- Proxy settings participate in every per-asset proxy cache key. Changing one invalidates proxy manifests without changing source-media identity.
- QC detector thresholds and evidence limits are explicit project inputs. Changing them invalidates
  render-to-QC freshness because release decisions must be made against the same effective config
  recorded by the render.
