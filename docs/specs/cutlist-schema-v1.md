# Cut-list schema v1

The runtime authority is `interview_edit.models.cutlist.CutList`. The generated Draft 2020-12
snapshot is `cutlist-v1.schema.json`. JSON Schema describes field shape; the CLI validator also
enforces the cross-document and project-evidence rules below.

## Time and timeline

- Persist every edit position and duration as an integer number of microseconds in a field ending
  `_us`. Floating-point and numeric-string values are rejected for edit-time fields.
- Persist frame rate as a positive rational string such as `25/1` or `30000/1001`.
- Source ranges are source-relative. Camera cuts, overlays, and subtitles are item-relative.
- Retain each stream's FFprobe `time_base` in the media index; source identity and proxy time maps
  remain external evidence rather than duplicated cut-list fields.
- User-facing seconds and timecode are views, not persisted edit authority.

## Document shape

```yaml
schema_version: "1"
project_id: prj_example01
timeline:
  frame_rate: 25/1
  width: 1920
  height: 1080
acts:
  - act_id: act_001
    title: Opening
    items: []
subtitle_policy:
  enabled: true
  language: zh
  safe_area_percent: 5
render_profile: preview
```

`acts` and `items` retain declared order. Act titles, item notes, title text, and subtitle text are
content-bearing. `cutlist inspect` reports counts and timing but does not emit those values.

## Item kinds

Every item has a globally unique `item_id`, `kind`, and positive `timeline_duration_us`.

- `primary`: main narrative/spoken material. `content_role` may be interview, talking-head,
  tutorial, review, vlog, screen-capture, or another project-owned label.
- `broll`: standalone supplemental video. It uses its source audio when available and otherwise
  receives deterministic silence.
- `still`: an image held for the declared duration; requires `image_path`.
- `title`: a locally rasterized title/card; requires `title_text` and a readable configured or
  item-level font.
- `transition`: reserved in the enum for migration. A standalone transition item is rejected by V1
  preflight because it has ambiguous additive-versus-overlap duration semantics.

`primary` and `broll` are source-backed and require `source_id`, `source_in_us`, and
`source_out_us`. Their source range must exactly equal `timeline_duration_us`; M4 playback is 1x.

```yaml
- item_id: item_001
  kind: primary
  content_role: talking-head
  source_id: asset_0123456789abcdef01234567
  source_in_us: 62000000
  source_out_us: 78000000
  timeline_duration_us: 16000000
  audio_source: asset_0123456789abcdef01234567
  base_camera: wide
  camera_cuts: []
  overlays: []
  subtitles: []
  transition_in: null
  transition_out: null
  notes: Keep the complete explanation.
```

## Camera cuts

Camera cuts change video only. The primary/audio source continues without a splice.

```yaml
camera_cuts:
  - cut_id: cut_001
    camera_id: close
    start_us: 4000000
    duration_us: 8620000
```

The primary source must have a camera and take mapping. `base_camera`, when declared, must identify
that source asset's camera. Each target camera must be unique in the take and match non-uncertain M3
sync evidence. Mapping uses `camera_time = reference_time + offset`, including the recorded linear
drift term.

## Visual overlays

Overlays change the displayed picture while the underlying item audio continues. They may not
overlap one another in V1.

```yaml
overlays:
  - overlay_id: overlay_001
    kind: broll
    start_us: 9000000
    duration_us: 4000000
    source_id: asset_89abcdef0123456789abcdef
    source_in_us: 1000000
    source_out_us: 5000000
  - overlay_id: overlay_002
    kind: still
    start_us: 14000000
    duration_us: 1500000
    image_path: ../../graphics/chart.png
  - overlay_id: overlay_003
    kind: title
    start_us: 0
    duration_us: 2000000
    text: Chapter one
    font_path: ../../fonts/title.ttf
```

`broll` requires an indexed video source and an exact source range. `still` requires an existing
image. `title` requires nonempty text and a readable local font. Exact B-roll range reuse is a
warning so intentional reprises remain possible and auditable.

## Subtitles

```yaml
subtitles:
  - subtitle_id: subtitle_001
    start_us: 0
    duration_us: 2200000
    text: A corrected subtitle line.
    font_path: ../../fonts/subtitle.ttf
```

Subtitles are nonempty, in-bounds, and non-overlapping within an item. Font precedence is subtitle,
item, then the first project-configured font. When `subtitle_policy.enabled` is false, declared
subtitle text remains in the edit document but is not rasterized or rendered.

## Transitions

M4 implements a basic fade through black. A transition must appear identically on both neighboring
content items:

```yaml
# preceding item
transition_out:
  kind: fade
  duration_us: 300000

# following item
transition_in:
  kind: fade
  duration_us: 300000
```

The duration may not exceed half of either adjacent item. Transitions do not change the additive
sum of item durations in V1.

## Strict render preflight

`subtitle_policy.style` is an optional `standard|minimal` preset, defaulting to `standard`.
Standard retains a dark caption background; minimal uses smaller outlined text without the box.
Both use the declared local font and safe-area policy; title cards retain their existing style.
This is a cut-list-wide policy, not per-word animation or arbitrary CSS styling. Unknown styles
remain schema errors. Style participates in text-raster and item cache identity.

Text is wrapped using measured font width without truncating content. A layout exceeding four
lines or containing a glyph wider than the available line fails with `text_layout_overflow`.
It must be split or revised before rendering; a partial raster must never replace an output.

`cutlist validate` and `render` enforce the same preflight:

- schema version and unknown-key rejection;
- project ID equality and globally unique act/item/cut/overlay/subtitle IDs;
- nonempty render selection, positive durations, ordered exact source ranges, and source bounds;
- current media index/source evidence and checksum-valid preview proxies;
- camera/take membership, sync report camera/asset identity, and non-uncertain status;
- in-item bounds and non-overlap for camera cuts, overlays, and subtitles;
- existing image and font assets;
- complete text layout without silent truncation;
- identical adjacent transition pairs and maximum duration;
- configured render profile, positive rational output frame rate, and even H.264 dimensions.

Warnings do not block rendering. Any error returns exit code 3 before FFmpeg starts and does not
create or replace a render output.
