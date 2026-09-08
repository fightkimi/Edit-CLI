# Jianying editable draft export v1

Status: experimental protocol output. Mac and Windows entry generation is tested structurally;
native application import/edit/render is **not verified** because the client is not installed.

## User workflow

```text
interview-edit --dry-run export jianying --project PROJECT --cutlist CUTLIST --name NAME
interview-edit export jianying --project PROJECT --cutlist CUTLIST --name NAME \
  [--platform macos|windows|both] [--bundle-media|--reference-media] [--json]
interview-edit jianying doctor [--json]
interview-edit jianying install --draft PACKAGE \
  [--draft-root EXISTING_DIRECTORY] [--platform macos|windows] [--json]
```

Global `--dry-run` applies to export and installation. `both` and `--bundle-media` are export
defaults. Bundling copies complete referenced original files and fonts once per path; large projects
should inspect the dry-run byte estimate first. Reference mode uses absolute local paths and cannot
be installed through the portable installer. Neither command downloads software or uploads data.

## Editable output

The package is a directory under `artifact_root/exports/<name>-<UUID>/` containing:

- `draft_info.json` for Mac, `draft_content.json` for Windows, or both;
- `draft_meta_info.json`, including all video/audio/photo material registrations;
- `Resources/` with bundled original media, images and fonts when bundling is selected;
- `export-manifest.json` with input SHA-256, resource file inventory and item-to-native-segment mapping;
- a Chinese handoff guide.

Primary video, camera-selected ranges, B-roll/still overlays, primary audio, subtitles and titles
remain native clips/text on separate tracks. Video tracks are muted while primary audio stays on its
own track. Source/target times are integer microseconds and camera offsets/drift use the same shared
mapping as the FFmpeg renderer. Native speed materials preserve source/target duration differences.
Rich text ranges use UTF-16 code units. Text is not converted to PNG or burned into an MP4.

Paired fades become editable native alpha/volume keyframes. Native font sizing, text backgrounds,
composited fades and audio playback must be reviewed in the application; they are not claimed to
match the FFmpeg output pixel-for-pixel or sample-for-sample. CLI master loudness processing is not
applied to the native project. Unsupported/invalid cut-list constructs fail rather than disappearing.

## Integrity and privacy

Export validates the complete cut-list using original-media preflight before writing. It hashes
used inputs, verifies copies, checks inputs again before atomic publication, and never changes the
source cut-list or media. Dry-run produces no files. Names must be portable between Mac and Windows.
The UUID prevents accidental collisions; outputs are never intentionally replaced.

Bundled paths use the native draft-folder placeholder before installation. Installation verifies
file sizes and SHA-256, rejects altered packages, symlink/path escapes and existing target drafts,
copies into staging, selects the host entry file, and rebases media/font paths to the new local
draft location. It preserves the original export package and the app's global `root_meta_info.json`.
If the app's list does not refresh, restart it; listing/import behavior still needs client validation.

The explicit installation destination is the user-authorized exception to artifact-root writes,
limited to a newly created draft under an existing library. It does not modify or decrypt an existing
Jianying project. Exported metadata includes original resource paths for provenance; do not assume
that an export package is anonymous. No machine IDs are collected or copied from old user projects.

## JSON and failure behavior

`export jianying` returns `draftPath`, `exportId`, `platform`, `bundledMedia`, `resourceBytes`,
`dryRun`, and `nativeValidation: not_run`. `resourceBytes` is the planned/actual bundled input size,
not an estimate of the final native rendered video. Warnings explicitly identify unverified client
compatibility and approximate native styling/audio treatment. The manifest is a typed local protocol;
the native draft is a version-pinned third-party JSON format.

`jianying doctor` reads known installation locations and returns the host platform, app path/version
when available, default draft root and existence. Missing client returns exit 4 with `jianying_missing`.
Windows version inspection is not currently implemented; an unavailable version is null.
On other operating systems native client detection fails explicitly; package export remains possible.

`jianying install` with no explicit root requires a detected client and its existing draft library.
An explicit root allows offline/manual installation into an existing library. This does not launch
the GUI or prove a draft was imported. The receipt retains `nativeValidation: not_run`.

General failure codes follow the CLI envelope: 2 for invalid arguments/names, 3 for invalid or stale
evidence/packages, 4 for missing native prerequisites, 5 for paths/permissions. Failed operations
clean only their own staging directories and preserve prior projects.

## Ownership after handoff

Once opened, native edits belong to Jianying and may change/encrypt its draft representation.
Do not install or regenerate over that project. There is no reverse importer or automatic merge
into the source cut-list. Render manually in Jianying after editing; existing CLI QC/freeze reports
do not certify that later native output. Automated GUI rendering is not part of this adapter yet.

## Protocol sources

Reviewed data templates originate from MIT-licensed `duoec/duo-video` at
`ef4eb46c823910553f901649f2f13fd7575e748f`, retrieved through `zenstory-ai/video-recap-skills` at
`ec369e7e38866f23e953903fb30de9638a900e57`. Runtime data and complete license are in
`src/interview_edit/adapters/jianying_templates/`; `SOURCE.json` records file hashes and scrubbing.
Example device IDs and times were removed before committing. Native field behavior was also checked
against pyJianYingDraft and capcut-cli source; no upstream executable is used by this exporter.
