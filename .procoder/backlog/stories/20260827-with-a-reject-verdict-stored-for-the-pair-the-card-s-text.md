# With a `reject` verdict stored for the pair, the card's text equals the POST-`glossary.correct()` ASR text and no `repair_applied` entry is written -- pinning the consult between `glossary.correct()` (`repair.py:634`) and `accept_repair` (`repair.py:649`), so a consult placed before the correction fails this.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 004-task-4-consult-the-decision-store-inside-repair-reject

## Description

Task 4. The consult must sit between `glossary.correct()` and `accept_repair`, and this story is what
pins it there. Done means a stored rejection leaves the card showing the POST-correction ASR text
and writes no queue entry.

Asserting post-correction text is deliberate: a consult placed before the correction would leave
different text and fail, which is the only cheap way to catch a mis-placed consult point.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] With a `reject` verdict stored for the pair, the card's text equals the POST-`glossary.correct()` ASR text and no `repair_applied` entry is written -- pinning the consult between `glossary.correct()` (`repair.py:634`) and `accept_repair` (`repair.py:649`), so a consult placed before the correction fails this.

## Evidence

- `pytest -k reject_verdict` -> `test_a_reject_verdict_keeps_the_post_correction_asr_text` passes.
  RED first: the SRT read `I saw Spandam` (the repair had shipped). GREEN after the consult landed.
- Consult position pinned by mutation, in the direction that was missed last sprint: capturing the
  raw LLM output and keying the lookup on it (i.e. a consult placed ABOVE `glossary.correct()`)
  fails 7 tests, this one among them.
- Asserted on the rebuilt SRT, not `conf.json`: repair.py mutates conf rows in memory and never
  writes that file back, so the conf.json form of this assertion passes whether or not the repair
  was applied. That trap was in the first draft of this test and is now commented in place.
