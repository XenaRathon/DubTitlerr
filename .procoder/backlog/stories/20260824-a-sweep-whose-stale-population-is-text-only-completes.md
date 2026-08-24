# A sweep whose stale population is text-only completes without loading `WhisperModel` — asserted by the absence of the load, not by timing.

Status: open
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 7 of `.procoder/plans/v5-two-tier-idempotency.md`.

`main()` loads WhisperModel whenever there is anything to do, so a text-only sweep pays a ~40 second GPU model load to perform zero transcription — the cheap tier quietly is not cheap. Done means the todo list is partitioned and the model is constructed only when there is transcription work, asserted by making the constructor raise rather than by measuring elapsed time.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] A sweep whose stale population is text-only completes without loading `WhisperModel` — asserted by the absence of the load, not by timing.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

