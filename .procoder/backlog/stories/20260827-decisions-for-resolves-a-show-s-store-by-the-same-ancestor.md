# `decisions_for()` resolves a show's store by the same ancestor walk `glossary_for()` uses, and returns an empty store when `DECISIONS_DIR` does not exist.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 002-task-1-and-2-the-decision-store-and-glossary-promotion

## Description

Task 1. The store must be found from an episode path the same way its glossary is, or the two artifacts
disagree about what show they belong to. Done means the same ancestor walk `repair.glossary_for()`
uses, and an absent `DECISIONS_DIR` yields an empty store rather than an error -- absence of decisions
is the pre-existing state and must stay safe.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `decisions_for()` resolves a show's store by the same ancestor walk `glossary_for()` uses, and returns an empty store when `DECISIONS_DIR` does not exist.

## Evidence

RED: `python3 -m pytest tests/test_decisions.py -q` —
`AttributeError: module 'decisions' has no attribute 'decisions_for'` x3, exit 1.

GREEN: after implementing `show_for()`/`decisions_for()` — exit 0, 10 passed.

Three behaviours: the walk resolves a show from an episode nested two levels below it, an
absent `DECISIONS_DIR` yields `({}, show)` rather than raising, and — the one that matters —
show identity comes from the show DIRECTORY, not the glossary's `show` key.

That third test exists because the two disagree in the real library:
`glossaries/Cowboy Bebop (1998) {tvdb-76885}.json` carries `show == "Cowboy Bebop"`. Keyed
on the display name, a show's decision store and its glossary would be two differently
named artifacts for one show, and every lookup would miss without ever erroring.
