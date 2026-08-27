# An empty store produces byte-identical output to the code before this change, AND the lookup is observably called -- a `return` short-circuiting before the consult would otherwise satisfy the byte-identical half on its own.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 004-task-4-consult-the-decision-store-inside-repair-reject

## Description

Task 4. Shipping the consult must not change production behaviour, which is what lets this land with no
`TEXT_VERSION` bump per ADR 0001. Done means output matches the pre-change code with an empty store
AND the lookup is observably reached -- byte-identity alone is satisfied by a `return` that never
gets there.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] An empty store produces byte-identical output to the code before this change, AND the lookup is observably called -- a `return` short-circuiting before the consult would otherwise satisfy the byte-identical half on its own.

## Evidence

- `pytest -k empty_store` -> `test_an_empty_store_is_byte_identical_and_still_reaches_the_lookup`
  passes. Asserts the exact SRT bytes literally, plus one `repair_applied` entry -- pre-change
  behaviour, written out rather than computed from a second run.
- The "observably called" half drove a real code change: the first implementation short-circuited
  on `if DECISIONS_APPLY and store`, so with an empty store `lookup` was never reached. RED on the
  spy (`seen == []`) removed the `and store`, so the consult cannot become dead code on exactly the
  installs where it is least exercised.
