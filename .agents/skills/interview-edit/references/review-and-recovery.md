# Review, approval, and recovery

Use this reference for preview/master decisions, long-running commands, failed or interrupted work,
and cross-session handoff.

## Approval ledger

| Decision | Required evidence | What approval authorizes | What it does not authorize |
|---|---|---|---|
| preview render | valid cut-list; current proxies | one preview of the stated scope | master, freeze, publish, upload |
| master render | reviewed preview/QC and exact cut-list revision | one master render for that revision | freeze or publish |
| version freeze | exact successful master run and passing release QC | `version freeze --approve` for that run | another run, overwrite, publish |
| download/upload/network/paid action | provider, data, cost and destination scope | only the described external action | later external actions |

When requesting approval, name the object and consequence in plain language. Do not rely on a generic
earlier "continue" after the object has changed or before the exact master run exists.

## Preview review packet

Return a compact, decision-ready packet:

- cut-list revision and rendered scope;
- output path, duration, and run ID;
- changes grouped as keep/remove/reorder/visual treatment without dumping transcript text;
- preview QC state, warnings, item IDs/timeline times, and selected evidence paths;
- deviations from the brief and unresolved choices;
- the exact next approval requested, if any.

Under `strict` privacy, do not open evidence images or quote transcript content. Under `assisted`,
announce before loading the minimum relevant content into the session.

## Release packet

After a master, report the master run ID and path, release QC report ID/state, hashes or verification
state, warnings that remain non-blocking, and whether source integrity was checked. Ask separately
before freeze. After freeze, immediately verify and report the version ID plus verification result.

## Failure classification

| Exit | Class | Recovery |
|---:|---|---|
| 2 | usage/config/schema | correct the explicit input; do not retry unchanged |
| 3 | validation/preflight/QC | inspect structured issues, correct true inputs, produce new evidence |
| 4 | dependency | run `doctor`; request approval before installing/downloading anything |
| 5 | path/permission | stop; resolve ownership/boundary rather than broadening access |
| 130 | interruption | preserve terminal manifest; resume only where the CLI supports verified reuse |
| 1 | runtime | inspect diagnostics and terminal artifact; retry once only with a supported, evidence-based change |

Do not repeat the same failed long-running command more than twice. After two equivalent failures,
stop and present the evidence, likely cause, and materially different options. Never delete valid
caches, previous outputs, reports, or versions merely to make a retry look clean.

## Cross-session handoff

Persist detailed truth in project artifacts, cut-lists, and run/QC/version manifests. A handoff
summary should contain only:

```text
Project/config path:
Privacy mode:
Last successful stage and IDs:
Current cut-list revision:
Observed blocker or pending decision:
Evidence paths safe to inspect:
Exact next command (not yet claimed as run):
Approvals still required:
```

Re-run `status` in a new session before continuing; the handoff is an index, not current truth.
