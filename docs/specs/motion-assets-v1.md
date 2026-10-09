# Local motion assets v1

The CLI supports three short speech-video graphics: `callout`, `lower_third`, and `chapter`.
It generates transparent QTRLE/ARGB MOV assets using Pillow and local FFmpeg, without a browser,
cloud renderer or additional animation runtime.

```bash
interview-edit motion build --project PROJECT --template callout \
  --text "Key idea" --secondary "Supporting point" --font /path/to/font.ttf \
  --width 1920 --height 1080 --duration-us 3000000 --json
interview-edit motion edit --project PROJECT --asset ASSET --text "Revised idea" --json
interview-edit motion verify --project PROJECT --asset ASSET --json
interview-edit cutlist motion --project PROJECT --cutlist CUTLIST \
  --item ITEM --asset ASSET --start-us 0 --duration-us 3000000 --json
```

`build` and `edit` return asset path, template, frame count, duration and dry-run state without
echoing text. Each directory under `artifact_root/motion/` contains `spec.json`, `render.mov`,
`poster.png` and `manifest.json`. Text and images contain user content: apply project privacy rules
before loading them into an agent. Font bytes are not bundled; canonical local font path and SHA-256
record generation provenance. Regeneration needs that font. Verified movie playback does not.

The model uses strict integer microseconds and dimensions, rational frame rates from 1 to 60 fps,
duration 0.8–10 seconds, enter/exit up to 2 seconds each, and a hold of at least 500 ms. Canvas sides
are bounded to 3840 and total pixels to 3840×2160. Generation rounds duration upward to a whole
frame; the manifest records measured duration and frame count. CLI generation uses project frame rate
and defaults to project dimensions; width/height can be specified. Text, template, font, dimensions,
timing and all three palette colors can be changed using `motion edit`.
Each text field allows 160 characters and two measured lines. Missing glyphs, overflow, malformed
colors and invalid timing fail before publication. Cubic easing controls alpha and a short vertical
entrance/exit; the PNG poster is the full hold.

Editing creates a new immutable directory. It never rewrites an asset referenced by an old cut.
`cutlist motion` creates a validated revision with an item-relative `kind: motion` overlay and
`motion_path` pointing to the package. Attachment must fit both the item and declared motion duration.
Shortening an overlay deliberately truncates the animation; generate a shorter source for a complete
exit. Canvas aspect must match the selected render profile. Lower-thirds with captions warn that
spacing needs review. V1 overlays may not overlap one another. They are composited before subtitles;
main audio remains intact.

Verification checks project ownership, bounded source/control sizes, SHA-256 inventory, geometry
and timing. Symlink traversal and paths outside the artifact root are rejected. Changed assets fail
preflight; cache fingerprints include the whole package. Encoder failure cleans only its private
staging directory and preserves published assets. Dry-run checks inputs/layout without writing files.

Source editability means changing retained parameters and regenerating a movie. Movie pixels are
not native text layers. Default Jianying export rejects motion-containing cuts with
`jianying_motion_unsupported`; it must not omit graphics or claim native editable motion.
Native title/subtitle/video/audio handoff remains a separate experimental path.

Opt-in `--native-effects` maps a verified MOV to an independent native video track and bundles its
source spec/font for `motion from-spec` regeneration. It does not create native editable motion text.
See [native effects](native-effects-export-jobs-v1.md). Source import accepts a bounded specification
and optional receiving-machine font override, producing a new immutable asset in the current project.
