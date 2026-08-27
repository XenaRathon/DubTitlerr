# An episode with no `conf.json` is refused by name, and its stamp is untouched.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 5. `conf.json` is the source the srt is rebuilt from; without it there is nothing to apply verdicts
to. Done means the episode is refused BY NAME and its stamp is left alone -- a half-applied episode,
stamp cleared but text unchanged, is the state to avoid.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] An episode with no `conf.json` is refused by name, and its stamp is untouched.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
