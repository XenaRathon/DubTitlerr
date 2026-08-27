# With a `correct` verdict stored, the card carries the human's text.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 004-task-4-consult-the-decision-store-inside-repair-reject

## Description

Task 4. The owner's most common action on the 45-line read was neither approve nor reject but rewrite
-- five of the 41 he accepted carried hand-corrections. Done means a stored `correct` verdict puts
the human's wording on the card.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] With a `correct` verdict stored, the card carries the human's text.

## Evidence

- `pytest -k correct_verdict` -> `test_a_correct_verdict_applies_the_humans_text` passes; RED before
  the branch existed (the model's `I saw Spandam` shipped instead of the human's text).
- The human's text is deliberately one `accept_repair` REFUSES (24 chars against 13 is a 1.85 ratio,
  outside the 0.6-1.5 band) while still rendering in the 2.0s card at 12 cps. The first draft used a
  text the gate would have accepted anyway, which could not distinguish "the branch bypasses the
  gate" from "the branch exists" -- strengthened before GREEN.
