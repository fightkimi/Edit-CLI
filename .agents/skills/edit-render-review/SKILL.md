---
name: edit-render-review
description: Review visual composition and render quality in this interview-edit project. Use for blurry previews, awkward B-roll, unreadable title layouts, aspect-ratio problems, transition dips, or requests for motion effects the CLI may not support.
---

# Render and composition review

Read [interview-edit](../interview-edit/SKILL.md) for privacy, status and execution gates. Read the
current render profile, cut-list schema, run manifest and QC before diagnosing an output. Keep
source media read-only and generated evidence under the artifact root. No direct FFmpeg, Remotion,
cloud renderer or media upload replaces the CLI.

## Separate the symptom from its cause

| Symptom | Check before changing anything | Supported next step |
|---|---|---|
| Soft picture | Source resolution, proxy settings, preview profile and actual encoder | Explain proxy/preview limits; test one authorized profile change; do not upscale and claim restored detail |
| Black bars or tiny subject | Source and output aspect ratio; current renderer uses fit plus padding | Use a compatible composition/profile; subject-tracking crops need engine work |
| Distracting B-roll | Does the image explain the current sentence? Is the span synchronized? | Adjust an indexed visual overlay while preserving primary audio |
| Text collision | Longest title/caption, glyph coverage, safe area, existing image text | Revise text and timing within supported fields; use caption review |
| Dip at a join | Adjacent transition fields and actual audio/video fades | Remove an unnecessary fade or change the cut; a fade is not an overlapping dissolve |
| Color jump | Source camera lighting and whether the issue appears in permitted proxy evidence | Use review color and a bounded cutlist color revision; LUT/calibrated matching remains unsupported |

Default preview is 1280x720 at CRF 24, made from viewing proxies; master defaults to 1920x1080
and reads indexed originals. Treat these as repository defaults to verify, not project overrides.
VideoToolbox quality and libx264 CRF are not numerically comparable. Read the actual encoder from
the run before claiming a codec improvement. Do not request a master merely to diagnose pacing.

## Review sequence

Inspect opening, each changed join, B-roll entrances/exits, dense text, important demonstrations,
payoff and final frame using permitted preview/QC evidence. Check first/middle/last frames of
text-bearing intervals. Check playback for motion and audio when available; stills alone cannot
prove smooth transitions. Preserve meaningful source text rather than cropping it to fill a canvas.

For each revision change one coherent cause, validate the full cut-list and preview the affected
item/act before the full preview. Compare the same range, output size and encoder when assessing
picture changes. Report what was directly observed, measured, inferred and not checked.
Follow the main Skill's bounded recovery rules and separate master and freeze approvals.

## Motion-design requests

Remotion is useful design/engineering reference for frame-based timing, text measurement and
composable animation; it is not an installed backend here. If a user needs animated captions,
J/L cuts, custom layouts or motion graphics, specify the desired visible behavior and identify the
missing CLI contract. Do not silently create a React project, download packages, or bypass QC.
For an explicitly authorized engine implementation, verify current official APIs before coding.

This is an original project-specific review Skill, not a copy of Remotion's Skill package.
Research pointers: [official skill repository](https://github.com/remotion-dev/skills),
[Remotion documentation](https://www.remotion.dev/docs), and
[X demonstration discussion](https://x.com/wcandillon/status/2015345960491069718).
The official Skill repository had no declared repository license in the inspected snapshot;
no source text or code from it is redistributed here.


For supported SDR color work, use `review color` for original/after samples and `cutlist color` for
source-specific revisions. Confirm the proposed/configured label and inspect the scene rather than
judging by mean brightness alone. Neutral/low-variation graphics need no automatic brightening.
Same-take reference cameras use existing sync evidence. Grading applies before text overlays;
verify readability, highlights and scene consistency in the resulting preview. Known HDR and native
Jianying color mapping are explicit gaps; do not silently drop a correction during handoff.


For short callouts, lower-thirds and chapter cards, use the CLI's `motion build` → `motion edit`
→ `cutlist motion` workflow. It retains editable source parameters and creates immutable transparent
movies. Review entrance/hold/exit, longest text, main-audio continuity and subtitle collision in a
preview with QC. It does not add animated subtitles, J/L cuts or native editable motion layers.
Jianying export rejects motion overlays explicitly until that mapping is implemented and verified.
