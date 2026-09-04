# ADR 0004: Media identity, change detection, and proxy cache

- Status: accepted
- Date: 2026-09-03

## Context

M2 must index very large local media trees without copying media, keep cut-list references stable across repeated scans, notice source changes cheaply, and rebuild only affected generated artifacts. It must also survive interruption without damaging earlier successful outputs.

Filename alone is not a safe identity, while hashing every byte of hundreds of gigabytes on every scan is unnecessarily expensive. Content-only identity would also make a normal in-place source replacement silently retain the same cut-list identity.

## Decision

An asset's stable identity is derived from its selected canonical media root and NFC-normalized relative POSIX path. Its mutable revision is represented by a versioned fast fingerprint over metadata and bounded byte samples. Full SHA-256 is optional.

FFprobe metadata is committed only after every selected source has been probed successfully. The index is written by atomic replacement. A failed ingest therefore leaves the previous successful index usable.

Generated proxy artifacts are committed per asset by atomic replacement. Their manifest cache key contains the asset identity, fingerprint, complete output settings, implementation schema, and detected FFmpeg version. Cache validation never relies only on file existence.

Source symlinks are accepted only when their resolved target remains inside the same media root. Artifact and media trees may not overlap. Removed-source artifacts are retained but become unreachable from the current index; cleanup is a separate future explicit operation.

## Consequences

- Unchanged scans are idempotent and cheap relative to full hashing.
- Rename or movement creates a new asset ID and requires deliberate cut-list reconciliation.
- Touching mtime conservatively invalidates the fast fingerprint even if bytes are unchanged.
- Sampled hashing is change detection, not cryptographic proof; `--full-hash` supplies proof when needed.
- Different FFmpeg versions invalidate proxy cache entries even if output might happen to be compatible.
- Completed assets survive interruption, while partial current files are never published as successful artifacts.
