# Jianying handoff verification

Date: 2026-09-08. This is implementation self-review, not independent or native app acceptance.
Baseline audit commit: `1b65b03`; the completion fixes are on PR #2.

## Current local evidence

- Ruff: passed. Mypy: passed, 68 source files.
- Full suite: **178 passed, 1 skipped in 33.72 seconds**. The skip is the real Windows PE version API
  test on this Mac; it is included in the Windows CI job. The earlier 146-test baseline is superseded.
- New regression tests initially reproduced stale cut-list/source races and invalid native timelines
  being accepted; the repaired path now rejects them before publication or installation.
- The 2.8-second title/subtitle/audio/B-roll/fade demo was regenerated through the actual CLI with
  schema 2, bundled original resources and an input snapshot. `jianying verify` passed. The local
  demo and media remain ignored artifacts; this is not a video rendered by Jianying.
- Wheel/source distribution build passed. A fresh isolated wheel installation passed command
  registration, JSON envelope parsing, actual schema-2 package verification, expected missing-client
  exit and all eight bundled template loads. It imported the installed wheel, not the source tree.

Tests cover wrong references, empty tracks, negative/overflowing times, duplicate IDs, track/material
mismatch, inconsistent speed/keyframes, rehashed wrong text/UTF-16 styles, changed source provenance,
incomplete registration, malformed structures and platform divergence. Input cases include a stale
in-memory cut-list, saving during serialization, media replacement after preflight/during copy and
an image changed after its dimensions were read. Rejected drafts are not published.

Cache tests check verified reuse, corrupt-cache repair, interrupted temporary cleanup and independent
output copies. Output checks use synthetic media to verify dimensions, duration, explicit changed
expectations and unreadable files; they do not claim native rendering. Platform tests cover Mac
bundle identity, Windows version-directory ordering, real Windows PE version API (Windows only),
custom locations and launch failures/dry-run. Existing export tests continue to cover both entry
names, path rebasing, old-project preservation, fonts, text, photos, multicamera timing and fades.

CI now includes macOS 14 and Windows 2022 runners for platform contracts and the three Jianying
integration modules, in addition to the full Linux Python 3.11/3.12 checks. These are **OS execution
checks without a Jianying GUI**. They must not be described as native app compatibility tests.

## Native acceptance matrix

| Platform | App/version | Discover/open | Edit tracks/text | Save/reopen | Native export | Result |
|---|---|---|---|---|---|---|
| macOS | Not installed | Pending | Pending | Pending | Pending | Unverified |
| Windows | No test machine available, confirmed by user | Pending | Pending | Pending | Pending | Unverified |

Mac `jianying doctor` returns exit 4 and `jianying_missing`. The official website bootstrap installer
failed a local signature check and was not executed. The official App Store listing was reached,
but automatic approval rejected clicking Get because explicit software-installation authorization
was missing. The installation question remains pending; no alternate download or launch bypasses it.
Windows remains a supported output target; the user explicitly confirmed native validation is
currently unavailable. No version is added to a certified compatibility range.

## Repeatable native checklist after prerequisites are available

Use a new synthetic draft, not an existing user project. Record exact app version and OS, package ID,
input snapshot hash and resulting video hash. Keep screenshots/media as local evidence.

1. Run doctor; confirm the actual configured draft directory. Close the app before new-draft install.
2. Export and verify a fresh schema-2 package. Install once into the identified library.
3. Launch and observe whether the new project appears. If it does not, inspect a native-created
   empty project's storage/registration before implementing any registry change. Preserve old drafts.
4. Open with no missing-media warnings. Inspect main video, audio, B-roll, title, Chinese/emoji text,
   fades and alignment. Change subtitle text and one clip boundary; capture the actual result.
5. Save, close and reopen. Confirm both changes persist and other tracks remain intact.
6. Export from Jianying to the project's artifact area; wait for actual app completion. Run
   check-output using the original package and the new expected duration if it was trimmed.
7. Watch/listen to the result, checking captions, frame composition, cuts, fades and sound. A full
   decode pass alone does not certify these qualities or native provenance.
8. Only record native acceptance for the exact app/platform version and the features observed.
   Changes to discovery, registration or GUI automation need their own evidence and regression tests.

Open issues remain client discoverability/registration, exact native field compatibility, native
font/layout/sound fidelity, real save/reopen and export. No fixture from an actual installed client
is available. The module remains experimental until those steps are observed.
