# ADR 0008: State-aware Skill orchestration with evaluated routing

- Status: accepted
- Date: 2026-09-04

## Context

M0–M5 provide a deterministic CLI, but the initial project Skill mostly lists the safe sequence. M6
must route natural-language requests across incomplete, valid, failed, and approval-pending project
states; support multiple speech-led creator formats; and remain small enough to activate reliably.
Public Skill implementations show useful phase gates and review packets, but some also duplicate
media execution, embed mutable platform details, or grow into very large capability catalogs.

## Decision

- Keep the CLI as the only execution engine and current project evidence as operational truth. The
  Skill may author or revise versioned cut-lists, but it must not generate replacement FFmpeg or
  media-processing scripts.
- Make `SKILL.md` a concise state-aware router. Move command details, editorial judgment, privacy,
  QC/approval, and recovery guidance into focused references loaded only when relevant.
- Resolve routes from both user intent and fresh project state. Read the current config and actual
  CLI help before asserting that a command, option, or state transition exists.
- Add format-aware editorial guidance for interviews, talking heads, tutorials, reviews, and vlogs.
  These are decision heuristics, not automatic engagement or quality claims.
- Treat preview approval, master approval, and freeze approval as distinct object-bound decisions.
  No prior generic permission permanently authorizes a later master or version freeze.
- Maintain a natural-language eval corpus with positive workflows and near-miss exclusions. Static
  checks validate its structure and referenced commands; model behavior requires separate observed
  runs and must not be inferred from static validation alone.
- Keep installation and Beta evidence in repository documentation, not inside the Skill entrypoint.
- Use the installed Codex `quick_validate.py` as the local compatibility gate. Although the public
  Agent Skills specification permits a top-level `compatibility` field, the current bundled
  validator rejects it, so runtime requirements live in the `SKILL.md` body until the validator
  supports that field.

## Consequences

- The Skill gains deeper editorial guidance without inflating every invocation's context.
- State transitions and stop conditions become reviewable and testable against the CLI contract.
- Cross-directory CLI use remains independent from Codex, while repository Skill discovery remains
  intentionally scoped to the checkout.
- Future CLI capabilities must update the command reference and affected eval scenarios together.
- Model-routing quality can improve iteratively without weakening deterministic validation or user
  approval boundaries.
