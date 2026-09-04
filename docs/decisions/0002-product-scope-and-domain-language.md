# ADR 0002: Speech-led creator-video scope and domain language

- Status: accepted for V1 architecture
- Date: 2026-09-03

## Context

The original PRD centers on fixed-camera interviews and documentaries. The current product direction also includes other creator formats such as talking-head explainers, tutorials, reviews, and vlogs. Expanding directly to an arbitrary film or television editor would invalidate V1's bounded workflow and test strategy.

## Decision

- Keep the distribution and command name `interview-edit` for V1, following the approved default.
- Define V1 as speech-led creator-video editing, not documentary-only and not a general nonlinear editor.
- Use generic domain names such as `MediaAsset`, `TimelineItem`, `primary`, and `content_role` in new contracts.
- Support `primary`, `broll`, `still`, `title`, and `transition` item kinds in the draft cut-list. `content_role` describes interview, talking-head, tutorial, review, vlog, screen capture, or another editorial role without changing render semantics.
- Keep the initial deterministic workflow optimized for one primary spoken track with optional synchronized cameras, overlays, subtitles, and B-roll.

## Consequences

- The architecture can serve several common self-media formats without pretending to be a universal editor.
- The original reference project's `interview` item maps to the new `primary` kind during a future importer or migration.
- Renaming the public CLI remains a pre-Beta product decision, not an M1 blocker.
