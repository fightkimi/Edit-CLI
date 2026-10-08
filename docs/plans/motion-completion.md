# Complete the scoped video-use optimization series

User authorized continuing the remaining work to completion. Implement local editable motion
source assets, attach/regenerate workflow, full preview/QC smoke and accurate acceptance evidence.
Continue on the existing two PRs, preserving user files and existing source-media/approval gates.

Scope:
1. Three bounded templates: callout, lower-third and chapter card. Typed source specification contains
   text, subtitle, local font, palette, dimensions/frame rate and integer timing. Produce transparent
   QTRLE MOV through the CLI with deterministic easing, no external runtime or cloud dependency.
2. Assets are immutable artifact directories with spec, render, preview and hash manifest. Editing
   produces a new asset, so an old cut never changes unexpectedly. Validate glyphs/text layout,
   timing, image dimensions, input revisions and package checksums before publish or attachment.
3. Attach an asset as an item-relative motion overlay in a new validated cut-list. Render it before
   subtitles, preserve alpha and main audio, include hashes in cache/run provenance and reject altered
   assets. Keep original editable text overlays/subtitles unchanged.
4. An asset's spec and CLI regeneration are editable; generated motion pixels are not native NLE
   text layers. Native mapping must remain explicit rather than silently omit/bake unsupported edits.
5. Verify actual movie alpha, duration/frame count, easing, immutable revisions, attachment and full
   preview/QC path. Add meaningful negative tests and Windows/Mac CI. Inspect synthetic samples.
6. Real footage requires a local project/media path (none discovered in the code repository).
   User approved official App Store installation and resumed Mac acceptance. Jianying 11.5.0 is
   installed, draft discovery is observed and independent tracks are user-confirmed. Save/reopen
   and native export remain pending due inaccessible editor controls; Windows GUI is unavailable.
   Do not claim real-media or native acceptance from synthetic tests or OS CI.
7. Run Ruff/mypy/full tests and isolated packaged CLI. Push same commit to both existing PRs and
   record final CI and remaining acceptance facts. Do not merge merely from older merge authorization.

Acceptance: complete round-trip spec editing → new asset → validated cut → rendered preview, with
alpha, readable text, source/control integrity, immutable old outputs, precise integer timing and
honest native editability. Completion of code scope is separate from unavailable external acceptance.
