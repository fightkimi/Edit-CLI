# V1 release-readiness record

- Date: 2026-09-04
- Package version: 0.6.0
- Previously verified baseline commit: `9ac2994adf1442265fe4945bd660e68f72664856`
- Status: private Beta engineering baseline; security hardening is locally verified and awaiting
  immutable commit/remote CI evidence

This record captures evidence produced after the historical M0-M6 acceptance records. Statements
in those milestone records such as “not committed” or “remote CI not run” describe their original
acceptance checkpoints and are superseded for current release readiness by this document.

## Repository and remote evidence

- The complete V1 baseline and follow-up CI portability fixes are committed on `main` and pushed to
  `guang-tech/edit-CLI`.
- At the verification checkpoint before this evidence-only record was added, local `HEAD`,
  `origin/main`, and `refs/heads/main` resolved to the verified implementation commit above.
- The working tree was clean after the final verification.
- GitHub Actions run
  `https://github.com/guang-tech/edit-CLI/actions/runs/33835807579` completed successfully.

The workflow is pinned to Ubuntu 24.04 and installs FFmpeg, FFprobe, and Noto CJK fonts. This turns
the media and Chinese-text coverage into executed Linux tests instead of environment-based skips.

## Fresh verification

| Environment | Check | Actual result |
|---|---|---|
| local Python 3.11.15 | `ruff check .` | passed |
| local Python 3.11.15 | `mypy src` | passed; 53 source files |
| local Python 3.11.15 | `pytest` | 84 passed |
| GitHub Ubuntu 24.04 / Python 3.11.16 | lint, type check, test | passed; 84 tests |
| GitHub Ubuntu 24.04 / Python 3.12.14 | lint, type check, test, build | passed; 84 tests; sdist and wheel built |
| isolated local Python 3.11.15 | install built wheel | installed `interview-edit==0.6.0` with base dependencies |
| isolated local Python 3.11.15 | `interview-edit --version` | returned `0.6.0` |
| isolated local Python 3.11.15 | `interview-edit --help` | displayed the complete V1 command surface |
| isolated local Python 3.11.15 | base-wheel `doctor --json` | returned the stable JSON envelope and exit 4 because no optional transcription backend was installed |

The base-wheel doctor result is expected: speech recognition remains an explicit optional extra.
Python, Pillow, FFmpeg, FFprobe, portable H.264/AAC encoders, and required filters passed in that
isolated environment.

The post-audit hardening work removes production fake transcription, closes path-redirection and
source/sync/model-freshness gaps, adds strict CI dependency behavior, and adds installed-wheel CI
smoke coverage. Its final commit and GitHub Actions run will be recorded here after both exist.

## Current release blockers and limits

- No production creator footage is present in the repository or workspace, so editorial quality,
  long-media performance, production codecs, and disk-pressure behavior have not been accepted on
  real material.
- The final isolated-wheel smoke did not install MLX Whisper or Faster-Whisper. Earlier M0/M3 host
  evidence covers MLX with a cached local model; Faster-Whisper runtime behavior remains unverified.
- The historical M6 whole-flow fixture injected deterministic fake speech recognition. It validates
  CLI orchestration and media processing, not a real-model end-to-end transcription claim.
- Windows, NVIDIA/CUDA, network shares, removable drives, and permission changes during a long run
  remain unverified.
- The repository intentionally has no open-source license. ADR 0003 forbids copying or publicly
  redistributing reference source until ownership and license terms are explicitly decided.
- No Git tag, GitHub Release, package-registry upload, signing, or public distribution has occurred.

## Promotion gate

Before promoting 0.6.0 beyond the private Beta baseline:

1. Run an approved real-media Beta covering representative interview, talking-head, tutorial,
   review, or vlog material and record source-integrity, preview, QC, and performance evidence.
2. Decide the repository and distribution license.
3. Verify the selected transcription extra on every claimed target platform.
4. Obtain explicit authorization for the exact tag and distribution destination.
