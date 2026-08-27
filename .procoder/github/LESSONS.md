# Lessons — findings that escaped our own gates

One entry per finding caught downstream (bot review, human review,
production) — the escape is the bug; the finding is its symptom. Every
entry names which layer should have caught it and the adaptation that now
does. `procoder lessons` flags entries with no adaptation.

Entry shape (unindented in real entries):

    ## <date> <where caught> — <one-line finding>

    - Class: mechanical | judgment | taste
    - Missed by: linter | rubric | controller | test | ci
    - Adaptation: <the concrete change that catches this class from now on>

== then register the commit template (once per clone):
git config commit.template .procoder/github/COMMIT_TEMPLATE.md

## 2026-08-27 subagent review — a re-decided verdict was silently unreachable

- Class: judgment
- Missed by: rubric
- Finding: `decisions.record()` appended and `lookup()` returned the first match, so a
  reviewer changing their mind wrote a second entry that was stored, shipped to git, and
  permanently unreachable. The sibling module documents this exact failure as its I3/C2
  invariant (`glossary_acquire.py:668`, "the both-states bug this module exists to avoid
  reintroducing") and the new module reintroduced it anyway.
- Missed because: all six acceptance criteria described a FIRST verdict. Nothing described
  a second one, so nothing tested one, and the story closed correctly against criteria that
  were incomplete rather than wrong.
- Adaptation: when a new module has a sibling with hard-won invariants, read that sibling's
  invariants BEFORE writing the criteria, not before writing the code. The scout sweep that
  surfaced I3 was run for Task 2 and would have caught this in Task 1 had it come first.

## 2026-08-27 subagent review — guards validated the shape of input but never its value

- Class: mechanical
- Missed by: test
- Finding: `record()` guarded an empty pair and a no-op `correct`, but accepted any verdict
  string at all (`"aceptt"`, `""`, `None`) and accepted a `correct` carrying no replacement
  text. The latter would have raised `KeyError` inside `repair.py` mid-episode, against this
  project's never-fail-an-episode contract, or rendered a blank card.
- Missed because: the criterion named the two guards to build. Having built exactly those
  two, the story was complete — a criterion that enumerates cases silently asserts the list
  is exhaustive.
- Adaptation: for any function taking untrusted input, the criteria enumerate the VALUE
  space (which values are legal), not just the failure cases already thought of. The
  test now passes `[..., None, 0, ["reject"]]` because the value arrives from a JSON body.

## 2026-08-27 subagent review — two tests asserted half of their guard's contract

- Class: mechanical
- Missed by: test
- Finding: the no-op-`correct` test asserted the verdict flipped to `reject` but not that
  the correction text was dropped; the empty-pair test used literal `""` and would have
  passed had the guard checked the raw argument instead of the normalised key.
- Missed because: each test was written from the criterion's wording rather than from the
  mutation that should break it.
- Adaptation: every guard test is mutation-checked before its story closes — break the
  production line, watch the test fail, restore. Applied to five behaviours in this sprint,
  and it caught two claims that had been implemented before their test existed
  (`save()`'s atomicity and `record()`'s `promoted` handling), both of which were passing
  on code nobody had proven.
