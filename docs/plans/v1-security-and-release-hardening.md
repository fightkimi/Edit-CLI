# V1 security and release hardening plan

- Status: complete; local and remote verification passed
- Date: 2026-09-04

## Goal

Close the evidence-backed safety and release-boundary gaps found after the first complete V1 audit.
The private repository remains a Beta engineering baseline until this plan is verified and the
separate real-media, license, versioning, and distribution decisions are complete.

## Confirmed scope

1. Remove the test-only mock transcriber from production configuration and factory paths.
2. Reject path-bearing camera/take identifiers and project or cut-list writes into media roots.
3. Prevent artifact writes through symlinked paths that escape the configured artifact root.
4. Revalidate optional full source hashes at master validation/render boundaries.
5. Reject stale synchronization evidence after source, proxy, membership, or analysis changes.
   Protect sync results themselves with a detached checksum.
6. Include every local model file's content identity in transcription cache invalidation.
7. Make CI fail, rather than skip, when required media/font test dependencies regress.
8. Build, install-smoke, and retain packages from the exact final commit.

## Public-contract impact

- `transcription.backend` accepts only `auto`, `mlx-whisper`, and `faster-whisper`. The mock remains
  a test fixture injected through the service boundary and cannot be selected by an installed CLI.
- Camera and take IDs become path-safe identifiers. Existing values composed of letters, digits,
  underscores, and hyphens remain valid.
- Unsafe project, cut-list, sync, or generated-artifact paths fail with exit code 5.
- A full-hash mismatch, stale synchronization report, or changed local model invalidates the
  dependent operation instead of reusing old evidence.

## Ordered implementation and tests

1. Add failing regression tests for each confirmed issue before its production fix.
2. Harden identifier and write-path validation in shared project/media boundaries.
3. Add current-sync identity validation and reuse it from cut-list validation and rendering.
4. Reuse full source-revision validation in cut-list and master rendering, including a pre-publish
   recheck for long-running source changes.
5. Replace the partial local-model revision with a deterministic recursive content manifest.
6. Strengthen CI dependency gates and final-wheel smoke, then update stable specifications and the
   release-readiness record.
7. Run Ruff, Mypy, the full Python 3.11/3.12 tests, package build, isolated-wheel smoke, remote CI,
   and final staged/unstaged scope review.

## Stop conditions

- Do not weaken validation, convert a failure to a warning, or retain a production mock route to
  preserve an old acceptance claim.
- Do not write, move, or mutate source media while testing safety boundaries.
- Do not tag, publish, upload packages to a registry, download transcription models, or select an
  open-source license without separate explicit authorization.
- Stop and request a product decision if a fix requires changing legitimate user identifiers or a
  frozen protocol beyond backward-compatible field additions.
