# ADR 0010 Editable Jianying handoff

- Date: 2026-09-08
- Status: user-authorized direction; native client compatibility pending verification

The user needs to continue editing after the automatic cut and explicitly requests Jianying on
Mac and Windows. This extends the earlier V1 exclusion of NLE project export for this named target.
It does not turn the product into a general editor or authorize cloud services.

The cut-list remains the input to the CLI. Add native multi-track draft output alongside FFmpeg
preview, preserving editable captions/titles and independent source clips/audio. Export packages
stay under the configured artifact root. A separate explicit installation command may copy a
verified package to the user's local Jianying draft library; this is the authorized handoff boundary.
It must create a new directory and leave existing projects and the global registry untouched.

After native editing, Jianying owns those changes and renders. Do not regenerate over that edited
project or treat existing CLI QC/freeze records as covering its output. Native rendering automation
requires later validation of the installed app and cannot be claimed from draft-file generation.

Draft support is version-sensitive and based on public protocol templates rather than an official
stable API. Do not decrypt existing drafts, collect machine fingerprints, downgrade the user's app,
or silently flatten unsupported effects. A missing client is a reported prerequisite, not a success.
