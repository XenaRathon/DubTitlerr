# `unresolved.pending()` filtered to the primary stages returns exactly the accepted repairs plus the guard rejections, and the unfiltered walk additionally returns `no_reference`, `llm_empty` and the punctuation stages.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 003-task-3-queue-accepted-repairs-for-human-confirmation

## Description

Task 3. The owner reviews ~25 judgement-worthy lines per episode but the queue holds ~86 once
`no_reference` and `llm_empty` are counted. Done means the default view is the actionable subset and
the full walk is one flag away.

The test asserts the ABSENCE of non-primary reasons. `unresolved.pending()` applies no stage filter
of its own, so a filter that returns everything would pass a presence-only assertion.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `unresolved.pending()` filtered to the primary stages returns exactly the accepted repairs plus the guard rejections, and the unfiltered walk additionally returns `no_reference`, `llm_empty` and the punctuation stages.

## Evidence

RED: `TypeError: pending() got an unexpected keyword argument 'primary_only'`, exit 1.

GREEN: after adding `PRIMARY` and `pending(stem, primary_only=False)` — exit 0.

Keyed on `(stage, reason)` PAIRS, not reason alone. Caught while writing the filter:
`REASONS["punctuation"]` also contains `rejected_guard`, so reason-only keying would sweep
punctuation entries into the repair queue. The test was tightened before implementing to
record a `punctuation`/`rejected_guard` entry and assert its exclusion.

Asserted on ABSENCE — `no_reference` and `llm_empty` must not appear, and the unfiltered
walk must still return all 7 seeded entries. `pending()` applies no stage filter of its own
(unresolved.py), so a filter returning everything would satisfy any presence-only test.

The adversarial review corrected the JUSTIFICATION, which was factually wrong: the comment
claimed punctuation rejections could not be judged by reading two texts, but
`punctuation.py:290-296` records `original_text` and `proposed_text` exactly as the repair
rejection does. Verified against that call site. The exclusion is scope ([S-1] covers repair
decisions), not judgeability — the comment and the test now say so, and whether to widen
PRIMARY is recorded as an open question for the owner rather than a settled design point.
