# `decisions.key()` maps `"  We're  Looking  For A Factory. "` and `"we're looking for a factory."` to the same key, and maps `"CP-0."` and `"CP?"` to different keys.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 1. A verdict has to match the same line next run despite whitespace and capitalisation drift,
without collapsing two genuinely different lines together. Done means case and whitespace are
normalised away and punctuation is not -- the majority of this stage's repairs ARE punctuation, and
`CP-0.` must never match `CP?`.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `decisions.key()` maps `"  We're  Looking  For A Factory. "` and `"we're looking for a factory."` to the same key, and maps `"CP-0."` and `"CP?"` to different keys.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
