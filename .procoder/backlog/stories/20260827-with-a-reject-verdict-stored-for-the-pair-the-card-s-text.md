# With a `reject` verdict stored for the pair, the card's text equals the POST-`glossary.correct()` ASR text and no `repair_applied` entry is written -- pinning the consult between `glossary.correct()` (`repair.py:634`) and `accept_repair` (`repair.py:649`), so a consult placed before the correction fails this.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 4. The consult must sit between `glossary.correct()` and `accept_repair`, and this story is what
pins it there. Done means a stored rejection leaves the card showing the POST-correction ASR text
and writes no queue entry.

Asserting post-correction text is deliberate: a consult placed before the correction would leave
different text and fail, which is the only cheap way to catch a mis-placed consult point.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] With a `reject` verdict stored for the pair, the card's text equals the POST-`glossary.correct()` ASR text and no `repair_applied` entry is written -- pinning the consult between `glossary.correct()` (`repair.py:634`) and `accept_repair` (`repair.py:649`), so a consult placed before the correction fails this.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
