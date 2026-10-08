# Native effects and export jobs

User authorized continued development and paused physical-client acceptance on 2026-10-08.
Continue the existing two PRs; preserve unrelated PRDs and local generated evidence.

Scope and acceptance:
- Opt-in experimental native effects: map bounded brightness/contrast/saturation to their documented
  native keyframes. Reject gamma rather than pretend native sliders reproduce FFmpeg gamma.
- Attach verified transparent motion movies on an independent video track with retained source spec
  and package provenance. Native trim/position is separate from regenerating the movie's text.
- A schema-3 draft describes generated media and effect provenance; old schema-2 packages remain
  readable. Independent verification rejects missing/altered effect values, timing, source or specs.
- Persistent export jobs bind an original package, installed draft and a private output path. Manual
  completion works on both platforms; optional legacy-Windows automation runs in a bounded worker.
  Atomic publication requires output media checks. Failed/incomplete exports preserve prior outputs.
- Modern Mac/Windows GUI automation is not inferred from legacy selectors. No actual client is
  launched, installed, edited or exported during this development request.
- Verify contract/CLI behavior, failures/resume, native serialization and synthetic output checks,
  then Ruff/mypy/full pytest, isolated wheel and both-repository CI.

Reference: GuanYixuan/pyJianYingDraft keyframe.py and jianying_controller.py (read-only source evidence).
No upstream code is copied. Native application compatibility and perceptual equivalence remain unverified.
