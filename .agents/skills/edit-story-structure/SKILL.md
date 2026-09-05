---
name: edit-story-structure
description: Improve the editorial script and narrative structure of this interview-edit project. Use for weak openings, repetitive explanations, unclear story progression, or selecting a coherent short from speech footage.
---

# Story structure

Use this as an editorial pass inside [interview-edit](../interview-edit/SKILL.md).
Read its privacy and editorial references, inspect current status, and reuse the existing brief.
In strict mode use user-provided ranges; do not open transcripts or visual evidence.

## Produce a paper edit before changing the timeline

Identify the viewer's question and the answer actually supported by the recording. Build a small
beat table: purpose, source ID, source in/out in integer microseconds, keep/tighten/reorder reason,
and context that must survive. Store project-specific notes under the configured artifact root,
outside media roots. Do not place private transcripts in this code repository.

For a short, choose one self-contained idea: opening promise, necessary context, evidence, payoff,
and a deliberate last sentence. For a tutorial preserve prerequisites and verification; for a
review preserve counter-evidence and conditions; for an interview preserve the question's meaning.
Do not impose a viral hook, fixed three-second opener, or target length that cuts off the answer.

Compare repeated takes as whole claims. Keep the cleanest complete delivery only when qualifiers,
numbers, uncertainty and meaning agree. Keep an emotional pause or a useful failed demonstration
when it explains the story. Do not turn an original statement into a new quote by stitching words.

Write chosen ranges into a new cut-list revision using existing acts and typed items. Use `notes`
for short edit reasons and `content_role` for beat labels; neither changes rendering. A paper edit
is planning evidence, while the validated cut-list remains the executable edit contract.

Hand off chosen boundaries to [speech pacing](../edit-speech-pacing/SKILL.md). Validate the whole
cut-list, render a preview through the CLI and run preview QC before presenting a revised edit.
Return what the opening promises, what the ending delivers, changed ranges, and unresolved choices.
Technical QC does not establish that the story is engaging. Keep master/freeze approvals separate.

## Source and adaptation

Adapted from ECC's `video-editing` (MIT). Retains structure-before-polish and explicit edit intent;
replaces its FFmpeg/Remotion/cloud/NLE pipeline with this repository's CLI and cut-list.
See [source record](SOURCE.json) and [upstream license](LICENSE.upstream).
