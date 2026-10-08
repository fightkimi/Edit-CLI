# Local motion verification

Date: 2026-10-08. This is implementation self-review; it does not certify creative quality or
native editor compatibility. Contract: [motion-assets-v1.md](../specs/motion-assets-v1.md).

Fresh local verification: Ruff passed; mypy passed (83 source files); full pytest
**218 passed, 1 skipped in 52.31 seconds**. The skipped case is the real Windows version API on Mac;
Windows CI runs that case. Source/wheel build, isolated wheel installation and command help passed.

Focused cases exercise all three templates, actual decoded MOV alpha, frame count/duration, visible
text/overflow constraints, easing/hold/exit, palette/font source revisions, immutable old assets,
content-safe CLI output, successful attachment/render/preview QC, wrong project/path inventory,
modified source/movie rejection and encoder failure cleanup. A motion-containing native handoff
fails explicitly rather than losing the graphic. Mac/Windows CI runs these alongside Linux full tests.

An isolated installed wheel (working directory outside the repository) performed Chinese callout
generation, text/font/palette editing, verification, attachment, a source-color revision, preview
render, preview QC and timeline evidence. The generated 0.8-second 1280×720 H.264/AAC output has
SHA-256 `a1d3e7bc7910733d9e684295c8c7e1d23f20e22100eac3d47c26d7a9196177e9`.
Run: `render_20261008T082954Z_fb3e534dd7`; preview QC:
`qc_20261008T083018Z_2ab6abee1c`, passed with unchanged warnings for incomplete color metadata and
the fixture's quiet sine-tone level. Video/audio/timeline duration deltas were zero. No master,
release QC or freeze was requested or performed.

The CLI-generated timeline contact sheet was inspected: transparent entrance, readable hold,
near-transparent final frame and visible blue background. Actual decoded alpha is also checked in
tests. Still-frame review does not establish motion smoothness or listening quality.
This is a synthetic blue-video/tone fixture, not real speech or a comparison of narrative quality.
Generated sources and all evidence remain ignored local files under `.interview-edit/acceptance/`.
Native export uses the separately created `artifacts/acceptance/native/` directory.

Remaining limits: motion source parameters can be regenerated, but its movie pixels cannot be
edited as native text. Native motion/color mappings are unsupported. Mac Jianying 11.5.0 discovery
is observed and independent tracks are user-reported; text edit, save/reopen and native output are
pending. Windows GUI is unavailable. See [native evidence](jianying-editable-handoff.md).
