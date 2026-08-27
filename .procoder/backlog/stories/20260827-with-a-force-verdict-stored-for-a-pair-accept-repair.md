# With a `force` verdict stored for a pair `accept_repair` refuses, the repair is applied; the same pair with no verdict is still refused.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 004-task-4-consult-the-decision-store-inside-repair-reject

## Description

Task 4. The gate errs in both directions, and only one of them is currently recoverable: it admits
meaning-destroying repairs, and it refuses proposals nobody has ever judged. Done means a human can
admit a repair `accept_repair` refused, and that the same pair without a verdict is still refused.

`force` is recorded distinctly from `accept` so the count becomes the evidence for the deferred
`accept_repair` tightening.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] With a `force` verdict stored for a pair `accept_repair` refuses, the repair is applied; the same pair with no verdict is still refused.

## Evidence

- `pytest -k force_verdict` -> `test_a_force_verdict_admits_a_repair_the_gate_refused` passes.
- Both halves in one test: the same 30-char proposal (2.3 length ratio) is admitted with `force`
  stored and refused with an empty store. Without the control half the test would pass on a
  proposal the gate was going to accept anyway.
