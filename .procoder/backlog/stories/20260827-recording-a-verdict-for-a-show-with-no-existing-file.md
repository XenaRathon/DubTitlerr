# Recording a verdict for a show with no existing file creates the file; a second verdict appends without losing the first; a crash-simulating partial write leaves the previous file intact.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 002-task-1-and-2-the-decision-store-and-glossary-promotion

## Description

Task 1. A show's store must appear on first use the way `mine_glossary.py` creates a glossary from
nothing, and must never lose an earlier verdict to a later one. Done means create-on-first-write,
append without loss, and a torn write leaves the previous file intact -- atomic `mkstemp` +
`os.replace`, mirroring `unresolved._rewrite`.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] Recording a verdict for a show with no existing file creates the file; a second verdict appends without losing the first; a crash-simulating partial write leaves the previous file intact.

## Evidence

RED: `python3 -m pytest tests/test_decisions.py -q` —
`AttributeError: module 'decisions' has no attribute 'save'` and `...no attribute 'load'`,
exit 1.

GREEN: after implementing `load()`/`save()` — exit 0, 6 passed. Create-on-first-write,
append without loss (`["reject", "accept"]` round-tripped in order), and a corrupt file
loading as `{}` rather than a partial parse.

The third clause — a torn write leaving the previous file intact — PASSED IMMEDIATELY when
first written, because the atomic implementation predated its test. Rather than accept an
unproven claim, the production code was mutated to write in place and the test re-run:

    MUTATED exit=1
    E  assert '' == '{\n  "decisi...ersion": 1\n}'

The in-place write truncated a good store to empty, which is exactly the failure the test
guards. Restoring `mkstemp` + `os.replace` returned the suite to green (7 passed).
