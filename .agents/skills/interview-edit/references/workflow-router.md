# State-aware workflow router

Choose a route from both the user's intent and fresh `status` evidence. A later-stage request does
not imply that its prerequisites exist or remain current.

## Source-of-truth order

1. Current CLI output, files, hashes, and exit codes.
2. Installed `interview-edit --help` and subcommand help.
3. Stable repository specs and this reference.
4. Prior conversation, remembered commands, and assumptions.

If a lower source conflicts with a higher one, follow the higher source and report the drift.

## Intent routes

| User intent | First evidence | Route | Stop point |
|---|---|---|---|
| "看看项目到哪了" / inspect only | config + `status` | report state; `doctor` only if environment matters | no mutation |
| initialize a new local edit | project path, media roots, privacy choice | `init` → `doctor` | missing privacy or unsafe path |
| scan/import footage | valid config and readable media roots | `ingest`; optionally proxy only if requested | index errors or changed-source warning |
| prepare editable media | current index | `proxy build --resume` | missing/stale source evidence |
| transcribe speech | valid audio proxy, local backend/model | `transcribe --resume` | download or remote service required |
| synchronize cameras | same-take assets and transcript/audio evidence | `sync`; review low confidence | manual offset requires reviewed evidence |
| create first edit | brief + current transcript/sync evidence | scaffold/revise cut-list → validate → preview → preview QC | preview review |
| revise one passage | exact revision/range + requested change | copy/new revision → edit → validate → affected preview → QC | preview review |
| explain QC failure | report JSON; selected evidence if privacy permits | classify integrity vs editorial findings; recommend input fix | never mutate report/threshold to pass |
| approved master | approved cut-list revision | validate → master render → release QC | freeze requires separate exact-run approval |
| approved freeze | exact successful master run + passing release QC | `version freeze --approve` → `version verify` | any stale hash or failed gate |

## State rules

- Missing config: only `init` can establish a project; do not create an ad hoc directory layout.
- Missing or stale index: do not infer asset IDs from filenames.
- Missing proxy: master may use source media, but preview-first workflow still requires a valid proxy.
- Missing transcript: a user-provided source range can still support a strict-mode cut-list; do not
  claim semantic editing without transcript evidence.
- Missing/low-confidence sync: keep one verified camera or request review; do not silently align by
  visual guess.
- Invalid cut-list: fix the input revision and validate again before any render.
- Failed/interrupted render: inspect its terminal manifest and preserve prior successful output.
- Failed QC: fix the cut-list, assets, configuration, or environment indicated by evidence; create a
  new render/QC report rather than editing generated evidence.
- Frozen version: read-only. Any requested change starts from a cut-list revision and produces a new
  run and version ID.

## Scope selection

Use full-timeline commands unless the user explicitly requests an act/item check or a small revision
can be validated with an affected-scope preview. Before master, always validate and render the whole
approved timeline; an item preview is not release evidence.

Use `--resume` for proxy, transcription, or render work only when current hashes allow the CLI to
prove cache validity. Use `--force` only for a documented non-quality replacement explicitly
requested by the user; it never overrides validation, QC, approval, or path safety.
