# SDR source color policy and diagnosis

Status: implemented in the local CLI. Native Jianying parameter mapping remains unverified and
paused; a colored cut-list cannot be silently exported without its correction.

## Commands

```text
interview-edit review color --project PROJECT --asset ID [--in-us 0] [--out-us US] \
  [--samples 4] [--reference ID] [--cutlist REVISION] [--json]
interview-edit cutlist color --project PROJECT --cutlist REVISION --asset ID \
  [--brightness VALUE] [--contrast VALUE] [--gamma VALUE] [--saturation VALUE] [--output NAME]
interview-edit cutlist color --project PROJECT --cutlist REVISION --asset ID --reset [--output NAME]
```

Global dry-run creates no image/revision or media-processing job. `cutlist color` requires at least
one value or reset; unspecified values preserve the existing source settings. A new validated YAML
is published under artifact cut-list revisions, never over the original.

## Additive schema-1 policy

```yaml
color_policy:
  by_source:
    asset_0123456789abcdef01234567:
      brightness: 0.03
      contrast: 1.04
      gamma: 1.05
      saturation: 0.98
```

Values are finite strict numbers: brightness -0.15–0.15, contrast/gamma 0.75–1.25, saturation 0–1.5.
Default policy is empty; default correction is 0/1/1/1 and emits no filter. Unknown/nonvideo source
IDs and active correction on known PQ/HLG HDR sources fail validation before rendering. Reset removes
that source's policy. No free-form filter expression, per-frame auto adjustment or LUT is accepted.

The renderer applies the actual interval camera's correction, and each B-roll video's own source
correction, before composition and subtitles. Static images, titles and subtitles retain their
existing treatment. Cache keys include only active corrections of relevant visual sources. Neutral
and unrelated source settings preserve cache reuse. Source files, audio treatment, timeline duration
and QC/master/freeze gates are preserved.

`eq` behavior and parameters were checked against local FFmpeg 9.0.2 help and its
[official filter reference](https://ffmpeg.org/ffmpeg-filters.html#eq). CI executes real sample/render
cases on the repository's Linux, Windows and Mac FFmpeg environments. Brightness/gamma are image
operations, not calibrated photographic exposure compensation.

## Diagnosis and comparison artifacts

The source window defaults to the first three seconds, clamped to known video duration. Choose a
window up to 30 seconds and 2–8 samples. Original source media is read only; sampling uses real
presentation timestamps converted to the normalized source clock. Source clock origins are recorded.
Nonzero container start offsets and the final available frame are handled explicitly. When stream
video duration is known, it constrains the window even if container duration includes a start offset.

`artifact_root/review/color_<UUID>/` contains original/after sample JPEGs, a labeled contact sheet,
optional reference frames and typed `report.json` (schema 1). It records source IDs, range/timestamps,
clock origins, source fingerprints, input hashes, correction parameters/status, sample/image hashes
and before/after pixel statistics. The reference camera must have confirmed same-take mapping; its
range is synchronized through existing source-time/sync evidence. Its sample times/hashes are
recorded, and configured reference correction is used when a cut-list is supplied.

Without a cut-list, the comparison uses a **proposed** bounded correction: low-variation frames are
left neutral; otherwise a small brightness suggestion derives from sampled luma or reference-camera
mean luma. This never changes edit settings. With `--cutlist`, the comparison uses **configured**
source settings (or neutral if absent). Apply chosen values explicitly through `cutlist color`,
render the returned revision as preview, and review it before any master.

Metrics are mean decoded RGB-derived luma, 5th/95th percentiles, mean HSV-style saturation and
near-dark/near-white fractions. Samples are JPEG thumbnails; these are heuristic image statistics,
not sensor clipping, calibrated colorimetry, white balance, skin-tone acceptance or scene meaning.
Unknown transfer metadata, low variation and increased near-white pixels are visible warnings.
Both report and CLI retain `qualityVerified=false`. Numeric CLI summaries are content-safe; the
images contain footage, so existing strict/assisted privacy rules apply before agent inspection.

Input/source/sync/cut-list changes during diagnosis stop atomic publication and remove only its
staging directory. Prior reviews are preserved. Failed decoding is an error, never a neutral result.
Known HDR is rejected because this feature provides no verified HDR tonemapping workflow.

## Editable draft boundary

`export jianying` rejects non-neutral color policy with `jianying_color_unsupported`, before copying
resources. Current native templates do not have a tested mapping for these settings. To hand off an
original-based editable draft, explicitly reset source corrections in a new revision and use the
comparison as a guide for native manual grading. Do not represent baked or discarded color settings
as editable native parameters. This does not resume paused native-client acceptance.
