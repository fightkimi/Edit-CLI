# ADR 0001: Runtime, media tools, and local transcription

- Status: accepted for M0/M1
- Date: 2026-09-03

## Context

The development host is an Apple M5 Pro MacBook Pro with 48 GB RAM and macOS 26.6.2 on arm64. `/usr/bin/python3` is Python 3.9.6, while the Codex workspace runtime provides Python 3.12.13. Homebrew provides `uv` 0.11.19 and FFmpeg/FFprobe 8.1.2.

FFmpeg advertises VideoToolbox, libx264, libx265, ProRes, and AAC. A 12-second H.264/AAC encode succeeded with libx264. VideoToolbox failed in the Codex sandbox with error `-12908` but succeeded when executed on the host, so capability enumeration alone is insufficient.

No Whisper implementation or model cache was present before M0. The reference project uses Faster-Whisper with CUDA, which is not an Apple GPU path. Apple MLX provides a native Apple Silicon implementation with word timestamps. A real MLX Whisper run succeeded on the host, while the same installed module could not access Metal inside the Codex sandbox. A cold import in a fresh environment took 34.59 seconds, so a 15-second probe produced a false negative.

## Decision

- Support Python 3.11+ and perform M0/M1 verification with Python 3.12.
- Use `uv` for environments, locking, building, and test execution.
- Use FFmpeg/FFprobe through argument-array subprocess adapters.
- Treat libx264 as the portable H.264 fallback. Enable VideoToolbox only after a real encoding probe succeeds in the execution environment.
- Make `mlx-whisper` the preferred Apple Silicon transcription adapter.
- Keep Faster-Whisper as the NVIDIA CUDA and portable CPU adapter, and a deterministic mock adapter for tests.
- Probe transcription by importing the selected backend in the current execution environment; package discovery alone does not prove it is usable. Allow up to 60 seconds for a first MLX import on this host.
- Never download a model implicitly. A remote model identifier is unresolved until the user explicitly authorizes download; a local path must exist before use.

## Consequences

- `doctor` distinguishes installed, advertised, and actually usable capabilities.
- A Codex sandbox may report VideoToolbox as unavailable even though a normal terminal can use it.
- MLX transcription from Codex requires an execution context with Metal access; `doctor` must fail clearly when the sandbox blocks it.
- The base package stays lightweight; transcription implementations are optional extras.
- Python 3.9 cannot install or run this project.

## Evidence

- Local M0 commands and outputs are summarized in `docs/tests/m0-environment-validation.md`.
- MLX Whisper usage and word timestamps: https://github.com/ml-explore/mlx-examples/tree/main/whisper
- Published MLX Whisper package: https://pypi.org/project/mlx-whisper/
