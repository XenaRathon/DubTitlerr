# `lookup()` on a store built from a recorded verdict returns that verdict for the same pair and `None` for a pair differing only in `proposed`.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 1. The store is keyed on the `(orig, proposed)` pair, never on episode or card index -- position
does not survive a `TEXT_VERSION` bump and means nothing in another library. Done means a stored
verdict is found for its own pair and is NOT found when the model proposes something different,
so a stale verdict can never be misapplied to a new proposal.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `lookup()` on a store built from a recorded verdict returns that verdict for the same pair and `None` for a pair differing only in `proposed`.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
