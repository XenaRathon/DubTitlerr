# A decision promoted as a term writes `hard_fixes[variant] = canonical` into the show glossary, the decision records what it promoted, and a curated entry already present is not overwritten.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 2. When a verdict's lesson is a TERM rather than a line -- `Samadai -> Samurai` -- it belongs in
the glossary, where it applies show-wide through `glossary.correct()` and ships in an artifact that
is already committed. Done means the promotion writes `hard_fixes`, the decision records what it
promoted, and a curated entry already present is never overwritten: a human's glossary outranks a
promotion.

`promoted` is set by the human at review time. No rule auto-classifies -- auto-classification on a
single-token difference would promote `factory -> needle` show-wide, the exact regression the store
exists to catch.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] A decision promoted as a term writes `hard_fixes[variant] = canonical` into the show glossary, the decision records what it promoted, and a curated entry already present is not overwritten.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
