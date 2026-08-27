# `lookup()` on a store built from a recorded verdict returns that verdict for the same pair and `None` for a pair differing only in `proposed`.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 002-task-1-and-2-the-decision-store-and-glossary-promotion

## Description

Task 1. The store is keyed on the `(orig, proposed)` pair, never on episode or card index -- position
does not survive a `TEXT_VERSION` bump and means nothing in another library. Done means a stored
verdict is found for its own pair and is NOT found when the model proposes something different,
so a stale verdict can never be misapplied to a new proposal.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `lookup()` on a store built from a recorded verdict returns that verdict for the same pair and `None` for a pair differing only in `proposed`.

## Evidence

RED: `python3 -m pytest tests/test_decisions.py -q` —
`AttributeError: module 'decisions' has no attribute 'record'`, exit 1.

GREEN: after implementing `record()` and `lookup()` — exit 0, 2 passed.

Keyed on BOTH sides. Test data is the real `It's a VIVRA card?` -> `It's a Vivi card?`
rejection: looking up that pair returns `reject`, and looking up the same `orig` with
`It's a Vivre card?` returns `None`. Keying on `orig` alone would have let one rejection
suppress the proposal that actually fixes the line.
