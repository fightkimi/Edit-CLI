# ADR 0009: Artifact boundaries and evidence freshness

- Status: accepted
- Date: 2026-09-04

## Context

V1 writes many derived files beneath one configured artifact root and then reuses their manifests
as evidence. Root-level media/artifact separation is insufficient when an artifact child is replaced
by a symbolic link. Likewise, a structurally valid sync report or media index is not current merely
because its identifiers still match. Optional source hashes and local model content must affect the
operations that claim to rely on them.

## Decision

- Validate every generated artifact path lexically and canonically against the artifact root, and
  reject every existing symbolic-link component before reading or writing operational artifacts.
- Restrict camera and take identifiers to letters, digits, underscores, and hyphens, beginning with
  an alphanumeric character, with a maximum length of 120 characters.
- Reject project metadata and explicit cut-list outputs inside any configured media root.
- Revalidate indexed size, modification time, fast fingerprint, and optional full SHA-256 before
  cut-list acceptance and source-backed work. Recheck every referenced source immediately before a
  render candidate is published.
- Accept a sync report only when current take membership, source revisions, validated audio-proxy
  hashes, analysis settings, manual overrides, and implementation identity reproduce its cache key.
- Write and verify a detached `sync.sha256` so accidental edits to synchronization results cannot
  retain a valid input cache key.
- Fingerprint every regular file beneath a resolved local transcription model directory by relative
  path, size, and SHA-256. Compute that model revision once per transcription invocation.
- Keep deterministic fake transcription behind test dependency injection. It is not a valid project
  configuration value and cannot be selected from the installed CLI.

## Consequences

- Existing unsafe identifiers or artifact-child symlinks fail closed and must be renamed or removed.
- Reingest, proxy rebuild, changed sync settings, or local model mutation invalidates dependent cache
  evidence instead of silently reusing it.
- Full source hashing remains opt-in at ingest because of its I/O cost, but when present it is an
  enforced invariant rather than passive metadata.
- Recursive local-model hashing adds startup I/O proportional to model size once per command. This
  is accepted in exchange for content-correct cache reuse.
- The checks reduce accidental and local adversarial path redirection. They do not claim protection
  against an attacker racing filesystem mutations during the same operation.
