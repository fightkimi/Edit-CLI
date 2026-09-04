# Privacy modes

Read the project's `privacy_mode` before opening content-bearing artifacts.

## strict

- Read paths, stable IDs, hashes, durations, stream metadata, status, and aggregate statistics.
- Do not read full transcripts, thumbnails, contact sheets, proxies, or QC images.
- Ask the user for explicit ranges or rely on a cut-list they provide.

## assisted

- Read only the transcript ranges needed for the current editing decision.
- Read selected thumbnails, contact sheets, and QC evidence when they materially help.
- Keep original video local to the CLI; do not treat it as direct model input.
- Tell the user when content-bearing text or images will enter the current Codex session context.

Neither mode authorizes uploads, network transcription, or model downloads. Those require a separate explicit decision.
