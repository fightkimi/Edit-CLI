# Editable Jianying handoff

User direction: the result must remain adjustable in Jianying instead of only a flattened MP4.
Both Mac and Windows are target platforms. The user confirms Jianying is not installed locally.

Implement an experimental native-draft export from the current cut-list: original video ranges,
camera selections, independent primary audio, B-roll/stills, and editable text. Bundle referenced
media when requested, use platform-specific draft entry files and preserve source/provenance.
Unsupported features must fail explicitly instead of flattening or silently dropping them.

Commands: `export jianying` (new artifact-only draft package), `jianying doctor` (client/draft-root
inspection), and `jianying install` (explicit local draft-library handoff of a verified package).
Installation must never replace an existing project or rewrite the app's global registry. Opening
the native client and final rendering cannot be verified on this machine until it is installed.

Architecture: a schema adapter produces native data; an export service validates evidence and
publishes atomically under artifact_root/exports; shared timing logic is reused by FFmpeg and export.
Native manual edits become owned by Jianying; there is no implicit round trip to the original
cut-list, and CLI release QC does not certify later native changes.

Protocol evidence: MIT-licensed duo-video templates, pinned through video-recap-skills; copy only
reviewed empty data templates and license notices, remove example device IDs before inclusion.
No upstream executable or model is installed. Both target formats remain client-unverified until
opened, edited and rendered in the actual app version.

Acceptance: tests for editable text, ordered source/target times, main audio across camera/B-roll
changes, unique IDs, UTF-16 text ranges, complete material registration, portable bundled paths,
source integrity, dry-run/no writes, path escapes/symlinks, no overwrite, and unsupported features.
Run Ruff, mypy, full pytest and a wheel package-content check. A JSON/schema pass must never be
reported as successful native-app import.
