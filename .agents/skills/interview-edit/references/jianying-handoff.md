# Editable Jianying handoff

When the user wants to continue adjusting a cut in 剪映 / Jianying, export native editable tracks
instead of treating a flattened MP4 as the editable deliverable. Reuse the current cut-list and
its validation/source evidence. The CLI remains the execution engine.

1. Resolve the project and privacy mode and inspect status. Check current CLI help for export
   jianying and jianying doctor/install/verify/open/check-output. Do not guess additional app automation commands.
2. Validate the complete cut-list. Export with --name and --platform macos|windows|both (both is
   default). Use --dry-run first when bundling a large source set. --bundle-media copies complete
   original files/fonts; --reference-media is local-only and cannot use the portable installer.
   --resume optionally retains and rechecks complete cached resources; it needs extra disk space.
   Export schema 2 binds the input snapshot and source revisions. Re-export old schema 1 packages;
   never migrate or overwrite a draft already edited in Jianying.
3. Report the exported draft path, bundled size, platform entries, manifest and warnings. Video,
   primary audio, B-roll/stills, titles and subtitles remain separate native segments. Fades are
   native alpha/volume keyframes. Native text styling/composition and audio treatment require review;
   do not promise pixel/sample identity to the FFmpeg preview or normalized native master audio.
4. Run jianying doctor on the receiving computer. A missing client or draft library is a prerequisite,
   not an import success. Do not install/downgrade software or decrypt user drafts as an implicit fix.
5. If local draft-library installation is requested, use jianying install --draft PACKAGE. It creates
   a new draft and leaves existing projects and the global app registry alone. Use --draft-root only
   for the user's identified existing native draft library. It is the explicit exception to writing
   generated output under the original artifact root.
6. Use jianying verify on the original unedited package. Use jianying open to request an OS launch;
   it does not select a draft or prove the editor loaded it. In the actual app/version, verify the new draft appears, opens without missing media, exposes
   separate editable text and clip tracks, can save/reopen, and can render a short sample. Until then
   report nativeValidation=not_run. Current CLI commands do not drive GUI rendering.
7. After the user finishes native export, run jianying check-output --draft ORIGINAL_PACKAGE
   --video COMPLETED_VIDEO. If trimming changed the duration, pass the new expected-duration-us
   explicitly. A media-check pass proves decoding/dimensions/duration/audio presence and a stable
   hash, not native app provenance, editing, save/reopen or visual/audio quality.
8. Record the exact platform/version and observed native steps. Windows remains a target even
   without a test machine; CI platform tests do not certify the Windows Jianying GUI. Unknown
   versions remain unverified. A rejected software installation requires explicit user approval;
   do not bypass operating-system security or use another installer to evade the rejection.

Manual edits belong to Jianying. Never regenerate over an edited draft or suggest a round-trip
importer that does not exist. Existing CLI release QC/freeze evidence does not cover the manual
native result. Opening native previews must honor the current privacy/user consent scope.
