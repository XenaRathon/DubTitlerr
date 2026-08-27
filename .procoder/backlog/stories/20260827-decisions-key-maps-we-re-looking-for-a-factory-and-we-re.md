# `decisions.key()` maps `"  We're  Looking  For A Factory. "` and `"we're looking for a factory."` to the same key, and maps `"CP-0."` and `"CP?"` to different keys.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 002-task-1-and-2-the-decision-store-and-glossary-promotion

## Description

Task 1. A verdict has to match the same line next run despite whitespace and capitalisation drift,
without collapsing two genuinely different lines together. Done means case and whitespace are
normalised away and punctuation is not -- the majority of this stage's repairs ARE punctuation, and
`CP-0.` must never match `CP?`.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `decisions.key()` maps `"  We're  Looking  For A Factory. "` and `"we're looking for a factory."` to the same key, and maps `"CP-0."` and `"CP?"` to different keys.

## Evidence

RED: `python3 -m pytest tests/test_decisions.py -q` before `decisions.py` existed —
`ModuleNotFoundError: No module named 'decisions'`, collection interrupted, exit 2. The
feature was missing, not misspelled.

GREEN: same command after implementing `key()` as `" ".join(text.lower().split())` —
exit 0, 1 passed.

The test asserts both directions: `"  We're  Looking  For A Factory. "` and
`"we're looking for a factory."` collapse to one key, and `CP-0.` and `CP?` stay two.
That second pair is a real ASR/proposal pair the owner rejected on 2026-08-27, so folding
punctuation would have let the rejection match the text it rejected in favour of.
