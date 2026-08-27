# `review_apply.py --show` invalidates only the episodes whose text actually changes, leaving the rest of the show's stamps valid.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 5. A downstream user pulling a store for a show they already generated has valid stamps everywhere
and nothing to re-trigger; a sweep is the mechanism. Done means only the episodes whose text actually
changes lose their stamp, so the re-mux is targeted rather than a whole-show re-run.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `review_apply.py --show` invalidates only the episodes whose text actually changes, leaving the rest of the show's stamps valid.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
