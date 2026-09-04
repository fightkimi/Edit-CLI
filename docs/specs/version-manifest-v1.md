# Frozen version manifest protocol v1

`version freeze` creates a new `artifacts/versions/vNNNN/` directory. IDs increase monotonically and
an existing directory is never reused or replaced. Publication uses a sibling staging directory
followed by atomic rename.

## Release gate

Freeze requires all of the following:

- a separately supplied `--approve` flag;
- a successful, completed master render;
- unchanged effective configuration, cut-list, render manifest, and output;
- the latest passing release QC for the same run;
- a QC report matching its detached checksum with intact evidence;
- zero `error` and zero `blocking` release findings.

`--force` does not bypass any condition.

## Frozen payload

Each version contains:

```text
v0001/
  version.json
  version.sha256
  output/<master-name>.mp4
  evidence/render-run.json
  evidence/release-qc/report.json
  evidence/release-qc/report.sha256
  evidence/release-qc/evidence/<frame>.jpg
  inputs/effective-config.yaml
  inputs/cutlist.yaml
```

The effective merged configuration is serialized, rather than copying only the project-level YAML.
The selected release QC report, its detached checksum, and every evidence file declared by that
report are copied so the version remains self-contained. Original source media, proxies,
transcripts, caches, and unrelated QC reports or evidence are never copied.

`version.json` records the version/project IDs, note, source run/report IDs and hashes, approval
kind, creation time, master output hash, and every frozen payload file:

```json
{
  "role": "output|render_run|release_qc|qc_checksum|qc_evidence|config|cutlist",
  "relative_path": "output/master.mp4",
  "size": 1234,
  "sha256": "..."
}
```

## Verification

`version verify VERSION_ID` checks the detached manifest hash, every declared regular file's path,
size, and SHA-256, and rejects undeclared payload files. Missing, modified, symlinked, duplicated,
escaping, or unexpected files return exit code 3 with stable issue codes.

Immutability is enforced by CLI behavior and checksum evidence. It protects against accidental or
ordinary filesystem changes; external signing would be required to defend against an administrator
deliberately rewriting both a payload and its detached checksum.
