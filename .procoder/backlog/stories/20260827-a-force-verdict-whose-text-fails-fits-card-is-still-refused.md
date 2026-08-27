# A `force` verdict whose text fails `fits_card` is still refused, and records an unresolved entry naming the refusal -- force does not override card timing.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 004-task-4-consult-the-decision-store-inside-repair-reject

## Description

Task 4. `force` overrides the JUDGEMENT gates -- length ratio, ref-borrow cap, `invents_name`, the
phonetic guard. It does not override physics. Done means a forced repair that cannot be rendered is
still refused and recorded, on the same terms as a `correct` that does not fit.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] A `force` verdict whose text fails `fits_card` is still refused, and records an unresolved entry naming the refusal -- force does not override card timing.

## Evidence

- `pytest -k cannot_be_rendered` -> `test_a_forced_repair_that_cannot_be_rendered_is_still_refused`
  passes. RED showed `force` widening the card -- the C1 violation this story exists to prevent.
- `force` overrules `accept_repair` (judgement) and never `fits_card` (timing). The refusal is
  recorded as `decision_unfittable` so the forcer is told rather than silently ignored.
