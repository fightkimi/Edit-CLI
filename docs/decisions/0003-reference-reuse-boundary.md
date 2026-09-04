# ADR 0003: Reference repository reuse boundary

- Status: accepted
- Date: 2026-09-03

## Context

`guang-tech/interview-edit-pipeline` was inspected at commit `95c0a93dbf3c9823317b459ad06b86bcf3a0e029`. It contains valuable production methods for cut-list assembly, audio correlation, evidence-driven QC, source-use ledgers, loudness normalization, and immutable versions. It is also a project template with hard-coded paths, media mappings, Windows executables, NVIDIA encoders, mutable module globals, and direct process exits. The repository contains no `LICENSE` or `COPYING` file at that commit.

The user has authorized using the repository as a development base, but a public redistribution license for copied source has not been established.

## Decision

- Reuse documented methods, domain lessons, test cases, and observable behavior.
- Reimplement M1 and later capabilities behind the new package interfaces and tests.
- Do not copy source text into the new repository until ownership and the intended public license are recorded.
- Do not carry over project-specific paths, people, content, camera mappings, correction dictionaries, codecs, frame rates, or hardware assumptions.
- Keep the reference checkout outside the new repository and treat it as read-only evidence.

## Consequences

- M1 has no source-level dependency on the reference repository.
- Later algorithm ports require a focused provenance review and tests against synthetic media.
- The new repository remains without an open-source license until the owner chooses one; absence of a license is not treated as permission to redistribute.
