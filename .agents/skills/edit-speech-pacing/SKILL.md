---
name: edit-speech-pacing
description: Refine speech cut boundaries, repeated takes, pauses and continuity in interview-edit cut-lists. Use when cuts sound clipped, jump cuts feel rushed, or a transcript-based rough cut lacks natural pacing.
---

# Speech pacing

Operate within [interview-edit](../interview-edit/SKILL.md), its privacy mode, current status and
cut-list contract. The source recording is read-only; write revisions under the artifact root.
This adaptation does not install or invoke `vtc`, write foreign EDLs, or export FCPXML.

## Review boundaries in context

Use corrected words and neighboring sentences, not only transcript segment edges. Preserve a
complete claim and its audible start/end. Recognition timestamps are estimates, not phoneme truth.
When the permitted evidence cannot establish a clean boundary, retain more context and mark the
boundary for listening review. Do not assert that you listened when only text/images were available.

For every changed join record source ID, old/new in/out in integer microseconds, neighboring words
or content-safe labels, reason, and remaining uncertainty. Inspect the start, join, and end of a
preview at normal speed when playback evidence is available; otherwise give the user exact join
times for review. A selected QC frame cannot prove the absence of an audio click.

Use silence only to find candidates. Remove a pause when it adds no thinking, emotion, demonstration
or comprehension time. For repetitive takes choose the cleanest complete version, preserving any
qualifier that changes the claim. Avoid isolated filler fragments and cadence made uniformly fast.
Any boundary padding must fit the indexed source, preserve adjacent words, and be checked by ear;
do not apply a fixed millisecond allowance or an automatic silence threshold to every speaker.

After moving item boundaries update `timeline_duration_us`, item-relative subtitles, overlays and
camera cuts to match the new span. Do not slide the source while leaving its captions at old times.
At 1x speed the source span equals item duration. Do not add unsupported speed/retiming fields.

Prefer a motivated camera change or indexed B-roll overlay to conceal a necessary visual jump,
with the primary audio preserved. Do not add a fade to every speech join: current fades also fade
audio and can create a dip. Missing audio-only crossfades or J/L cuts are engine gaps, not flags.

Validate the full revision, render the smallest useful preview through the CLI, run preview QC,
then check joins in the full narrative context. Stop after two equivalent failures using the main
Skill's recovery rules. Report unresolved phoneme/continuity risks separately from technical QC.

## Source and adaptation

Adapted from Video Timeline Copilot (MIT): whole-word/phrase cuts, complete takes, deliberate endings
and visual/text continuity. Its helper commands, floating-second EDL, source-folder writes and
Resolve workflow are replaced by the local CLI, integer-microsecond cut-list and preview gates.
See [source record](SOURCE.json) and [upstream license](LICENSE.upstream).
