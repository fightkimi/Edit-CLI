# M6 Skill and Beta local acceptance record

- Date: 2026-09-04
- Package version: 0.6.0
- Result: locally accepted; deterministic Beta flow and independent Skill routing verified

## Skill upgrade

The 70-line `SKILL.md` is now a state-aware router instead of a command handbook. It checks current
configuration, privacy mode, project status, and installed CLI help before choosing a route. Focused
references cover workflow state, creator-format editorial judgment, cut-list rules, privacy,
review/recovery, and QC/release gates.

The natural-language corpus contains six positive workflows and three near-miss exclusions. Every
case defines expected behavior and explicit expectations covering command order, forbidden actions,
approval scope, and the final evidence summary. Static tests validate frontmatter, local reference
integrity, corpus shape, required command coverage, negative cases, and every documented CLI command
path against the real Typer application.

Three independent clean-context Codex evaluations then exercised all nine prompts without access to
the expected answers. The primary session reran the critical read-only project checks before
accepting their conclusions. All nine correctly selected activation, evidence order, stop point,
approval scope, and forbidden actions.

The installed Codex Skill Creator validator returned `Skill is valid!`. Its current frontmatter
allow-list rejects the public specification's optional `compatibility` field, so the runtime
requirement is recorded in the body and ADR 0008.

## Automated verification

| Check | Actual result |
|---|---|
| Skill Creator `quick_validate.py` | passed: `Skill is valid!` |
| `pytest tests/skill/test_interview_edit_skill.py -q` | 5 passed |
| Ruff format check on Python 3.12.13 | passed; 115 files at the full-test checkpoint; final repository check passed with 116 files |
| Ruff lint on Python 3.12.13 | passed |
| mypy on Python 3.12.13 | passed; 53 source files |
| full pytest on Python 3.12.13 | 84 passed; 85% statement coverage |
| full pytest on Python 3.11.15 | 84 passed |
| `uv build --offline` | built the 0.6.0 sdist and wheel |
| independent Skill forward evaluation | 9/9 scenarios passed across three clean contexts |

Optional transcription modules are imported dynamically so the documented base development install
can be linted and type-checked without installing either ML backend. The behavior and error handling
remain covered by adapter tests.

## Synthetic-media requirements

The committed fixture is a deterministic source generator plus tests, not binary media. Generated
MP4, WAV, JPEG, and acceptance artifacts remain outside Git.

| PRD fixture condition | Fresh evidence |
|---|---|
| three cameras | `test_beta_fixture_has_three_cameras_two_takes_and_mixed_language` ingested `wide`, `close`, and `side` |
| two takes | the same test mapped all three cameras to `take-01` and `take-02` |
| known offset | real FFmpeg integration recovered 250,000 us, within one 25 fps frame |
| simulated drift | synthetic multi-window signal reported about 2,000 ppm and more than 6,000,000 us/hour |
| silence and black | real generated fixture produced preview warnings and release errors |
| A/V parameter mismatch | replaced render was rejected for width, height, and audio-channel mismatches |
| reusable B-roll | real composition rendered B-roll over continuous primary audio; QC unit evidence flagged an exact reused range |
| mixed Chinese/English | Beta transcription fixture persisted `你好 creator` with word timing |
| spaces and Chinese paths | Beta sources and project used both, and the complete CLI flow succeeded |
| source immutability | SHA-256 values were unchanged in tests and the isolated-wheel flow |

## PRD acceptance matrix

| # | Acceptance | Result and evidence |
|---:|---|---|
| 1 | cross-directory `command -v` | passed in `/private/tmp`; resolved to the isolated environment |
| 2 | clear `--help` | passed; all 12 top-level/group commands were shown |
| 3 | doctor detects dependencies and permissions | passed by unit tests; isolated doctor passed core dependencies and reported four non-blocking warnings |
| 4 | repeated ingest is idempotent | passed; two assets became `unchanged`, with no additions |
| 5 | source change invalidates only correct downstream work | passed by proxy integration coverage |
| 6 | interrupted transcription resumes | passed by chunk-checkpoint integration coverage |
| 7 | known sync offset within one frame | passed; 250,000 us recovered at 25 fps |
| 8 | drift detected or marked uncertain | passed by synthetic 2,000 ppm regression |
| 9 | invalid cut-list exits 3 without rendering | passed by integration coverage |
| 10 | one-item edit invalidates one item cache | passed; cache states changed from `built,built` to `cached,built` |
| 11 | interrupted render preserves prior success | passed for an interrupted forced replacement |
| 12 | QC detects black, silence, parameter errors, and reuse | passed across real-media integration and focused duplicate-source policy tests |
| 13 | failed release QC blocks freeze | passed |
| 14 | freeze contains complete evidence | passed; manifest, config, cut-list, QC, checksum, and output were declared |
| 15 | verify detects frozen-file modification | passed |
| 16 | source fingerprints unchanged end to end | passed |
| 17 | JSON is cleanly parseable | passed by command integration tests |
| 18 | Skill selects correct order for test prompts | passed: 9/9 independent clean-context scenarios, with critical evidence rerun by the primary session |
| 19 | no unconfirmed master or freeze | passed by Skill contracts and CLI approval/release gates |
| 20 | deterministic flow works without Codex | passed with the isolated 0.6.0 wheel |

## Independent natural-language forward evaluation

The detailed record is in `docs/tests/m6-skill-forward-eval.md`. The most important observed result
was resistance to false premises:

- a claimed 6-minute tutorial was actually an 8-second mock fixture;
- the requested second segment did not exist;
- the allegedly failed preview QC had passed;
- the exact approved run `render_ABC` did not exist.

Evaluators stopped before mutation in every conflicting case. They did not fabricate a cut, call a
warning a failure, substitute the latest master, transfer approval, or claim an unrun command had
succeeded. All three near-miss requests were correctly excluded.

## Isolated-wheel deterministic flow

The final wheel was installed into a new Python 3.12.13 environment and invoked from
`/private/tmp`, outside the source checkout.

- `command -v interview-edit` resolved inside the isolated environment and `--version` returned
  `0.6.0`.
- `doctor` returned success with degraded status: portable FFmpeg/FFprobe and required filters
  passed; VideoToolbox fell back to libx264; mock transcription, no repository Skill from the
  installed context, and initially missing font were reported as warnings.
- The first subtitle-bearing cut-list validation returned exit 3 for `font_required` and produced no
  render. After configuring the verified local Chinese font, validation passed.
- The actual chain `init → doctor → ingest twice → proxy → transcribe → sync → cutlist scaffold →
  validate preview → render preview → preview QC → validate master → render master → release QC →
  freeze → verify` completed without Codex involvement.
- Sync run reported the expected 250,000 us close-camera offset.
- Preview run `render_20260904T022115Z_94b3f89c20` and master run
  `render_20260904T022143Z_66a636e1ca` succeeded.
- Release report `qc_20260904T022149Z_4d41944618` passed with one non-blocking missing-color-metadata
  warning. Frozen `v0001` verified six payload files with no issues.
- Source hashes remained `dfc17887...eba39` and `328c9975...cbd7` before and after the chain.
- Final wheel SHA-256: `e2a00ad4fa44df11feb1502ec2f9b62bb2f8e3835884158952668d96164b1225`.

## Limits and repository hygiene

- Independent clean-context routing was exercised, but it was a read-only forward test rather than
  destructive execution. The separate isolated-wheel flow covers deterministic command execution.
- The isolated full flow deliberately selected the deterministic mock transcriber. A real local MLX
  transcription was not rerun in M6; M0/M5 retain the earlier host evidence, while the current Codex
  sandbox still cannot provide a usable Metal device to MLX.
- Production media, long-duration performance, disk pressure, Windows/Linux/NVIDIA, network shares,
  and removable-media permission changes remain unverified.
- The isolated doctor warning that it could not find the repository Skill is expected outside the
  checkout; Skill discovery and globally installed CLI use are intentionally separate.
- No generated media, models, logs, or local QC frames are present in the repository. Nothing is
  staged, committed, pushed, published, or uploaded.

## Next milestone

M6 is locally accepted. The next step is release preparation: review the initial commit boundary,
run remote CI after an authorized push, and tag or distribute the Beta only after explicit approval.
