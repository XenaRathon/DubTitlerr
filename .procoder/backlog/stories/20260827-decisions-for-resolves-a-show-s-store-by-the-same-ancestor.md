# `decisions_for()` resolves a show's store by the same ancestor walk `glossary_for()` uses, and returns an empty store when `DECISIONS_DIR` does not exist.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 1. The store must be found from an episode path the same way its glossary is, or the two artifacts
disagree about what show they belong to. Done means the same ancestor walk `repair.glossary_for()`
uses, and an absent `DECISIONS_DIR` yields an empty store rather than an error -- absence of decisions
is the pre-existing state and must stay safe.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `decisions_for()` resolves a show's store by the same ancestor walk `glossary_for()` uses, and returns an empty store when `DECISIONS_DIR` does not exist.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
