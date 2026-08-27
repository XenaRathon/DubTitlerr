# A `correct` verdict whose text fails `fits_card` leaves the ASR text in place and records an unresolved entry naming the refusal.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 004-task-4-consult-the-decision-store-inside-repair-reject

## Description

Task 4. Card timing is immutable in repair (C1), so a human's wording that cannot be rendered inside
the card's duration cannot win. Done means the ASR text stays AND an unresolved entry records the
refusal -- the human is told their correction was refused rather than watching it vanish.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] A `correct` verdict whose text fails `fits_card` leaves the ASR text in place and records an unresolved entry naming the refusal.

## Evidence

- `pytest -k does_not_fit` -> `test_a_correct_that_does_not_fit_the_card_is_refused_and_recorded`
  passes. RED showed the 57-char verdict shipped across two wrapped lines.
- Asserts the ASR text stands AND a `decision_unfittable` entry is written with the refused text.
- Mutation: replacing the fits_card guard with `if False:` fails this test and the force twin.
- Assertion tightened during RED: `too_long not in srt` passed unconditionally because
  `wrap_balance` always inserts a newline, so the full string never appears verbatim even when it
  HAS shipped. Now asserts on a token that survives wrapping.
