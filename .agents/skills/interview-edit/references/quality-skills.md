# Focused output-quality Skills

These project-local Skills supplement the main workflow. Load only the relevant pass; run them
in the order below when the user requests a complete edit-quality revision. They share the main
Skill's privacy, artifact, validation, preview, QC and approval boundaries. Their guidance changes
editorial decisions; it does not add CLI flags or a second media engine.

| Problem | Skill |
|---|---|
| Weak script, repeated ideas, incoherent opening/ending | [edit-story-structure](../../edit-story-structure/SKILL.md) |
| Clipped speech, too many jump cuts, unnatural pauses | [edit-speech-pacing](../../edit-speech-pacing/SKILL.md) |
| Dense Chinese captions, collisions, dialogue inconsistency | [edit-caption-audio-review](../../edit-caption-audio-review/SKILL.md) |
| Soft picture, awkward framing, B-roll or transition problems | [edit-render-review](../../edit-render-review/SKILL.md) |

Start from the user's concrete criticism and existing preview. Preserve the previous revision as
a comparison. Report the observed defect, revised ranges, rendered run and QC, and any playback or
visual review still required. Do not claim output improved from installing Skills or passing static
checks. An absent animation, reframing or audio feature must be identified as an engine gap.

The CLI now provides cutlist speech-check, cutlist set-range, cutlist captions, and optional
render --item ID --context-items 1 for join review. See cli-reference.md for current semantics.
Load the relevant focused Skill, then execute these operations through the CLI. An estimated subtitle
time or unknown speech boundary must remain visible in the review summary.


For cross-take selection, build `review transcript` and inspect only the permitted phrase spans.
Keep the final narrative decisions in a new cut-list revision. For a suspect join, run `review timeline` at its output time and, when useful, the mapped source time. It combines actual frames,
absolute audio waveform and word boundaries; clipped words are flagged. Missing audio and decode
failure are distinct. Listen to the WAV through the user's permitted review flow; do not call a
waveform a listening test.

When smoothing is within the requested edit, propose the starting `cutlist audio --edge-fade-us
5000` revision, then preview/QC. Adjust for the material; continuous audio is not faded merely for
a visual camera switch. Use optional caption pause/minimum display/read-speed constraints, and
report any timing that could not fit. Limit a review/fix cycle to three passes, retain each revision
and its evidence, and report unresolved issues instead of weakening QC or claiming taste from metrics.
