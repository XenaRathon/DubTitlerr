# Task 4: consult the decision store inside repair -- reject/correct/force verdicts applied under DECISIONS_APPLY, fits_card never overridden

Status: active
Created: 2026-08-27

## Goal

A human verdict recorded by an earlier review changes what the next run of an episode
ships. Until now the decision store has been write-only: sprint 002 built it, sprint 003
filled its queue, and nothing read either back. This sprint closes that loop.

`repair.py` consults the store for each candidate card between `glossary.correct()` and
`accept_repair()`. A stored `reject` keeps the corrected ASR text and writes no
`repair_applied` entry. A stored `correct` applies the human's text. A stored `force`
admits a repair `accept_repair` refused -- and only that: `fits_card` still governs both
`correct` and `force`, because card timing is immutable (C1) and a line that cannot be
rendered is not a decision a human is allowed to make. A refusal on that path tells the
human rather than dropping silently.

This is the first change in the epic that alters what a viewer sees, so the sprint is
written to make the two ways it could be fake fail loudly:

- An empty store must produce byte-identical output AND observably reach the consult. A
  `return` that never reaches it satisfies byte-identity on its own.
- `DECISIONS_APPLY=0` must be proven read BEFORE the verdict takes effect, asserted on
  the application rather than the bytes. Identical output proves the flag exists, not
  that it is honoured in the right order.

Carried from the sprint 003 retro: enumerate mutation DIRECTIONS before running them --
three mutations that move the same way are one mutation -- and run the adversarial review
BEFORE closing stories, not after.
