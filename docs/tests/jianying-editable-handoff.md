# Jianying handoff verification

Date: 2026-09-08. Self-review and automated tests; native client acceptance is pending.

- `uv run ruff check .`: passed.
- `uv run mypy src`: passed, 65 source files.
- `uv run pytest`: **146 passed in 30.20 seconds**, including 14 native-export/installation tests.
- Wheel/source-distribution build: passed. Wheel contents include all eight reviewed protocol
  JSON templates, their source record and MIT license notice.
- Main Skill metadata and all local references: passed.
- Template identity scan: example device ID, disk ID, MAC address and OS version are empty.
- `jianying doctor --json`: correctly returned exit 4, `jianying_missing`, no app path and
  `nativeValidation: not_run` on this Mac. No app or draft library was present.

Tested behaviors: Mac/Windows entry names and platform tags, source/target microseconds, UTF-16 text
ranges, editable text material, muted visual tracks plus independent primary audio, B-roll overlays,
stills and overlapping title layers, native alpha/volume fade keyframes, full media/font bundling,
material registration, source hashes, package verification, installation path rebasing, unchanged
global registry, no overwrite, changed/symlink package rejection, portable filename rules, dry-run
with no writes and invalid-cut-list rejection. A multicamera case verifies a 100,000 µs camera offset
while the main audio remains one 800,000 µs segment.

A 2.8-second synthetic editable example was exported through the actual CLI and its package verified.
It contains a title, two subtitle cues, a main clip/audio pair, B-roll and paired fades. The portable
ZIP and source fixtures are local evidence, excluded from Git. This example is not a native render.

Not verified: application registration/list refresh, actual import in any installed Mac/Windows
Jianying version, font loading, editable-track interactions, save/reopen, visual/audio fidelity and
native final rendering. Structural tests are not substitutes for these acceptance checks. After the
client is installed, record its exact version and execute those checks before claiming compatibility.
