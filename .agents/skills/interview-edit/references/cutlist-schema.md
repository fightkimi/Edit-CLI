# Cut-list working rules

The repository contract lives at `docs/specs/cutlist-schema-v1.md` with a generated machine snapshot at `docs/specs/cutlist-v1.schema.json`. Read those files before authoring a cut-list.

Essential rules:

- Persist time as integer microseconds, never bare floating-point seconds.
- Use stable and unique project, act, item, and source IDs.
- Use `primary` for the main spoken narrative and `content_role` for interview, talking-head, tutorial, review, vlog, screen capture, or another editorial role.
- Use `broll`, `still`, and `title` only for their defined render semantics. The `transition` enum is reserved in V1; express a basic fade as identical `transition_out` and `transition_in` values on adjacent items.
- Keep camera cuts, overlays, and subtitles item-relative and within the item's duration.
- Preserve one configured primary audio source when changing displayed cameras.
- Refer to indexed media and existing sync evidence. A `motion` overlay instead references a verified generated asset directory via `motion_path`; attach it with `cutlist motion`, retain non-overlap rules, and review source-regeneration/native limits in docs/specs/motion-assets-v1.md.
- Preview from validated proxies before requesting a master. Titles and enabled subtitles require a readable declared or project-configured local font.
- Do not hand-edit generated indexes, transcripts, run manifests, or QC reports as a substitute for correcting the true input.

After every edit, run `interview-edit cutlist validate --project PATH --cutlist PATH --json`. Stop on any nonzero exit and explain the exact validation evidence. Use `cutlist inspect` for structural checks because it omits content-bearing text.
