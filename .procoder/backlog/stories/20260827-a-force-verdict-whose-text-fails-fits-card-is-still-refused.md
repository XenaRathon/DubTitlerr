# A `force` verdict whose text fails `fits_card` is still refused, and records an unresolved entry naming the refusal -- force does not override card timing.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 4. `force` overrides the JUDGEMENT gates -- length ratio, ref-borrow cap, `invents_name`, the
phonetic guard. It does not override physics. Done means a forced repair that cannot be rendered is
still refused and recorded, on the same terms as a `correct` that does not fit.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] A `force` verdict whose text fails `fits_card` is still refused, and records an unresolved entry naming the refusal -- force does not override card timing.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
