# With a `force` verdict stored for a pair `accept_repair` refuses, the repair is applied; the same pair with no verdict is still refused.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 4. The gate errs in both directions, and only one of them is currently recoverable: it admits
meaning-destroying repairs, and it refuses proposals nobody has ever judged. Done means a human can
admit a repair `accept_repair` refused, and that the same pair without a verdict is still refused.

`force` is recorded distinctly from `accept` so the count becomes the evidence for the deferred
`accept_repair` tightening.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] With a `force` verdict stored for a pair `accept_repair` refuses, the repair is applied; the same pair with no verdict is still refused.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
