# M2 ingest and proxy implementation plan

- Status: implemented and locally verified; see `docs/tests/m2-acceptance.md`
- Date: 2026-09-03

## Goal and acceptance

Implement source-read-only media discovery and per-asset proxy generation for speech-led creator-video projects. A successful run produces a deterministic media index, low-bitrate video proxies, normalized speech audio, thumbnails, paginated contact sheets, time mappings, and cache manifests.

M2 is accepted when:

- recursive ingest handles Unicode and spaces, excludes project artifacts, and never changes source bytes;
- two unchanged ingest runs retain the same asset IDs without duplicate assets;
- a failed probe preserves the previous valid media index;
- changing one source changes only that asset's fingerprint and proxy cache key;
- proxy outputs are committed atomically per asset and an interrupted/repeated run can reuse completed assets;
- `--json` remains one parseable envelope and expected errors use the documented exit codes;
- lint, typing, unit tests, live FFprobe/FFmpeg integration tests, build, and outside-source CLI smoke tests pass.

## Public command surface

```text
interview-edit ingest --project PATH
  [--media-root PATH ...]
  [--camera-map FILE]
  [--extensions EXT[,EXT...] ...]
  [--full-hash]
  [--build-proxies]
  [--resume]
  [--force]
  [--json]

interview-edit proxy build --project PATH
  [--asset ID ...]
  [--resume]
  [--force]
  [--json]
```

`--media-root` overrides configured roots for the run without mutating configuration. `--asset` is repeatable. Both normal and resume runs reuse valid cache entries; `--resume` explicitly communicates recovery intent in the run result. `--force` recomputes selected outputs but still uses atomic replacement.

## Durable protocols

- `artifacts/index/media-index.json`: media-index schema v1, deterministic asset ordering.
- `artifacts/proxies/<asset_id>.mp4`: H.264/AAC preview proxy when video exists.
- `artifacts/audio/<asset_id>.wav`: 16 kHz mono PCM speech-analysis proxy when audio exists.
- `artifacts/proxies/<asset_id>.jpg`: representative thumbnail when video exists.
- `artifacts/proxies/<asset_id>.time-map.json`: normalized proxy/source timeline relationship.
- `artifacts/proxies/<asset_id>.manifest.json`: cache inputs, FFmpeg version, completed outputs, and checksums.
- `artifacts/contact-sheets/sheet-<page>-<content-key>.jpg`: paginated raster thumbnail sheet.
- `artifacts/contact-sheets/manifest.json`: ordered sheet and asset membership.

Persistent times use integer microseconds. Rational FFprobe `time_base` and frame-rate strings are retained. A time map records source start PTS separately while proxy time starts at zero; later cut-list work uses the media index and time map instead of assuming filename, frame rate, or zero source PTS.

## Identity, fingerprint, and invalidation

- Asset ID: SHA-256-derived ID over the canonical media-root identity plus NFC-normalized POSIX relative path. Moving or renaming a source intentionally creates a new asset identity.
- Fast fingerprint `quick-sha256-v1`: file size, nanosecond mtime, and bounded beginning/middle/end samples. It detects ordinary change cheaply without reading the complete file.
- Optional full hash `sha256`: streamed in bounded chunks when `--full-hash` is set.
- A proxy manifest cache key includes schema version, asset ID, fast fingerprint, proxy settings, and FFmpeg version.
- Changed assets retain old generated files until a new atomic build succeeds, but their old manifests no longer validate. Removed assets are recorded in the ingest change set; their old artifacts are not selected and are not automatically deleted.

## Safety assumptions

- Supported defaults: `.mp4`, `.mov`, `.mkv`, `.m4v`, `.avi`, `.webm`, `.wav`, `.mp3`, `.m4a`, `.aac`, `.flac`, `.aif`, `.aiff`.
- A symlink target is scanned only when its canonical path remains within the same selected media root. Outside-root links are skipped with a warning unless a later explicitly authorized contract changes the safety policy.
- Artifact/media overlap remains a hard path error. Artifact directories are also excluded defensively during traversal.
- Camera-map files are YAML with ordered glob rules over root-relative POSIX paths. Unmatched camera/take fields remain null; names are never guessed.
- M2 does not transcribe, synchronize cameras, infer semantic content, create cut-lists, render edits, or delete orphan artifacts.

## File-level work

| Files | Responsibility | Verification |
|---|---|---|
| `src/interview_edit/models/media.py` | strict media-index, stream, change-set, camera-map, proxy/time-map models | schema/model unit tests |
| `src/interview_edit/adapters/filesystem.py`, `media.py` | bounded hashes, FFprobe/FFmpeg boundary, precise time parsing | adapter unit tests and live probes |
| `src/interview_edit/ingest/service.py` | safe traversal, IDs, camera rules, atomic index | unit/integration tests |
| `src/interview_edit/proxy/service.py` | per-asset atomic outputs, manifests, JPEG sheets, cache/resume | live FFmpeg integration tests |
| `src/interview_edit/cli/app.py` | thin `ingest` and `proxy build` routing | CLI JSON/help tests |
| `src/interview_edit/status/service.py` | media-index and proxy freshness counts | integration tests |
| `tests/fixtures/media_factory.py` | deterministic temporary synthetic media generation | used only when local FFmpeg exists |
| `tests/unit/`, `tests/integration/` | identity, parsing, cache, safety, idempotency, invalidation, atomic failure | `uv run pytest` |
| `docs/specs/`, `docs/decisions/`, Skill reference, README | freeze public protocols and operator flow | review plus link/schema checks |

## Ordered execution

1. Freeze the M2 protocol and decision record.
2. Add failing tests for indexing, identity, failure preservation, and cache invalidation.
3. Implement media models, probing, traversal, hashing, and atomic index writes.
4. Add failing tests for proxy artifacts, cache reuse, and selective rebuild.
5. Implement per-asset proxy outputs and contact sheets.
6. Expose commands, update status/Skill/docs, and run full verification.

## Acceptance commands

```bash
uv run ruff check .
uv run mypy src
uv run pytest --cov=interview_edit --cov-report=term-missing
uv build

interview-edit ingest --project <synthetic-project> --full-hash --json
interview-edit ingest --project <synthetic-project> --full-hash --json
interview-edit proxy build --project <synthetic-project> --resume --json
ffprobe -v error -show_format -show_streams <generated-proxy>
```

The installed wheel is also exercised from outside the source tree. Exact commands and outputs are recorded in `docs/tests/m2-acceptance.md`; unrun commands are not marked passed.

## Stop conditions

Stop and realign if M2 requires source writes, silent model/network use, filename-based semantic inference, unbounded whole-video reads, deletion of old valid outputs on failure, or a public protocol incompatible with the frozen V1 CLI names.
