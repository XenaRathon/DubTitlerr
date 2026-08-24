# A glossary edit that changes only `hard_fixes` leaves `initial_prompt` byte-identical, marks **zero** episodes transcription-stale, and re-applies the correction to conf and srt through the card-text path. An edit that changes `initial_prompt` marks the episode transcription-stale. The count of newly-flagged episodes is asserted, not just the flag.

Status: open
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 3 of `.procoder/plans/v5-two-tier-idempotency.md`.

`mine_glossary.py` appends hard_fixes on every sweep of a watched show, and those never reach `initial_prompt`. Hashing the glossary file would therefore re-queue an entire show for the GPU on edits that changed nothing about the decoder input — converting this spec's own motivating example back into the cost it exists to remove. Done means classification compares the stored prompt STRING, and the test asserts how many episodes were newly flagged, not merely that a flag moved.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] A glossary edit that changes only `hard_fixes` leaves `initial_prompt` byte-identical, marks **zero** episodes transcription-stale, and re-applies the correction to conf and srt through the card-text path. An edit that changes `initial_prompt` marks the episode transcription-stale. The count of newly-flagged episodes is asserted, not just the flag.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

