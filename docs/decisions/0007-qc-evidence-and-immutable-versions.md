# ADR 0007: Run-bound QC evidence and gated immutable versions

- Status: accepted
- Date: 2026-09-04

## Context

M5 must distinguish a technically inspectable preview from a release-ready master. A path-only QC
command would lose the render inputs and approval history, while a mutable “latest version” folder
would make later verification ambiguous. The measured FFmpeg build already provides the required
local detection and evidence primitives.

## Decision

- Bind every QC report to one validated `RenderRunManifest`, its output SHA-256, configuration hash,
  cut-list hash, and selected item IDs. A missing, failed, stale, or corrupt run is a blocking
  finding rather than an overrideable condition.
- Keep `preview` and `release` as evaluation policies over the same measurements. Preview content
  risks are warnings; release promotes unexplained black/silent intervals to errors, requires a
  master profile, and passes only with zero blocking/error findings.
- Persist complete detector argument arrays and bounded JPEG cut evidence. Reports contain timing,
  IDs, counts, hashes, and suggested actions but no transcript, subtitle, title, or note text.
- Treat explicitly silent/title items as planned silence/black context. Record those intervals as
  information so deterministic title cards do not make every release fail.
- Require `--approve` on freeze independently of any prior render approval. Resolve a current
  passing release report automatically for the requested master run and recheck all hashes at the
  freeze boundary.
- Assign monotonically increasing `vNNNN` directories and create them through a sibling staging
  directory followed by atomic rename. Never reuse or replace an existing ID.
- Copy the rendered output and evidence inputs into the version. Do not hard-link media, and never
  include original source files. Record every frozen relative path, size, and SHA-256 in
  `version.json`.
- Verify both declared files and unexpected payload files. A frozen version is immutable by CLI
  contract; verification reports any missing, modified, or added file with exit code 3.

## Consequences

- QC can be rerun without mutating render evidence, and older reports remain auditable.
- Release decisions are reproducible from local artifacts and cannot silently follow a changed
  cut-list, config, output, or report.
- Automatic black/silence detection remains conservative: it finds technical intervals and uses
  cut-list structure only to identify explicit planned context, not to infer editorial intent.
- Copying a master costs additional disk space but provides stronger isolation than hard links.
- The CLI provides evidence-backed immutability, not protection from an administrator deliberately
  rewriting both payload and manifest; external signing can be added later if required.
