---
name: interview-edit
description: Orchestrate the repository's local interview-edit CLI for substantive speech-led creator-video work. Use when a user asks to set up or inspect an editing project, index footage, build proxies, transcribe, synchronize cameras, plan or revise a cut-list, render or review a preview, diagnose QC, export an editable Jianying draft, create an approved master, or freeze and verify a release for interviews, talking-head videos, tutorials, reviews, or vlogs. Do not use for generic playback, online-video downloads, image generation, standalone FFmpeg questions, publishing, or arbitrary film/television post-production.
metadata:
  version: "0.6.0"
---

# Interview Edit

Coordinate editorial judgment around the repository CLI. The CLI is the only media-processing
engine and operational source of truth; the Skill turns user intent and current evidence into safe,
reviewable command sequences and versioned cut-list changes.

Requires this repository's `interview-edit` CLI, Python 3.11+, and local FFmpeg/FFprobe. Normal
operation is local-first and does not require network access.

## Resolve the route from fresh evidence

1. Locate the project or configuration. Never infer that the current directory is the media project.
2. Read `interview-edit.yaml`, then apply [privacy.md](references/privacy.md) before opening any
   transcript or image.
3. Run `interview-edit status --project PATH --json` and route from stage `validity` and
   `reasonCodes`, never the presence-only `state`. Run `doctor` when the environment is new,
   changed, or implicated by a failure.
4. Before asserting a command or option, check the installed `interview-edit --help` and relevant
   subcommand help. Use [cli-reference.md](references/cli-reference.md) as orientation, not as a
   substitute for the installed CLI.
5. Read [workflow-router.md](references/workflow-router.md) and choose the shortest route that starts
   from the observed project state. Do not rerun completed valid stages without a reason.

Load only the references needed for the selected route:

| Request | Read |
|---|---|
| improve script, pacing, captions, audio or visual quality | [quality-skills.md](references/quality-skills.md) |
| create/revise narrative or adapt creator format | [editorial-guidance.md](references/editorial-guidance.md), [cutlist-schema.md](references/cutlist-schema.md) |
| inspect transcript, thumbnail, contact sheet, or QC frame | [privacy.md](references/privacy.md) |
| create/revise a short callout, lower-third or chapter motion graphic | [cli-reference.md](references/cli-reference.md), [cutlist-schema.md](references/cutlist-schema.md) |
| keep editing in Jianying on Mac/Windows | [jianying-handoff.md](references/jianying-handoff.md) |
| render, review, approve, recover, or resume | [review-and-recovery.md](references/review-and-recovery.md) |
| release QC or freeze | [qc-policy.md](references/qc-policy.md), [review-and-recovery.md](references/review-and-recovery.md) |

## Editorial contract

- Establish the smallest useful brief: format, audience or viewing context, target length, must-keep
  ideas, and protected ranges. Ask only for a missing choice that would materially change the edit.
- Separate evidence from judgment. Transcript words, source ranges, sync reports, and QC findings are
  evidence; hook strength, pacing, clarity, and emphasis are proposed editorial choices.
- In `strict` privacy mode, work from user-provided ranges or an existing cut-list. In `assisted`
  mode, inspect only the transcript spans and selected visual evidence needed for the current choice.
- Write every narrative change to a new or explicitly selected cut-list revision. Never hand-edit
  generated indexes, transcripts, render manifests, QC reports, or frozen versions.
- Validate the complete cut-list after every change. A nonzero validation result blocks rendering.
- Render preview first and run preview QC. Summarize the changed ranges, output path, QC evidence,
  warnings, and unresolved editorial choices before asking for master approval.

## Non-bypassable gates

- Never modify, move, rename, or delete source media.
- Do not upload media or transcripts, publish content, or download models/dependencies without
  separate explicit authorization.
- A preview approval authorizes neither a master nor a freeze. Master approval binds to a cut-list;
  freeze approval binds to the exact successful master run after passing release QC.
- Never lower thresholds, relabel findings, use `--force`, or delete evidence merely to pass a gate.
- If a capability is absent from current CLI help, report the product gap. Do not improvise an
  untracked FFmpeg/Python replacement.
- Preserve the last successful artifact after failure or interruption and follow the bounded
  recovery rules rather than starting over blindly.

## Return a decision-ready result

Lead with what changed or why work stopped. Include the relevant run/report/version IDs, artifact
paths, validation or QC state, content-safe warning summary, source-integrity result when checked,
and the one next decision or command. Never describe an unrun command as successful.
