# `record()` refuses an empty `orig` or `proposed`, and converts a `correct` whose text equals the original into a `reject`.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 002-task-1-and-2-the-decision-store-and-glossary-promotion

## Description

Task 1. Two malformed verdicts would poison lookups: an empty key matches far too broadly, and a
`correct` whose text equals the original is semantically a rejection stored under the wrong name.
Done means both are refused or normalised at record time, so lookup has exactly one meaning per
outcome.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `record()` refuses an empty `orig` or `proposed`, and converts a `correct` whose text equals the original into a `reject`.

## Evidence

RED: `python3 -m pytest tests/test_decisions.py -q` — two failures, both on the
assertion meant rather than on an error:

    E  assert [{'orig': '', 'proposed': "it's a vivi card?", ...}] == []
    E  AssertionError: assert 'correct' == 'reject'

GREEN: after adding both guards to `record()` — exit 0, 4 passed.

An empty side normalises to `""` and would match every card the LLM returned nothing for.
A `correct` whose text restores the original is the same decision as a rejection reached
by a different route; stored as `correct` the [S-4] consult would have to handle two
spellings of one outcome, and one of them would look like a repair.
