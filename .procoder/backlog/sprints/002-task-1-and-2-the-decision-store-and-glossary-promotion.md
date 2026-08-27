# Task 1 and 2 -- the decision store and glossary promotion

Status: closed 2026-08-27
Created: 2026-08-27

## Goal

At the end of this sprint a human verdict on a repaired subtitle line is a durable object
rather than a sentence in a Markdown file: it can be recorded, found again from the same
line next run, and shipped in git the way a glossary is.

Concretely: `decisions.py` exists and owns a per-show JSON store keyed on the normalised
`(orig, proposed)` text pair -- never on episode or card index, which does not survive a
`TEXT_VERSION` bump and means nothing in another library. It creates a show's file on first
use, appends without losing an earlier verdict, survives a torn write, refuses the two
malformed verdicts that would poison lookups, and resolves a show from an episode path by the
same ancestor walk `repair.glossary_for()` already uses. Where a verdict's lesson is a TERM
rather than a line it promotes into the show glossary's `hard_fixes`, where it applies
show-wide and ships in an artifact that is already committed -- and never over a curated entry,
because a human's glossary outranks a promotion.

Nothing in this sprint changes what any episode ships. `repair.py` is untouched; the consult
that would read this store is Task 4. That is deliberate: the store is the one piece every
later task depends on, and it is the piece that can be built and proven with no pipeline, no
GPU and no LLM.

Deliberately excluded: the queue, the consult, write-back, the mux gate, the server and the
container wiring -- Tasks 3 through 8. Each depends on this store existing and none of them
can be proven while its shape is still moving.

## Retro

**What slowed us down.** The adversarial review ran AFTER all six stories were closed, and
it found four defects — three of them in closed stories, one of which (`record()` appending
where it had to replace) reintroduced the exact both-states bug the sibling module documents
as its I3 invariant and warns against by name. Nothing was wrong with the closes: every
criterion was met, and the gate and suite were green. The criteria were incomplete. All six
described a FIRST verdict; none described a second one, so nothing tested a reviewer changing
their mind — the single thing a human-review store exists to support. Closing was correct and
the work was still wrong, which is the uncomfortable case.

A second, cheaper version of the same shape: the scout sweep that surfaced I3 was launched for
Task 2. Had it run before Task 1's criteria were written, it would have handed us the
invariant before we needed it rather than after we had broken it.

**What we change next sprint because of it.** The review moves inside the task. A subagent
review is launched against the finished code BEFORE its stories close, not after — the whole
point of the closer demanding evidence is defeated if the evidence is collected before the
strongest available critic has looked. And when a new module has a sibling with hard-won
invariants, that sibling is read before the CRITERIA are written, not before the code is.
Task 3 touches `repair.py` and `unresolved.py`, both of which carry exactly that kind of
recorded invariant, so this applies immediately.

**One adaptation worth keeping.** Mutation-checking every guard before its story closes: break
the production line, watch the test fail for the right reason, restore. It caught two
behaviours that had been implemented before their tests existed — `save()`'s atomicity and
`record()`'s `promoted` handling — both of which were passing on code nobody had proven, and
both of which would have read as covered in any review of the test file alone. A test that has
never been watched failing is a claim, not evidence.

## Result

committed: 6
done: 6 (20260827-a-decision-promoted-as-a-term-writes-hard-fixes-variant, 20260827-decisions-for-resolves-a-show-s-store-by-the-same-ancestor, 20260827-decisions-key-maps-we-re-looking-for-a-factory-and-we-re, 20260827-lookup-on-a-store-built-from-a-recorded-verdict-returns, 20260827-record-refuses-an-empty-orig-or-proposed-and-converts-a, 20260827-recording-a-verdict-for-a-show-with-no-existing-file)
carried: 0
