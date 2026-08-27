# With an accept verdict stored for the pair, the repair is applied and NO repair_applied entry is queued -- a line the human has already approved must not come back to the reviewer on every re-run, which is the re-run amplification the spec's Edge cases record

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 004-task-4-consult-the-decision-store-inside-repair-reject

## Description

Found while implementing Task 4, not present in the plan. Spec `[S-4]` requires four
verdicts; the plan wrote RED steps for three. `accept` is the one it dropped, and it is the
verdict that closes the re-run amplification the spec's Edge cases already record:

> Between shipping [S-1] and [S-4] a re-run can show a reviewer the same line twice --
> noisy, never wrong. ... once [S-4] consults the store, a settled line is suppressed.

Suppression is not incidental to `accept` -- it is the whole point of the verdict. Applying
the repair is what already happens with no verdict at all, so a branch that only applies is
indistinguishable from no branch. The queue entry is the observable difference.

The same suppression follows for `correct` and `force`: all four verdicts mean a human has
ruled, and none should re-queue. `reject` already suppresses by never reaching the queue
write. This story pins the rule for the three that DO apply a repair.

## Acceptance criteria

- [x] With an `accept` verdict stored for the pair, the repair is applied to the shipped SRT
      and no `repair_applied` entry is written for that card.
- [x] With no verdict stored, the same episode DOES write a `repair_applied` entry --
      asserted in the same test or its neighbour, because "applied" alone is what happens
      without any branch and would pass on its own.
- [x] `correct` and `force` verdicts likewise write no `repair_applied` entry.
- [x] `procoder test` green, `procoder check` 0 blocking.

## Evidence

- `pytest -k re_queue` -> `test_an_accept_verdict_applies_the_repair_and_stops_re_queueing_it` and
  `test_correct_and_force_verdicts_are_not_re_queued_either` both pass. RED on the suppression
  assertion (`assert queued == []` saw one entry).
- The control half is what gives it meaning: with no verdict the same episode DOES queue the line
  (`len(control) == 1`). Applying alone is what already happens with no branch at all, so the
  suppressed queue entry is the only observable difference a verdict makes.
- Mutation: `if not ruling:` -> `if True:` fails both tests.
- STORY ADDED MID-SPRINT. Spec [S-4] names four verdicts; the plan wrote RED steps for three and
  omitted `accept`. Found while implementing, not inherited from the plan.
- The adversarial review then found `accept` was still being re-judged by `accept_repair`
  (`APPLYING` originally held only `correct`/`force`), so gate drift could silently revert an
  approved line AND re-queue it as a fresh `rejected_guard`. Reproduced by tightening
  `LEN_RATIO_MAX` to 0.9 after the verdict; fixed by putting `accept` in `APPLYING`; pinned by
  `test_an_accept_verdict_survives_later_drift_in_the_gate` and a mutation that removes it.
- Suite 1285 passed, `procoder check` 0 blocking, `lint --types` 0 findings.
