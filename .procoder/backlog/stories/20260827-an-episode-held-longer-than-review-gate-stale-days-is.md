# An episode held longer than `REVIEW_GATE_STALE_DAYS` is reported loudly and counted in the sweep summary, and is still NOT muxed -- the alert must not become a release.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 6. The gate's real failure is not holding -- it is holding SILENTLY. Two weeks away and the library
falls behind with nothing said. Done means a stale hold is reported loudly and counted in the sweep
summary, and the episode is STILL held.

The alert must never become a release: auto-releasing unreviewed repairs is the failure this whole
epic exists to prevent.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] An episode held longer than `REVIEW_GATE_STALE_DAYS` is reported loudly and counted in the sweep summary, and is still NOT muxed -- the alert must not become a release.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
