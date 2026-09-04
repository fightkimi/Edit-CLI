# QC and approval policy

Preview QC may complete with warnings. Report warnings with affected item IDs, timeline positions, and evidence paths when available.

Release QC requires zero `blocking` and zero `error` findings. At minimum it must cover black frames, silence, loudness and true peak, stream parameters, A/V duration, cut-list/output duration, source bounds, duplicate source use, cut-point evidence, subtitle safety/missing glyphs, and freeze inputs.

Use `interview-edit qc --project PATH --run RUN_ID --policy preview --json` after a preview. For a
master approved by the user, run the same command with `--policy release`. The report and its
detached checksum live under `artifacts/qc/<report-id>/`; do not edit either.

Preview may pass with warnings. Release additionally requires a master run; unexplained sustained
black/silent intervals, loudness or true-peak violations, unsafe text, and missing glyphs are errors.
Black/silent spans wholly contained in explicitly silent/title items are informational rather than
silently discarded.

Non-bypassable rules:

- A failed cut-list validation blocks every render.
- A failed or incomplete render cannot enter release QC.
- Missing or corrupt media and missing final outputs cannot be overridden.
- `--force` may override only a documented non-quality restriction and must record the reason.
- A version can freeze only after a successful master run and passing release QC.
- Master render and freeze require user approval; one approval does not imply the other.
- Freeze only through `version freeze --run RUN_ID --approve`, then immediately run
  `version verify VERSION_ID`. Never infer `--approve` from an earlier master-render request.

Never lower thresholds, reclassify findings, delete evidence, or edit generated reports merely to obtain a passing result.
