# CLI reference

Global options precede the command. M1 commands also accept `--project` and `--json` after the command.

```text
interview-edit [GLOBAL OPTIONS] init
interview-edit [GLOBAL OPTIONS] doctor
interview-edit [GLOBAL OPTIONS] status

interview-edit [GLOBAL OPTIONS] ingest
interview-edit [GLOBAL OPTIONS] proxy build
interview-edit [GLOBAL OPTIONS] transcribe
interview-edit [GLOBAL OPTIONS] sync
interview-edit [GLOBAL OPTIONS] cutlist scaffold|inspect|validate|set-range|captions|speech-check
interview-edit [GLOBAL OPTIONS] render
interview-edit [GLOBAL OPTIONS] qc
interview-edit [GLOBAL OPTIONS] version freeze|list|show|verify
```

Global options:

```text
--project PATH  --json  --quiet|-q  --dry-run|-n
--force|-f  --no-color  --version
```

Use `--json` for machine-readable calls. Parse the single JSON envelope from stdout; treat stderr as diagnostics. Respect nonzero exits:

- 2: arguments, configuration, or schema error
- 3: preflight, validation, or QC failure
- 4: dependency missing
- 5: permission or path boundary error
- 130: interrupted

Treat the installed `interview-edit --help` and relevant subcommand help as authoritative. Do not
call commands that do not appear there. Version 0.6.0 exposes every command listed above.

Current safe flow:

```text
interview-edit status --project PATH --json
interview-edit doctor --project PATH --json
interview-edit ingest --project PATH [--camera-map FILE] [--full-hash] --json
interview-edit proxy build --project PATH --resume --json
interview-edit transcribe --project PATH [--asset ID ...|--take ID] --resume --json
interview-edit sync --project PATH --take ID --reference-camera ID \
  [--window-count N] [--visual-check] [--manual-offset CAMERA=VALUE ...] --json
interview-edit cutlist scaffold --project PATH [--asset ID] [--output PATH] --json
interview-edit cutlist inspect --project PATH --cutlist PATH [--act ID] [--item ID] --json
interview-edit cutlist validate --project PATH --cutlist PATH \
  [--profile preview|master] --json
interview-edit render --project PATH --cutlist PATH [--act ID] [--item ID] \
  [--context-items 0|1|2] [--profile preview|master] [--output PATH] [--resume] --json
interview-edit qc --project PATH [--run RUN_ID] [--policy preview|release] --json
interview-edit version freeze --project PATH --run RUN_ID --approve [--note TEXT] --json
interview-edit version list --project PATH --json
interview-edit version show --project PATH VERSION_ID --json
interview-edit version verify --project PATH VERSION_ID --json
interview-edit status --project PATH --json
```

Use `--build-proxies` on `ingest` only when the user requested both stages. Use `--full-hash` when cryptographic source proof is needed; the default fast fingerprint is intended for routine change detection. Do not read contact sheets under `strict` privacy mode.

Before transcription, confirm that the selected backend and model are already local. A model name is
not download authorization. When `sync` exits 3 with `sync_confidence_insufficient`, keep the report,
review its windows and (when privacy allows) visual evidence, then ask before applying a manual
offset. The stored offset convention is `camera_time = reference_time + offset`.

`cutlist scaffold` with no `--asset` writes a blank deterministic document. With `--asset`, it
requires that asset's current checksum-valid corrected transcript and creates chronological item
and subtitle placeholders; it does not make narrative selections. `cutlist inspect` intentionally
omits transcript, note, act-title, title-card, and subtitle text.

Always validate the complete document immediately before rendering. Invalid cut-lists exit 3 before
FFmpeg starts. Preview requires existing valid M2 proxies and should be the default. Run `master`
only after explicit user approval. An explicit output must remain inside the configured artifact
root; `--force` is required to replace different existing content. `--resume` reuses only
checksum-valid item caches.

`qc` defaults to the latest successful run and preview policy. Read the report rather than raw
detector logs; it omits content text and preserves evidence hashes. Release QC is valid only for a
master and only when `state` is `passed`. Do not issue `version freeze` until the user separately
approves that exact master run. `--approve` records that approval but never bypasses release QC.
Immediately run `version verify` after freezing and report the resulting version ID.

## Output-quality revisions

Check subcommand help before using the quality commands:

```text
interview-edit cutlist speech-check --project PATH --cutlist PATH [--item ID] --json
interview-edit cutlist captions --project PATH --cutlist PATH [--item ID] \
  [--max-chars N] [--style standard|minimal] [--output NAME] --json
interview-edit cutlist set-range --project PATH --cutlist PATH --item ID \
  --in-us INTEGER --out-us INTEGER [--output NAME] --json
```

Revision commands write new YAML under artifact_root/cutlists/revisions; relative outputs are names
within that directory. Global --dry-run writes nothing. Existing revisions cannot be overwritten.
set-range moves item-relative components with the source range, clips B-roll source ranges, and
rejects partial subtitle trimming or known word-internal cuts. Split/revise the affected cue first.
captions preserves text; mismatched/missing word timing is explicitly estimated. A style change is
global and cannot be combined with --item. speech-check is read-only and does not establish natural
listening quality, audio-safe phonemes, or separate-audio alignment. Report unverified items.

After validation, use render --item ID --context-items 1 --profile preview to include neighboring
items when reviewing a join. Run preview QC and inspect the result. Master/freeze gates still apply.

## Editable Jianying handoff

```text
interview-edit export jianying --project PATH --cutlist PATH --name NAME \
  [--platform macos|windows|both] [--bundle-media|--reference-media] --json
interview-edit jianying doctor --json
interview-edit jianying install --draft PACKAGE [--draft-root EXISTING_DIRECTORY] \
  [--platform macos|windows] --json
```

Use this route when the user needs a native editable timeline. Default export bundles original media
and fonts and writes both platform entry files; show the --dry-run size for large source sets.
Follow jianying-handoff.md. Neither file creation nor installation proves the client accepted it.
