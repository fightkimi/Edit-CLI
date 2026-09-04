# ADR 0005: Local transcription checkpoints and multi-window sync

- Status: accepted
- Date: 2026-09-03

## Context

M3 adds the first content-bearing analysis stage. It must work on Apple Silicon today, retain a
portable CPU/CUDA path, recover from long-running inference interruptions, distinguish raw model
evidence from editorial correction, and synchronize cameras without trusting a single ambiguous
audio moment.

The measured host has MLX Whisper 0.4.3, NumPy 2.5.2, FFmpeg 8.1.2, and a previously authorized
local tiny-model snapshot. Faster-Whisper is not installed. MLX cannot see Metal inside the Codex
sandbox but has run on the host. The installed MLX API returns a complete dictionary rather than a
streaming generator, so recovery must be introduced above the backend boundary.

## Decision

- Keep backend-specific floats and objects inside transcription adapters. Convert all returned
  timestamps to integer microseconds at the service boundary.
- Extract bounded five-minute WAV chunks from the already-generated M2 audio proxy. Publish an
  atomic JSON checkpoint after each successful backend call, then assemble final JSONL/SRT outputs.
- Resolve model identifiers against local caches only. Missing registry models produce an explicit
  authorization/preflight error; the command never turns an identifier into a network download.
- Store raw recognition and corrected derivatives separately. Literal project dictionary rules do
  not mutate or invalidate raw recognition.
- Compute 100 Hz log-energy envelopes from normalized audio proxies and compare evenly distributed
  beginning/middle/end windows using normalized FFT cross-correlation.
- Fit offset against reference time to estimate drift. Preserve all window measurements so an
  operator can audit a result. Use the convention `camera_time = reference_time + offset`.
- Treat low confidence as a preflight failure after writing the report/evidence. Manual offsets are
  allowed but retain explicit provenance and never pretend to be automatic evidence.
- Generate visual contact sheets only from existing local video proxies when `--visual-check` is
  requested. No source video or audio leaves the machine.

## Consequences

- Restarting a long transcription repeats at most one unfinished chunk.
- Independent chunks can have minor textual boundary discontinuity; disabling previous-text
  conditioning reduces repetition loops and makes cache units deterministic. Later semantic work
  consumes timestamps and can reconcile prose without modifying raw evidence.
- Model cache discovery differs by backend, but missing local state is safe and explicit.
- NumPy becomes a direct base dependency because synchronization is part of the base CLI surface.
- Sync detects and reports clock drift but does not resample media in M3.
- Very quiet, repetitive, or unrelated camera audio can be uncertain. This is an expected guarded
  outcome, not a successful automatic sync.
