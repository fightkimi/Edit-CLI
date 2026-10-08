# Editorial review and output quality — video-use reference

Approved scope: cross-source phrase reading view, cut-window filmstrip/waveform/word evidence,
configurable audio edge smoothing, and caption pause/readability constraints. Reference assessment:
`docs/research/2026-10-08-video-use-reference-assessment.md`.

Implement within the existing Python CLI, typed cut-list and artifact-root rules. Do not install
upstream skills, add cloud transcription, change QC acceptance, add animation runtimes, or resume
paused Jianying native acceptance. No upstream executable/source copying is planned.

1. Reuse verified corrected transcripts for a phrase index across selected sources. Write content
   only to a new artifact; CLI JSON remains content-safe. Preserve original word/time mappings;
   missing speaker/event evidence is explicitly unknown.
2. Add a bounded timeline-review command for indexed source proxies and successful render runs.
   Filmstrip and absolute PCM waveform share integer-microsecond time coordinates. Map output
   words back to sources, record checksums, distinguish missing audio from decode failure, preserve
   existing evidence after failure, and reject stale run/source/transcript evidence. Never interpret
   a waveform image as listening acceptance.
3. Add opt-in 0–50ms audio edge smoothing to cut-list policy. Preserve continuous audio across
   adjacent contiguous ranges/camera changes, cap fades on short clips, include boundary context in
   render cache keys, and mirror the policy in Jianying's native volume keyframes. Defaults preserve
   existing projects. Verify PCM behavior and timeline duration on synthetic media.
4. Extend existing Chinese caption splitting with optional pause/minimum-duration/read-speed
   constraints, preserving text and explicit estimated timing. Never grow beyond original cues,
   cross a meaningful pause solely to meet duration, or hide unresolved readability warnings.
5. Update frozen schemas/contracts and focused Skill references. Run Ruff, mypy, full tests,
   installed CLI and synthetic visual/media checks; add affected tests to both OS CI paths.
6. Commit scoped code, tests and durable docs to a fresh feature branch, push the same commit to
   both requested GitHub repositories, open/attach a PR and inspect CI results.

Acceptance: consistent source/output time mappings, complete text, no private content in JSON,
validated inputs and atomic new review artifacts, no spurious audio dips on continuous joins,
measurably reduced discontinuity on noncontiguous synthetic joins, bounded short-clip treatment,
caption text/bounds preservation with warnings for impossible duration constraints. Actual editorial
and listening improvement requires a later real-media comparison and is not claimed by test counts.

Runtime discovery: the cut-window demo exposed per-item AAC priming/padding gaps even when the
boundary plan preserved a continuous source. A failing PCM-energy regression confirms this. Include
PCM audio in MOV item/assembly caches and encode final audio once (video remains stream-copied at
assembly/finalization). Version cache keys to prevent old AAC item reuse. Keep final preview/master
formats, approval and loudness gates. Timeline WAV extraction resolves presentation-clock packet
irregularities before trimming and rejects incomplete windows; it does not hide decoder failures.
