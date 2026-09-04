# M5 QC and version-freeze implementation plan

- Status: implemented and locally verified
- Date: 2026-09-04

## Goal and acceptance

Add deterministic media QC and immutable release snapshots without turning the CLI into an
editorial judge. M5 is accepted when:

- `qc` resolves one successful render run, validates all frozen inputs, probes the output, scans
  black and silent intervals, measures loudness/true peak, checks stream and duration contracts,
  reviews duplicate source use and subtitle/font safety, and writes checksum-bearing evidence;
- preview policy permits content warnings while integrity errors still fail; release policy requires
  zero `blocking` and zero `error` findings and additionally requires a master render;
- cut-point evidence is extracted locally into bounded JPEG files with recorded timestamps and
  SHA-256 values;
- QC reports and command evidence are written atomically under the artifact root and never expose
  subtitle or transcript text;
- `version freeze` requires a separately supplied approval flag, a successful master run, and a
  current passing release report for that run;
- a frozen version contains copies of the output, render manifest, release report, detached QC
  checksum, all declared QC evidence, effective project config, and cut-list plus a manifest of
  relative paths, sizes, and SHA-256 values;
- `version list`, `version show`, and `version verify` are privacy-safe, and verification detects
  missing, modified, or unexpected files;
- failed QC cannot freeze, an existing version is never overwritten, and source media remains
  byte-identical;
- lint, formatting, typing, Python 3.11/3.12 tests, build, and isolated-wheel end-to-end acceptance
  pass, or any unrun layer is reported explicitly.

## Public command surface

```text
interview-edit qc --project PATH
  [--run RUN_ID] [--policy preview|release] [--json]

interview-edit version freeze --project PATH --run RUN_ID --approve
  [--note TEXT] [--json]

interview-edit version list --project PATH [--json]
interview-edit version show --project PATH VERSION_ID [--json]
interview-edit version verify --project PATH VERSION_ID [--json]
```

When `--run` is omitted, `qc` selects the latest successful render by completion timestamp. QC
creates a new append-only report on each real run; `--dry-run` returns planned checks without
running FFmpeg or writing artifacts. Freeze automatically chooses the latest current passing
release report for the requested run, removing an error-prone path argument without weakening the
gate.

## Measured technical choices

- The detected FFmpeg 8.1.2 build exposes `blackdetect`, `silencedetect`, `loudnorm`, `select`, and
  the image encoders required for JPEG evidence.
- FFprobe remains the stream/duration authority. Optional color range, space, transfer, primaries,
  and field-order metadata are persisted when available; absent color tags are a warning rather
  than a release blocker because the current valid H.264 output does not always carry them.
- Loudness is measured through `loudnorm=print_format=json`, using its input integrated loudness,
  true peak, and range values as observations rather than applying another transform.
- Default detector thresholds are configurable: 0.5-second black interval, 2.0-second silence,
  -50 dB silence floor, 100 ms A/V and timeline duration tolerance, 1 LU integrated loudness
  tolerance, and 0.1 dB true-peak tolerance.
- Black or silent spans wholly contained in an explicitly silent/title timeline item are recorded
  as informational planned intervals. Other detected spans are warnings in preview and errors in
  release.
- Freeze copies files instead of hard-linking them so later in-place mutation of a render cannot
  change an already frozen payload.

## Durable outputs

- `artifacts/qc/<report-id>/report.json`
- `artifacts/qc/<report-id>/evidence/cut-<n>-before.jpg`
- `artifacts/qc/<report-id>/evidence/cut-<n>-after.jpg`
- `artifacts/versions/vNNNN/version.json`
- `artifacts/versions/vNNNN/output/<render-name>.mp4`
- `artifacts/versions/vNNNN/evidence/render-run.json`
- `artifacts/versions/vNNNN/evidence/release-qc/{report.json,report.sha256,evidence/*.jpg}`
- `artifacts/versions/vNNNN/inputs/{interview-edit.yaml,cutlist.yaml}`

## File-level work

| Files | Responsibility | Verification |
|---|---|---|
| `config/models.py`, project-config spec | typed QC thresholds | config tests |
| `models/qc.py`, QC spec | report, finding, measurement, evidence protocol | model/parser tests |
| `adapters/qc.py`, `qc/service.py` | FFmpeg scans, evidence extraction, policy evaluation | real synthetic media tests |
| `models/version.py`, version spec | frozen manifest and verification protocol | strict-model tests |
| `version/service.py` | gate resolution, atomic copy, list/show/verify | tamper and gate tests |
| `cli/app.py`, status/docs/Skill | thin routing and public workflow | CLI and Skill validation |

## Ordered execution

1. Freeze this plan, ADR 0007, report/version models, and configuration defaults.
2. Add failing parser and policy tests, then implement FFmpeg/FFprobe QC adapters and service.
3. Add real black/silence/stream/loudness/cut-evidence integration tests and expose `qc`.
4. Add failing release-gate, freeze, list/show, and tamper-verification tests.
5. Implement atomic version snapshots and expose the `version` command group.
6. Update status, README, CLI/Skill references, and stable protocol documents.
7. Run full Python 3.11/3.12 and isolated-wheel end-to-end acceptance.

## Acceptance commands

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=interview_edit --cov-report=term-missing
uv build --offline

interview-edit qc --project <synthetic-project> --run <preview-run> --policy preview --json
interview-edit qc --project <synthetic-project> --run <master-run> --policy release --json
interview-edit version freeze --project <synthetic-project> --run <master-run> --approve --json
interview-edit version verify --project <synthetic-project> v0001 --json
```

## Assumptions and stop conditions

- Invoking `version freeze` with `--approve` is the CLI's durable evidence of a separate freeze
  approval. The project Skill must still ask the user before issuing that command.
- `--force` never changes QC severity and never bypasses the master/release gate.
- QC evaluates the selected item IDs stored in the render manifest, so item/act renders compare
  against their actual selected duration rather than the entire cut-list.
- Exact repeated source ranges are reported; repetition is not automatically destructive and stays
  a warning unless a future product rule makes it blocking.
- Stop and realign if implementation would read or copy original media into a version, make release
  pass with an error/blocking finding, freeze stale evidence, overwrite a version, expose content
  text in reports, or require a new unapproved dependency.
