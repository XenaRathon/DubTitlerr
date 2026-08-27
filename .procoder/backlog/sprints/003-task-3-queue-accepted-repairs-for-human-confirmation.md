# Task 3 -- queue accepted repairs for human confirmation

Status: closed 2026-08-27
Created: 2026-08-27

## Goal

At the end of this sprint every repair the gate ADMITTED is visible to a reviewer, carrying
the evidence needed to judge it -- and the ~25 lines per episode worth judging are separable
from the ~86 the queue holds in total.

`unresolved.py` is already the human rung of the deterministic -> LLM -> human ladder; its own
docstring says so. But it records only what the pipeline could NOT settle. An accepted repair
WAS settled -- by `accept_repair`, whose docstring states the acceptance bar and then says
plainly that nothing below it enforces that -- so today it is never queued at all. The
2026-08-27 read of 45 such repairs found 4 outright regressions and 5 more needing correction:
36 of 45 clean. None of those nine was reachable by any check in the pipeline.

Concretely: a new `repair_applied`/`accepted` stage with its own evidence template, recorded on
the success path in `repair.process()` beside the existing `audit.append`, carrying the card's
PRE-repair text and the text actually applied. And a primary filter over `pending()`, because
the owner reviews in evening batches and a queue that opens on `no_reference` entries -- mostly
"this release has no fansub", true but not actionable per line -- is a queue nobody faces.

Nothing here changes what an episode ships. `repair.py` gains one record call on a branch that
already exists; no branch is added, removed, or reordered, and the consult that reads the
decision store is still Task 4.

## Process change carried in from sprint 002's retro

The adversarial subagent review runs BEFORE these stories close, not after. Last sprint it ran
after all six closed and found four defects, three of them in closed stories -- every criterion
met, gate green, criteria incomplete. Sibling-module invariants are read before the criteria are
written: this task touches `unresolved.py` and `repair.py`, both of which carry invariants this
project learned the hard way and records in comments.

Deliberately excluded: the consult (Task 4), write-back (Task 5), the mux gate (Task 6), the
server (Task 7) and container wiring (Task 8).

## Retro

**What slowed us down.** Nothing structural — the process change carried in from sprint 002
worked on its first outing. The review ran before the stories closed and found a real gap, so
the gap was closed before anything was marked done rather than after. That is the whole
difference between this sprint and the last one.

The gap itself is worth recording, because it is a shape that will recur. Three placement
mutations were run by hand and all three failed correctly, which felt like proof the call site
was pinned. It was not: all three moved the call DOWN or sideways, and the untested direction
was UP — above the secondary-model block. The review found it by running the one probe that had
not occurred to the author, and reported the entire suite still green while the queue recorded
`I saw Spandam` for a card that shipped `I saw Spandam there`. A reviewer would have been
approving text the viewer never saw, on exactly the case the two-pass gate exists to catch.

A comment was also caught stating a false reason. `PRIMARY` excludes `punctuation`/
`rejected_guard`, and the comment justified it by claiming those entries cannot be judged by
reading two texts. `punctuation.py:290-296` records both texts, exactly as the repair rejection
that IS included does. The exclusion is correct; the stated reason was invented.

**What we change next sprint because of it.** Mutation checks get enumerated by DIRECTION before
they are run: for a call site, at minimum earlier and later than every branch boundary it sits
between, not only the one the author was already worried about. Three mutations that all move
the same way are one mutation.

And a comment that explains WHY something is excluded is checked against the code it describes,
the same as any other claim. A false rationale is worse than none — it stops the next reader
looking, and it survives every test because nothing executes it.

**One adaptation worth keeping.** Reading the sibling module's recorded invariants BEFORE writing
the code, not after. It paid twice in one task: `audit.append` running before `c["text"] = new`
gave the record call its correct position for free, and `REASONS["punctuation"]` also carrying
`rejected_guard` meant the filter was keyed on `(stage, reason)` pairs from the first draft
instead of being fixed later. Neither would have been obvious from the diff alone.

## Result

committed: 2
done: 2 (20260827-an-accepted-repair-writes-one-repair-applied-accepted-entry, 20260827-unresolved-pending-filtered-to-the-primary-stages-returns)
carried: 0
