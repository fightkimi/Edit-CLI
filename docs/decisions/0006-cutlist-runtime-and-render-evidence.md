# ADR 0006: Strict cut-list runtime and evidence-backed rendering

- Status: accepted
- Date: 2026-09-03

## Context

M4 turns editorial intent into media output, which is the first stage capable of consuming many
inputs and producing a costly result. The edit model must remain understandable outside the Python
runtime, camera switches must preserve the chosen audio track, and a failed or interrupted render
must never be confused with a completed deliverable.

The PRD uses `interview` as an example item kind while ADR 0002 and the frozen cut-list draft use the
broader `primary` kind plus `content_role`. The measured FFmpeg 8.1.2 build supports the required
video/audio composition and loudness filters but lacks `drawtext`, `subtitles`, and ASS filters.

## Decision

- Make strict Pydantic v2 models the runtime authority and publish a JSON Schema snapshot for other
  tools. Unknown keys are rejected and every persisted edit time is an integer microsecond value.
- Keep `primary` as the main spoken/narrative item kind. Interview, talking-head, tutorial, review,
  vlog, and screen-recording semantics remain values of `content_role`, not separate execution
  branches.
- Reserve the `transition` item enum for forward compatibility but reject standalone transition
  items in V1 preflight. Implement basic transitions as identical paired edge-fade specifications on
  adjacent content items; item durations remain additive and inspectable.
- Resolve every source through the current media index. Preview uses verified M2 proxies; master
  uses indexed originals. Camera timing is mapped through M3 offset and linear drift evidence, and
  uncertain cameras cannot render.
- Build each selected content item into a normalized checksum-validated cache object. Assemble only
  complete cache objects and publish the final output through an atomic replace.
- Keep the selected primary/audio source continuous while camera cuts and full-frame visual
  overlays replace only the displayed video.
- Rasterize titles and subtitles locally into transparent PNGs, then compose them through FFmpeg's
  `overlay` filter. This avoids depending on FFmpeg text-filter build options and makes font/input
  hashes explicit cache inputs. Use Pillow through the declared `Pillow>=11.3,<13` runtime
  dependency; M4 was verified with Pillow 12.3.0.
- For master output, run a measured first loudness pass and feed its values to the second EBU R128
  pass. Preview skips this delivery normalization.
- Write one terminal manifest per render attempt. It records `running`, then `succeeded`, `failed`,
  or `interrupted`, together with arguments, configuration/cut-list/input fingerprints, cache
  decisions, exact FFmpeg argument arrays and version, selected encoder, and any published output
  checksum. A manifest is evidence, not a mutable global completion flag.

## Consequences

- Invalid or stale editorial references fail before FFmpeg starts, with exit code 3 and no render
  publication.
- Cache reuse is safe across resumptions because it depends on the complete edit item, profile,
  source identities, sync evidence, text/image assets, selected encoder, and implementation schema.
- Text rendering now needs a portable local rasterizer and a declared font. This adds a small runtime
  dependency but avoids prescribing a custom FFmpeg build.
- Existing still-image paths are opened and verified during cut-list preflight, so a mislabeled or
  corrupt image fails with exit code 3 before any render attempt is created.
- V1 fades pass through black rather than overlapping adjacent pictures. Cross-dissolve and audio
  crossfade can be added later with an explicit non-additive timeline contract.
- Standalone `transition` items remain representable at the schema enum level for migration but are
  intentionally blocked by V1 domain validation so their duration semantics cannot be guessed.
