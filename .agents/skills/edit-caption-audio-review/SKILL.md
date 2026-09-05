---
name: edit-caption-audio-review
description: Improve caption readability and dialogue presentation in interview-edit previews. Use for crowded or mistimed Chinese subtitles, inconsistent speech levels, clicks at cuts, or caption and overlay collisions.
---

# Caption and audio review

Use [interview-edit](../interview-edit/SKILL.md) for privacy, status, validation, render and approvals.
Inspect only permitted transcript spans and selected preview/QC evidence. Keep generated files
under the configured artifact root and keep source media read-only.

## Captions follow the final edit

First settle dialogue ranges, then recompute each subtitle relative to its item's start. Split
Chinese captions by phrase and meaning; preserve names, numbers, units, negation and qualifiers.
Prefer short readable chunks over one-word flashing. Do not paraphrase claims for visual punch.
Choose duration from speech timing and actual reading effort; no universal character-rate target
can replace viewing at the delivery size. Leave demonstration labels and faces visible.

Verify the declared local font contains the Chinese glyphs. Inspect the longest caption and each
title/overlay collision at the intended aspect ratio, including the first and last caption frames.
Test readability on the actual preview size, not only a large desktop image. If text is crowded,
split it at an appropriate spoken boundary or shorten nonessential title text before asking for
unsupported styling. Captions must fit within the item and the configured safe area.

The current contract supports subtitle text, timing and local font paths, plus safe-area policy.
It does not expose karaoke highlighting, arbitrary positions, caption background styles or animation.
Do not invent `style`, `position` or `font_size` fields or run imported caption scripts behind the CLI.

## Dialogue is the anchor

Keep the configured primary audio across camera and B-roll changes. At normal playback check
clipped starts, breaths, clicks, unexpected silence and level jumps; when listening is unavailable,
mark these as unverified and provide exact review times. Do not infer audio quality from screenshots.

Read the project's actual audio targets and run-bound QC, rather than copying a web preset.
Preview is not a loudness-normalized master. The existing master path uses measured two-pass
normalization; request master only with the required approval. Do not normalize individual phrases
through a second renderer or lower QC thresholds. Music ducking, restoration and automatic gain
riding require a separately implemented CLI capability when absent.

Deliver a compact issue table: item and local time, observed symptom, supported correction, and
whether it was visually checked, heard, measured or still unverified. After a correction validate,
render preview and run preview QC. Keep technical findings separate from taste judgments.

## Source and adaptation

Adapted from 6missedcalls/video-editing-skill (MIT): operation order and caption-style choice.
Its shell scripts and Whisper auto-transcription are not installed. This version uses the local
CLI and Chinese readability review; dynamic caption styles are explicitly capability gaps.
See [source record](SOURCE.json) and [upstream license](LICENSE.upstream).
