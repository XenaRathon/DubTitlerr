# `record()` refuses an empty `orig` or `proposed`, and converts a `correct` whose text equals the original into a `reject`.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 1. Two malformed verdicts would poison lookups: an empty key matches far too broadly, and a
`correct` whose text equals the original is semantically a rejection stored under the wrong name.
Done means both are refused or normalised at record time, so lookup has exactly one meaning per
outcome.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `record()` refuses an empty `orig` or `proposed`, and converts a `correct` whose text equals the original into a `reject`.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
