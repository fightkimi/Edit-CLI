# Jianying editable draft contract

Status: experimental native protocol. Export and installation target both macOS and Windows.
No Jianying app/version is certified by this project yet. This document supersedes the initial
v1 manifest contract; newly generated packages use manifest schema **2**.

## User workflow

```text
interview-edit --dry-run export jianying --project PROJECT --cutlist CUTLIST --name NAME
interview-edit export jianying --project PROJECT --cutlist CUTLIST --name NAME \
  [--platform macos|windows|both] [--bundle-media|--reference-media] [--resume] [--json]
interview-edit jianying verify --draft PACKAGE [--json]
interview-edit jianying doctor [--draft-root DIRECTORY] [--json]
interview-edit jianying install --draft PACKAGE \
  [--draft-root EXISTING_DIRECTORY] [--platform macos|windows] [--json]
interview-edit jianying open [--json]
interview-edit jianying check-output --draft ORIGINAL_PACKAGE --video COMPLETED_VIDEO \
  [--expected-duration-us MICROSECONDS] [--json]
```

Use `both` and bundled media unless a receiving computer requires another choice. Dry-run writes
nothing and estimates complete input file sizes, including fonts. Reference mode uses absolute local
paths and cannot use the portable installer. Commands never download software or upload footage.

After installation, `open` requests an OS launch of the detected client. Select the new draft in
Jianying, check and edit it, save/reopen, and use Jianying's Export action. This command does **not**
select a draft, observe its editor or automate rendering. A process launch is not native acceptance.
If the draft does not appear, retain it and record the app version; do not keep copying duplicates.

## Editable package

Outputs live under `artifact_root/exports/<name>-<UUID>/`:

- Mac `draft_info.json`, Windows `draft_content.json`, or both;
- `draft_meta_info.json` with video/audio/photo registration;
- `Resources/` with complete media, images and fonts when bundling;
- `input-cutlist.yaml`, the exact input bytes used for serialization;
- typed `export-manifest.json` and a Chinese handoff guide.

Video/camera cuts, B-roll/stills, primary audio, subtitles and titles remain separate native segments.
Visual tracks are muted; primary audio stays on its own track. Persistent time uses integer
microseconds. Camera mapping reuses the FFmpeg renderer's source/sync calculations. Source/target
length differences have matching native speed materials. Text style ranges use UTF-16 units.
Fades become alpha/volume keyframes. Native typography, composed fades and sound require in-app
review; CLI master loudness processing is not applied to this draft.

## Input and semantic verification

The exporter parses and hashes the same cut-list byte snapshot, rejects a stale passed document,
captures index/sync hashes and binds media to indexed size/mtime/fingerprint evidence. Image/font
revisions are captured before their use. Copies must match captured SHA-256; inputs are checked again
before atomic publication. Source media and cut-lists remain unchanged.

Manifest schema 2 adds the input snapshot, configuration/control hashes, indexed source identities,
source durations and resource digests, and native-material-to-source mappings. Old schema 1 packages
fail with `jianying_reexport_required`; re-export from the original cut-list. This never migrates or
rewrites a project that the user has edited in Jianying.

An independent validator checks file inventories, portable paths, unique IDs, resolved references,
material/track types, integer positive time ranges, bounds/nonoverlap, speed relationships, supported
keyframes, complete UTF-16 style coverage, media registration and source provenance. It compares
native text/timing and canvas with the input snapshot, checks each segment belongs to its input item,
and checks both platform timelines/materials are identical except platform metadata. Rehashed but
semantically invalid packages are rejected before installation. This detects internal consistency;
it is not a cryptographic signature or proof that Jianying accepts a third-party format.

Bundled resources use the native draft-folder placeholder. Installation verifies the package,
rejects symlink/path escapes and existing targets, stages a private copy, rebases media/font paths,
verifies the installed copy and publishes a new directory. The original package and existing user
drafts remain intact. The global `root_meta_info.json` is preserved: whether the app scans this folder
or needs registration remains a native acceptance question, not an assumed universal behavior.

The explicit native draft directory is the authorized exception to artifact-root writes, limited to
a new draft in an existing library. No old project is decrypted or rewritten. Provenance includes
original paths and the original cut-list; portable packages are not anonymous. Device IDs are empty.

## Large inputs and retry

`--resume` retains complete verified resources in `artifact_root/exports/.media-cache/<SHA-256>`.
Every cache hit is rehashed; corrupt entries are replaced from the checked source. Outputs are copied,
never hard-linked to sources or cache. Interrupting a copy removes that temporary file and the
export's staging directory; completed cache entries survive. A retry creates a fresh draft with new
IDs and reuses valid complete resources. This is file-level reuse, not byte-level resume. It still
reads inputs and verifies outputs, so there is no promised speed-up or fewer complete copies.

Without resume, space preflight reserves bundled input bytes plus metadata allowance. Resume uses a
conservative two-copy reservation plus allowance, even when cached files exist. Cache retention is
opt-in and may consume substantial disk space. Progress reports hash/copy percentages on stderr,
leaving the JSON stdout envelope intact. Global `--quiet` suppresses progress.

## Client detection and version evidence

Mac detection reads bundle identity/version in user/system Applications. Windows checks known
JianyingPro executable locations, orders version directories numerically, and reads the selected
executable's PE version through the Windows version API without executing it. Unknown versions stay
null. `doctor --draft-root` and `INTERVIEW_EDIT_JIANYING_DRAFT_ROOT` support explicit custom locations;
otherwise the known platform default is reported. Native app settings are not rewritten or inferred.

`doctor` includes `appPath`, `appVersion`, `draftRoot`, `draftRootExists`, `draftRootSource`,
`compatibility: unverified`, `automatedExport: false` and `nativeValidation: not_run`. Missing app
returns exit 4. Linux can generate/check packages but native detection/launch fails explicitly.
No version is labeled compatible solely because another project reported success.

## Output check and ownership

`check-output` is read-only. It requires the original unedited schema-2 package, checks the selected
video's dimensions, duration within one input timeline frame, presence of expected audio, full
FFmpeg decode, and an unchanged SHA-256 across verification. If manual trimming changed duration,
pass the new explicit `--expected-duration-us`; it is never silently taken from the video itself.
The typed JSON result records video hash, actual/expected duration, tolerance, dimensions/audio and
`output_check: passed`. It does not establish that the video came from Jianying, nor certify picture,
loudness, captions, editable tracks or save/reopen. `native_validation` remains `not_run`.

Native edits belong to Jianying and may change/encrypt its files. Never run package verification as
an acceptance gate on the subsequently edited live draft. Never re-export/install over that draft.
There is no reverse importer or automatic merge into cut-list. Existing CLI QC/freeze reports do not
certify manual native edits. Unattended native GUI export remains pending actual client/version work.

## Failure and receipt semantics

Export JSON adds `cachedResources` to `draftPath`, `exportId`, `platform`, `bundledMedia`,
`resourceBytes`, `dryRun` and `nativeValidation: not_run`. Install means files were copied and checked.
`verify` returns `packageValidation: passed`; `open` returns `launchRequested`; neither upgrades native
validation. Dry-run also applies to open. `verify`, `doctor`, and `check-output` are read-only checks.

Exit codes remain: 2 invalid arguments; 3 stale/invalid inputs, packages or output checks; 4 missing
prerequisites; 5 filesystem/permissions; 1 processing failure; 130 interrupted. Failures do not publish
partial drafts or overwrite an existing draft. Unknown/malformed native structures fail explicitly.

## Protocol sources

The eight reviewed JSON templates retain the recorded MIT licensing decision: `duoec/duo-video`
`ef4eb46c823910553f901649f2f13fd7575e748f`, retrieved through `zenstory-ai/video-recap-skills`
`ec369e7e38866f23e953903fb30de9638a900e57`. Source hashes and license remain alongside the templates.
See [first-principles audit](../research/2026-09-08-jianying-first-principles-audit.md) for upstream
version/automation limitations and [acceptance record](../tests/jianying-editable-handoff.md) for
this project's actual evidence. No upstream executable or new dependency is used by this adapter.
