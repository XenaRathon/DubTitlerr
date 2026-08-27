# With a show listed in `REVIEW_GATE_SHOWS`, `mux.py` skips an episode holding a pending `repair_applied` entry and muxes it once that entry is resolved; with the list empty, both episodes mux.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 6. On a show where every card is unanchored, a regression that reaches the library is permanent, so
the owner may want review BEFORE mux rather than after. Done means a listed show holds an episode
while it has a pending entry and muxes once resolved, and an unlisted show behaves exactly as today.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] With a show listed in `REVIEW_GATE_SHOWS`, `mux.py` skips an episode holding a pending `repair_applied` entry and muxes it once that entry is resolved; with the list empty, both episodes mux.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
