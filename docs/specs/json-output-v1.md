# JSON output protocol v1

Every machine-readable command emits exactly one JSON document to stdout.

```json
{
  "schemaVersion": "1",
  "ok": true,
  "command": "status",
  "runId": null,
  "data": {},
  "warnings": [],
  "artifacts": [],
  "next": []
}
```

## Fields

- `schemaVersion`: protocol version, currently the string `"1"`.
- `ok`: whether the requested command completed without a blocking error.
- `command`: stable command identifier such as `init`, `doctor`, or `status`.
- `runId`: long-running run identifier; `null` for M1 commands.
- `data`: command-specific structured result.
- `warnings`: non-blocking objects with `code` and `message`.
- `artifacts`: objects with `kind` and normalized absolute `path`.
- `next`: executable command strings suggested as safe next actions.
- `error`: present only when `ok` is false, with stable `code`, human `message`, and optional `details`.

Field additions are backward compatible. Renaming, removing, or changing field meaning requires a new `schemaVersion`.

Usage errors detected inside a command use the same envelope and exit code 2. Errors raised by the command-line parser before a command can be selected may use Typer's stderr format and exit code 2.

Long analysis can preserve useful artifacts while still returning a blocking result. In particular,
low-confidence `sync` emits one envelope with `ok: false`, error code
`sync_confidence_insufficient`, exit 3, and the written report/evidence in `data` and `artifacts`.
Consumers must evaluate both the process exit and `ok`; artifact presence alone is not success.
