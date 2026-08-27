# A `correct` verdict whose text fails `fits_card` leaves the ASR text in place and records an unresolved entry naming the refusal.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 4. Card timing is immutable in repair (C1), so a human's wording that cannot be rendered inside
the card's duration cannot win. Done means the ASR text stays AND an unresolved entry records the
refusal -- the human is told their correction was refused rather than watching it vanish.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] A `correct` verdict whose text fails `fits_card` leaves the ASR text in place and records an unresolved entry naming the refusal.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
