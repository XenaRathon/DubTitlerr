# Bumping `TEXT_VERSION` alone leaves `stale_tiers()` free of `"transcribe"`; bumping `TRANSCRIBE_VERSION` marks both. Both constants' docstrings name the decoder-affecting settings that require a transcribe bump.

Status: open
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 1 of `.procoder/plans/v5-two-tier-idempotency.md`.

The pipeline needs to decide which tier is behind without anyone remembering to set a flag. Done means a `TEXT_VERSION` bump marks only the text tier and a `TRANSCRIBE_VERSION` bump marks both, and both constants carry the ported bump manual naming the decoder-affecting settings — model, beam size, compute type, whisper thresholds, initial_prompt — because no mechanical signal detects a change to those.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] Bumping `TEXT_VERSION` alone leaves `stale_tiers()` free of `"transcribe"`; bumping `TRANSCRIBE_VERSION` marks both. Both constants' docstrings name the decoder-affecting settings that require a transcribe bump.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

