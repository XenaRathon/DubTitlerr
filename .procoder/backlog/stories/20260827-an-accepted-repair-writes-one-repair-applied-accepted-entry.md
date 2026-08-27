# An accepted repair writes one `repair_applied`/`accepted` entry to `<stem>.dubtitles.unresolved.jsonl` whose `original_text` equals the card's pre-repair text and whose `proposed_text` equals the text actually applied -- asserted on the FIELDS, not only on the count, which a pair of empty strings would satisfy. The entry count also equals the summary's `repaired` count for that episode.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 003-task-3-queue-accepted-repairs-for-human-confirmation

## Description

Task 3. The reviewer cannot judge what they cannot see. `unresolved.py` already queues what the
pipeline could NOT settle; an accepted repair was settled -- by a gate that does not check meaning --
and so is never queued at all. Done means every admitted repair lands in the episode's queue
carrying the card's pre-repair text and the text actually applied.

Asserted on the FIELDS, not the count: two empty strings would satisfy a count-only test, and an
entry stripped of the evidence it escalated with cannot be reviewed, which is the whole point.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] An accepted repair writes one `repair_applied`/`accepted` entry to `<stem>.dubtitles.unresolved.jsonl` whose `original_text` equals the card's pre-repair text and whose `proposed_text` equals the text actually applied -- asserted on the FIELDS, not only on the count, which a pair of empty strings would satisfy. The entry count also equals the summary's `repaired` count for that episode.

## Evidence

RED: `python3 -m pytest tests/test_unresolved.py tests/test_repair.py -q` before the stage
existed — `KeyError: 'repair_applied'` and `assert 0 == 1 where 0 = len([])`, exit 1.

GREEN: after adding the `repair_applied`/`accepted` stage to `REASONS`, its `_EVIDENCE`
template, and one `unresolved.record(...)` call in `repair.process()` — exit 0.
Suite 1272 passed, gate 0 blocking, `lint --types` 0 findings.

Asserted on the FIELDS (`original_text` == the card's pre-repair text, `proposed_text` ==
the text applied) and on the count agreeing with `repair-summary.json`'s `repaired`.

PLACEMENT was the whole difficulty, and three mutations pin it:

- moved BELOW `c["text"] = new` (repair.py:683) -> `MUTATED exit=1`. `original_text` becomes
  the repaired text and every entry compares a line against itself.
- moved into the REJECT branch -> `MUTATED exit=1`. A refused repair would appear in the
  accepted queue, telling the reviewer a line shipped that never did.
- moved ABOVE the secondary-model block (repair.py:667-680) -> `MUTATED exit=1`, but ONLY
  after a test was added for it. This gap was found by the adversarial review, which ran the
  probe itself and reported the whole suite still green: the queue recorded `I saw Spandam`,
  the discarded first pass, for a card that shipped `I saw Spandam there`. A reviewer would
  have been approving text the viewer never saw, on exactly the name-change-then-re-verified
  case the two-pass gate exists for. `test_the_queue_records_the_secondary_models_text_not_
the_first_passes` now holds it, and cross-checks the queue against the same run's CSV.
