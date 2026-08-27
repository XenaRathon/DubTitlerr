# Recording a verdict for a show with no existing file creates the file; a second verdict appends without losing the first; a crash-simulating partial write leaves the previous file intact.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 1. A show's store must appear on first use the way `mine_glossary.py` creates a glossary from
nothing, and must never lose an earlier verdict to a later one. Done means create-on-first-write,
append without loss, and a torn write leaves the previous file intact -- atomic `mkstemp` +
`os.replace`, mirroring `unresolved._rewrite`.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] Recording a verdict for a show with no existing file creates the file; a second verdict appends without losing the first; a crash-simulating partial write leaves the previous file intact.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
