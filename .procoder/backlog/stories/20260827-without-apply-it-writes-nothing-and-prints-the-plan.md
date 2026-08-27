# Without `--apply` it writes nothing and prints the plan.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 5. Every write-capable tool in this repo is dry-run by default -- `mux.py`, `glossary_acquire.py`.
Done means the plan prints and nothing on disk changes without `--apply`.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] Without `--apply` it writes nothing and prints the plan.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
