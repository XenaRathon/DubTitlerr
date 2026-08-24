# On an episode where `_clamp_to_segments` actually moved at least one word and at least one segment carries a non-zero `no_speech_prob`, a cached re-run from `words.json` produces cards **identical to the original run's**, including each card's `no_speech_prob` — asserted against the original production run, not against a second cache-shaped run.

Status: open
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 2 of `.procoder/plans/v5-two-tier-idempotency.md`.

This is the criterion the external review flagged as the one most able to pass while the feature is broken. Per-segment `no_speech_prob` and the clamp bounds live only on segment dicts and cannot be recovered from the word list, so a cached replay that omits them silently produces different cards and zeroed confidences. Done means the replay is compared against the ORIGINAL production run on an episode where the transforms demonstrably fired — not against a second cache-shaped run, which would validate the bug.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] On an episode where `_clamp_to_segments` actually moved at least one word and at least one segment carries a non-zero `no_speech_prob`, a cached re-run from `words.json` produces cards **identical to the original run's**, including each card's `no_speech_prob` — asserted against the original production run, not against a second cache-shaped run.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

