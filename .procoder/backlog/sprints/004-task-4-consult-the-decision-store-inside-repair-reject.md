# Task 4: consult the decision store inside repair -- reject/correct/force verdicts applied under DECISIONS_APPLY, fits_card never overridden

Status: closed 2026-08-27
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

## Result

committed: 8
done: 8 (20260827-a-correct-verdict-whose-text-fails-fits-card-leaves-the-asr, 20260827-a-force-verdict-whose-text-fails-fits-card-is-still-refused, 20260827-an-empty-store-produces-byte-identical-output-to-the-code, 20260827-decisions-apply-0-produces-byte-identical-output-to-an, 20260827-with-a-correct-verdict-stored-the-card-carries-the-human-s, 20260827-with-a-force-verdict-stored-for-a-pair-accept-repair, 20260827-with-a-reject-verdict-stored-for-the-pair-the-card-s-text, 20260827-with-an-accept-verdict-stored-for-the-pair-the-repair-is)
carried: 0

## Retro

What slowed us down: nothing in the mechanics -- the cost was three defects that the plan
did not anticipate, two of which only appeared because a NEW concept ("settled") interacted
with code written before it existed. The secondary-model pass and `accept_repair` were both
correct on their own terms; they became wrong the moment a human verdict could reach them.
The plan's task list, written before any of this code existed, could not have seen that.

What we change next sprint: when a change introduces a new authority (here: a human verdict
that outranks the gate), enumerate every EXISTING actor that can still overwrite the same
value AFTER the new authority has spoken, and write a test per actor. Both real defects
this sprint were exactly that shape -- something downstream reassigning `new`, or re-judging
a decision -- and both were invisible from the diff, which only shows the code that was
added, never the code that still runs afterwards.

Adaptation worth keeping: the suppression rule made the secondary-model bug WORSE, not
better -- it removed the queue entry that would have been the only evidence the
substitution happened. Any feature that suppresses an audit record needs its own check that
what it suppresses is genuinely settled, because a wrong suppression is silent by
construction. Ask of every "don't record this" branch: if the thing I am hiding were wrong,
what would tell me?

Also kept from sprint 003 and confirmed useful twice: running the adversarial review BEFORE
closing stories (it found a shipped-output defect that would otherwise have closed green),
and enumerating mutation DIRECTIONS -- the "consult moved above the correction" direction
that was missed last sprint is now the most heavily pinned property in the change.
