# An empty store produces byte-identical output to the code before this change, AND the lookup is observably called -- a `return` short-circuiting before the consult would otherwise satisfy the byte-identical half on its own.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 4. Shipping the consult must not change production behaviour, which is what lets this land with no
`TEXT_VERSION` bump per ADR 0001. Done means output matches the pre-change code with an empty store
AND the lookup is observably reached -- byte-identity alone is satisfied by a `return` that never
gets there.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] An empty store produces byte-identical output to the code before this change, AND the lookup is observably called -- a `return` short-circuiting before the consult would otherwise satisfy the byte-identical half on its own.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
