# Opening `MAX_CONCURRENT + 1` simultaneous connections results in the extra connection being closed by the server rather than queued indefinitely.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: -

## Description

Scope S-15 of `.procoder/specs/v0-2-0-hardening.md`: Add a real-socket HTTP test: the server started on port 0 in a thread, not the handler called directly.

Delivered by Task 15 of `.procoder/plans/v0-2-0-hardening.md` (sprint 013); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] Opening `MAX_CONCURRENT + 1` simultaneous connections results in the extra connection being closed by the server rather than queued indefinitely.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
