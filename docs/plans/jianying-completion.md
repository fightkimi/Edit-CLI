# Jianying correctness and native acceptance

User request: fully address the first-principles audit. Baseline `1b65b03`.

1. Add independent negative regression tests for stale cut-list snapshots, source replacement,
   orphan materials, empty tracks and invalid native times.
2. Capture immutable input evidence before serialization; bind source hashes to indexed revisions
   and compare before publication. Add reusable media-copy caching and progress without bypassing
   content checks.
3. Validate native references, types, track ranges, speed relationships, material registrations,
   UTF-16 styles, keyframes, duration and cross-platform entry parity before export/install.
4. Detect native client versions and configured draft locations; keep unknown version support
   explicit. Add safe native launch and verified-output recording, with platform-specific tests.
5. After explicit installation approval, install the official Mac client for native acceptance. Use a new synthetic
   draft only; observe discoverability, opening, editing, save/reopen and export. Obtain action-time
   confirmation if a legal agreement or unexpected permission is presented. Do not bypass security.
6. Add Windows CI for executable platform checks. Native Windows GUI acceptance requires a Windows
   environment; record it separately instead of claiming macOS tests certify Windows.
7. Update the existing PR with fixes, documentation and exact evidence. Preserve existing PRD files
   and local-only media. Keep unresolved native behavior visible until actually verified.

Completion requires fresh Ruff, mypy, tests, packaged CLI checks, and documented native acceptance
per available client/version. No encrypted-draft decryption, overwriting an edited project, or
assertion weakening is authorized by this plan. User-approved editable handoff permits creating a
new native draft and the registration work proven necessary by the installed app, with backup and
rollback. Existing native projects must remain intact.


Current result: input/semantic fixes, complete-file cache/progress, version detection, explicit
custom draft location, OS launch and read-only output checks are implemented. Native settings and
project registry adaptation are deferred until actual client observations justify them. No guessed
GUI automation or compatibility range has been added. Windows native acceptance is unavailable by
user confirmation. Mac App Store installation is awaiting explicit permission after automatic
approval rejected the Get action; no alternate installation will bypass that decision.
