# A decision promoted as a term writes `hard_fixes[variant] = canonical` into the show glossary, the decision records what it promoted, and a curated entry already present is not overwritten.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 002-task-1-and-2-the-decision-store-and-glossary-promotion

## Description

Task 2. When a verdict's lesson is a TERM rather than a line -- `Samadai -> Samurai` -- it belongs in
the glossary, where it applies show-wide through `glossary.correct()` and ships in an artifact that
is already committed. Done means the promotion writes `hard_fixes`, the decision records what it
promoted, and a curated entry already present is never overwritten: a human's glossary outranks a
promotion.

`promoted` is set by the human at review time. No rule auto-classifies -- auto-classification on a
single-token difference would promote `factory -> needle` show-wide, the exact regression the store
exists to catch.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] A decision promoted as a term writes `hard_fixes[variant] = canonical` into the show glossary, the decision records what it promoted, and a curated entry already present is not overwritten.

## Evidence

RED: `python3 -m pytest tests/test_decisions.py -q` —
`AttributeError: module 'decisions' has no attribute 'promote'` x4, exit 1.

GREEN: after implementing `promote()` — exit 0, 14 passed.

Guards mirror this repo's existing glossary write paths rather than inventing new ones
(located via a read-only sweep of `glossary_acquire.py`, `glossary_verify.py`,
`mine_glossary.py`, `glossary.py`):

- deep-copy before mutation, the convention stated at `glossary_acquire.py:660`
- `run == "review"` provenance, the marker `glossary_acquire.revert` refuses to delete (R4,
  `glossary_acquire.py:730`), so an automated sweep cannot undo a human's call
- an existing entry is never overwritten, compared CASE-INSENSITIVELY because
  `glossary.load_dict` lowercases every `hard_fixes` key at load (`glossary.py:70-72`) —
  `samadai` and `Samadai` are one fix downstream
- `applied` reports what actually landed, not what was asked for

The fourth clause — the decision recording what it promoted — also passed immediately, so
it was mutation-checked: changing `if promoted:` to `if promoted is not None:` in
`record()` made a REFUSED promotion record `promoted: {}`, and the test caught it
(`MUTATED exit=1`). Restored, 15 passed.

Suite: 1263 passed, 0 failed. Gate: 2 clean, 0 blocking. `procoder lint --types`: 0 findings.
