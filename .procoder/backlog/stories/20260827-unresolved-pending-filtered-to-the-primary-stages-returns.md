# `unresolved.pending()` filtered to the primary stages returns exactly the accepted repairs plus the guard rejections, and the unfiltered walk additionally returns `no_reference`, `llm_empty` and the punctuation stages.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 3. The owner reviews ~25 judgement-worthy lines per episode but the queue holds ~86 once
`no_reference` and `llm_empty` are counted. Done means the default view is the actionable subset and
the full walk is one flag away.

The test asserts the ABSENCE of non-primary reasons. `unresolved.pending()` applies no stage filter
of its own, so a filter that returns everything would pass a presence-only assertion.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `unresolved.pending()` filtered to the primary stages returns exactly the accepted repairs plus the guard rejections, and the unfiltered walk additionally returns `no_reference`, `llm_empty` and the punctuation stages.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
