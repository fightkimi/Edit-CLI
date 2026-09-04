# M4 cut-list and render implementation plan

- Status: implemented and locally verified
- Date: 2026-09-03

## Goal and acceptance

Turn the frozen edit protocol into a strict, inspectable cut-list and a local FFmpeg render
pipeline. The same model must cover interviews, talking-head videos, tutorials, reviews, vlogs,
screen recordings, and other creator formats without introducing documentary-only state.

M4 is accepted when:

- `cutlist scaffold` creates either a blank deterministic document or a chronological skeleton from
  one corrected transcript, without hidden narrative or model decisions;
- `cutlist inspect` reports structure and timing without dumping transcript, note, title, or subtitle
  text;
- `cutlist validate` checks schema, globally unique IDs, source ranges, camera/sync relationships,
  overlays, subtitle timing, image/font assets, paired transitions, and render-profile compatibility;
- invalid cut-lists return exit code 3 and do not create or replace a render;
- `render` can select a complete timeline, one act, or one content item and builds normalized,
  checksum-validated item caches before an atomic final publish;
- primary audio stays continuous while synchronized camera cuts and full-frame B-roll/still/title
  overlays change the displayed picture;
- subtitles and titles are rasterized locally, then composed with FFmpeg, so the feature does not
  depend on optional `drawtext` or `subtitles` filters;
- preview uses the existing M2 video proxies, master reads original indexed media, and master audio
  receives measured two-pass EBU R128 normalization;
- every render writes a run manifest containing complete inputs, selected scope, cache decisions,
  FFmpeg version and argument arrays, output checksum, and terminal state;
- lint, typing, unit/integration tests, build, isolated-wheel smoke, and synthetic preview/master
  probes pass, or any unrun layer is reported explicitly.

## Public command surface

```text
interview-edit cutlist scaffold --project PATH
  [--asset ID] [--output PATH] [--force] [--json]

interview-edit cutlist inspect --project PATH --cutlist PATH
  [--act ID] [--item ID] [--json]

interview-edit cutlist validate --project PATH --cutlist PATH
  [--profile preview|master] [--json]

interview-edit render --project PATH --cutlist PATH
  [--act ID] [--item ID] [--profile preview|master]
  [--output PATH] [--resume] [--force] [--json]
```

`--item` may be used alone or with its containing `--act`; an ambiguous item ID is impossible
because item IDs are globally unique. `--profile` overrides the document default for validation or
rendering but never mutates the cut-list. An omitted scaffold output is
`cutlists/revisions/cutlist-v001.yaml`; an existing file requires `--force`.

## Technical choices from measured environment

- Python 3.11+ and Pydantic v2 remain the runtime contract. Strict Pydantic models are the runtime
  authority; `docs/specs/cutlist-v1.schema.json` is their reviewable JSON Schema snapshot.
- FFmpeg 8.1.2 exposes `overlay`, `fade`, `xfade`, `concat`, and `loudnorm`, plus `libx264`,
  `h264_videotoolbox`, and AAC encoders. Its current build does not expose `drawtext`, `subtitles`,
  or ASS filters.
- Text is therefore rasterized to transparent PNG evidence before FFmpeg composition. Pillow
  12.3.0 is the verified local adapter, constrained by the package contract to `>=11.3,<13`;
  configured fonts are mandatory whenever a title or subtitle is present.
- Preview reads checksum-validated M2 video proxies. Master reads immutable original paths from the
  media index. `auto` video encoding probes VideoToolbox with a tiny real encode and falls back to
  `libx264`; the selected encoder becomes part of the cache key.
- Camera mapping follows the M3 convention `camera_time = reference_time + offset`, including the
  persisted linear drift term. Uncertain sync evidence blocks render.
- Basic V1 transitions are paired edge fades, not standalone timeline clips. This preserves a
  linear, additive item-duration model and avoids ambiguous overlap accounting.

## Durable outputs

- `cutlists/revisions/*.yaml`: user-owned, reviewable edit decisions.
- `artifacts/renders/cache/items/<cache-key>.mp4`: normalized reusable item output.
- `artifacts/renders/cache/text/<hash>.png`: deterministic local text raster.
- `artifacts/renders/runs/<run-id>.json`: append-only terminal render evidence.
- `artifacts/renders/<name>.mp4` or explicit `--output`: atomically published selection output.

## File-level work

| Files | Responsibility | Verification |
|---|---|---|
| `models/cutlist.py`, JSON schema and spec | strict v1 edit contract | model/schema tests |
| `cutlist/service.py`, `validation.py` | load, scaffold, inspect, domain preflight | invalid-boundary tests |
| `models/render.py`, `render/service.py` | selection, cache, run ledger, atomic publish | unit/integration tests |
| `adapters/render.py`, `text.py` | FFmpeg argument construction, encoder probe, local text PNG | real synthetic media probes |
| `cli/app.py` | thin command routing and one-document JSON | CLI integration tests |
| config/status/docs/Skill | public flow and measured dependency behavior | config/Skill validation |

## Ordered execution

1. Freeze this plan, ADR 0006, strict cut-list models, and generated JSON Schema.
2. Add failing model, scaffold, inspect, and validation tests; implement the cut-list service.
3. Expose the three cut-list commands and verify stable JSON/preflight behavior.
4. Add failing render-selection, cache, sync mapping, atomicity, and run-manifest tests.
5. Implement normalized item rendering, camera cuts, overlays, text rasters, transitions, and final
   assembly.
6. Implement preview/master differences and measured two-pass master loudness.
7. Update status, README, CLI/Skill references, then run full and installed-wheel acceptance.

## Acceptance commands

```bash
uv run ruff check .
uv run mypy src
uv run pytest --cov=interview_edit --cov-report=term-missing
uv build

interview-edit cutlist scaffold --project <synthetic-project> --asset <asset-id> --json
interview-edit cutlist validate --project <synthetic-project> --cutlist <cutlist> --json
interview-edit render --project <synthetic-project> --cutlist <cutlist> \
  --profile preview --resume --json
ffprobe -v error -show_format -show_streams <preview-output>
```

Master, camera-switch, overlay, subtitle, transition, cache-hit, invalid-cut-list, and interrupted-run
fixtures are exercised separately. Exact commands and observed results belong in
`docs/tests/m4-acceptance.md`; no command is recorded as passing until it has actually run.

## Assumptions and stop conditions

- `primary` is the generalized successor to the PRD's interview item. `content_role` carries the
  specific creative role; this is consistent with ADR 0002 and the already frozen v1 draft.
- Source-backed items play at 1x in M4. Speed ramps and retiming are later milestones.
- Camera cuts and visual overlays are item-relative; source in/out fields remain source-relative.
- Visual overlays replace the full frame while the primary audio continues. Picture-in-picture,
  keying, animation, and semantic layout are later work.
- A transition is declared identically as `transition_out` and the next item's `transition_in`.
- A missing valid proxy blocks preview; preview does not silently rebuild it. A missing or uncertain
  sync report blocks a camera switch.
- Stop and realign if implementation would write source media, accept an invalid cut-list, expose
  content-bearing text in inspect output, download without authorization, persist float edit times,
  or overwrite a previous successful output before a replacement is complete.
