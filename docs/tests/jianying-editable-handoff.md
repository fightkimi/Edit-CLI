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

## Native acceptance matrix (updated 2026-10-08)

The user authorized official App Store installation and resumed Mac acceptance. The installed
client is Jianying Pro 11.5.0 on macOS 26.6.2. `jianying doctor` detects the correct bundle and
native project directory. With the app closed, `jianying install` installed the previously verified
2.8-second schema-2 synthetic draft named `剪映可编辑验收-v2…5BC5`. After restart the app scanned
and displayed it without a custom global registry write. Existing projects were preserved.

| Platform | App/version | Discover/open | Edit tracks/text | Save/reopen | Native export | Result |
|---|---|---|---|---|---|---|
| macOS | Jianying 11.5.0 / macOS 26.6.2 | Discovery observed; open and independent tracks reported by user | Actual text change pending | Pending | Pending | Partial evidence |
| Windows | No test machine, confirmed by user | Pending | Pending | Pending | Pending | Unverified |

The computer-control tool repeatedly failed card clicks with `windowNotFoundAtPosition`; after
manual opening it continued to expose the home window, not the user's editor. The user confirmed
independent tracks were visible. This is user-observed evidence, not an independently captured
editor test. The requested text edit, save/reopen and MP4 export have no completed result yet.
The response “可以” authorizes that manual sequence but does not prove it succeeded. The local
native-output directory is `artifacts/acceptance/native/`; no native output has been supplied.

Native-created control files on this client are encrypted/non-JSON. They were not decrypted or
used as a verified draft-format fixture. No certified compatibility range is declared from one
open report. Source-based synthetic tests and OS CI remain distinct from native acceptance.
The earlier App Store authorization blocker is resolved; Windows GUI remains unavailable.

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

Open issues remain exact native field compatibility, font/layout/sound fidelity and actual
save/reopen/export. Mac 11.5.0 discoverability has been observed for this synthetic package.
The module remains experimental; local color corrections and motion overlays have no native mapping.
