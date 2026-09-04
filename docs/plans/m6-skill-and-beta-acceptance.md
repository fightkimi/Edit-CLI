# M6 Skill and Beta acceptance implementation plan

- Status: complete and locally accepted
- Date: 2026-09-04

## Goal and acceptance

Complete the project Skill as a state-aware editorial orchestrator and prove that the packaged CLI
works outside the source checkout. M6 is accepted when:

- the Skill description routes substantive speech-led creator-video work while excluding generic
  playback, download, image generation, standalone FFmpeg questions, and arbitrary film post;
- `SKILL.md` remains a concise router with focused, discoverable references for commands, workflow
  state, editorial strategy, privacy, review/recovery, and QC approvals;
- the Skill checks current project evidence and actual CLI help instead of relying on remembered
  commands or stale summaries;
- interview, talking-head, tutorial, review, and vlog requests receive distinct editorial guidance
  while preserving a common typed cut-list contract;
- a versioned natural-language eval corpus covers the five PRD-required workflows plus meaningful
  near-miss cases, with expected commands, forbidden actions, approval gates, and evidence summaries;
- static Skill tests validate frontmatter, reference integrity, eval shape, and documented command
  paths without claiming that those checks prove model behavior;
- installation documentation covers development, base-wheel, and local-transcription variants;
- the final wheel is installed into an isolated environment and invoked from outside the checkout;
- the complete synthetic-media evidence matrix covers the PRD's required media conditions using
  current automated tests or a newly executed Beta fixture;
- lint, format, typing, Python 3.11/3.12 tests, Skill validation, package build, cross-directory smoke,
  and source fingerprint checks pass, or any unrun layer is reported explicitly.

## File-level work

| Files | Responsibility | Verification |
|---|---|---|
| `.agents/skills/interview-edit/SKILL.md`, `agents/openai.yaml` | concise routing and discovery | quick validator + metadata tests |
| `references/workflow-router.md` | intent/state command routing | reference and command-path tests |
| `references/editorial-guidance.md` | creator-format editing decisions | eval scenario review |
| `references/review-and-recovery.md` | approvals, evidence, retries, handoff | gate and negative evals |
| `.agents/skills/interview-edit/evals/evals.json` | natural-language behavior contract | eval schema tests |
| `tests/skill/test_interview_edit_skill.py` | deterministic Skill package checks | pytest |
| `README.md` | install and cross-directory usage | isolated wheel smoke |
| `docs/tests/m6-acceptance.md` | complete Beta evidence and limitations | final evidence review |

## Ordered execution

1. Freeze the public benchmark and ADR 0008.
2. Refactor the Skill entrypoint and add focused references.
3. Add natural-language positive and near-miss eval scenarios.
4. Add deterministic Skill package and CLI-reference tests.
5. Complete installation guidance and bump the Beta package to 0.6.0.
6. Run the full synthetic evidence matrix and isolated-wheel cross-directory smoke.
7. Record actual results, remaining gaps, and repository hygiene in the M6 acceptance report.

## Stop conditions

- Stop if the Skill would need to invent an unsupported CLI command, bypass validation/QC, read
  content forbidden by privacy mode, infer master/freeze approval, or modify source media.
- Stop and record a product gap instead of importing publish, remote-generation, downloader, or
  general-NLE behavior from external examples.
- Do not claim independent model-routing acceptance unless an independent execution was actually
  performed; static contract tests and this session's self-evaluation must remain labeled as such.
