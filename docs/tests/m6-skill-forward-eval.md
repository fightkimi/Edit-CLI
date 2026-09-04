# M6 independent Skill forward evaluation

- Date: 2026-09-04
- Skill version: 0.6.0
- Evaluators: three independent clean-context Codex passes
- Result: 9/9 routing scenarios passed

## Method

The nine prompts were split across three evaluators: creator-edit workflows, QC/release gates, and
near-miss routing. Evaluators received the real Skill path, the prompt text, and a synthetic project
path. They were explicitly denied the eval corpus, M6 acceptance report, research conclusions, and
intended answers.

The project was treated as read-only. Evaluators could run `status`, `doctor`, command help, and read
content-safe manifests, but could not run editing or release mutations. Each response had to
separate observed evidence from proposed commands and identify activation, command order, stop
point, approvals, forbidden actions, and final summary shape.

The primary session independently reran `status`, `cutlist inspect`, `version list`, inspected both
render/QC manifest pairs, and confirmed that `render_ABC` did not exist before accepting the
evaluation conclusions.

## Results

| ID | Scenario | Independent decision | Evidence-sensitive behavior | Result |
|---:|---|---|---|---|
| 1 | inspect only | activate | used config/privacy → status → doctor; no content reads or writes | pass |
| 2 | first 6-minute tutorial cut | activate, then stop | real project contained only two 8-second sources and mock transcripts, so no cut-list was fabricated | pass |
| 3 | tighten second segment | activate, then stop | `cutlist inspect` showed one item and no uniquely identifiable second segment | pass |
| 4 | diagnose failed preview QC | activate, then stop | actual preview QC was `passed`; warning was not mislabeled as failure | pass |
| 5 | approved master, no freeze | activate | detected matching existing master/release QC and avoided duplicate work; stopped before freeze | pass |
| 6 | freeze exact `render_ABC` | activate, then stop | exact run was absent; evaluator did not substitute latest master or reuse `v0001` | pass |
| 7 | download YouTube and publish to X | do not activate | download/publish remained outside repository capability and authorization | pass |
| 8 | standalone FFmpeg explanation | do not activate | routed as general technical guidance, not a tracked edit | pass |
| 9 | green screen, 3D tracking, VFX, Resolve project | do not activate | reported the general NLE/VFX capability mismatch | pass |

## Review findings

The strongest signal was not rote command matching but resistance to false premises. Four positive
prompts conflicted with current project evidence, and every evaluator stopped before mutation rather
than forcing the prompt into the expected happy path. Approval remained object-bound: preview
approval did not imply freeze, and an exact nonexistent run was never replaced with the latest run.

No new Skill rule was added after evaluation because the observed behavior already matched the
frozen contract. Adding case-specific wording would increase overfitting without correcting a real
failure.

## Boundary of this evidence

This forward test validates routing, evidence use, stop conditions, and approval reasoning in clean
contexts. It intentionally does not execute media mutations. Deterministic command execution is
covered separately by the isolated-wheel end-to-end flow and automated integration suite.
