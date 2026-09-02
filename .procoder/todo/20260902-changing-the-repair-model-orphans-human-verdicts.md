# Changing the repair model orphans existing human verdicts

Status: open
Created: 2026-09-02

## Description

`decisions.record` replaces per `(orig, proposed)` pair, and `lookup` needs BOTH sides to
match. That is deliberate -- a rejection of one proposal must not suppress a different one.
The consequence nobody had measured: the proposal side is produced by the repair LLM, so
CHANGING THE MODEL changes the key, and every verdict recorded against the old model's
wording is orphaned.

MEASURED 2026-09-02. The repair backend moved from `nanbeige4.2-3b` to
`qwen3-4b-instruct` (Q6_K) and MARRIAGETOXIN S01E10 was re-run. Two verdicts the reviewer
had settled came back unsettled because the new model proposed different text for the same
original:

    reviewer approved : Are you listening? Earth to Gato.
    qwen proposed     : Are you listening, Earth to Gato?      <- shipped instead

    reviewer approved : more amateur work. i see you haven't changed mr. beast master.
    qwen proposed     : More amateur work. I see you haven't changed Mr. Beast Master?

Both show in the unresolved log as `repair_applied / accepted` -- the pipeline believes it
applied an approved repair, and it did, just not the one the human approved. The reviewer
is never told, because from the store's point of view nothing is wrong: their verdict is
still there, attached to a proposal that no longer occurs.

`decisions.corrected_text` already answers on the ORIGINAL alone, and its docstring
explains why that is safe for `correct` and only for `correct`. That is exactly the escape
hatch this needs for the other verdicts, and exactly why it cannot simply be widened to
them -- `accept`/`force` carry the model's wording, which is the thing that changed.

Done looks like: a model change either preserves settled verdicts, or surfaces them for
re-review instead of silently shipping a different wording under an old approval.

## Acceptance criteria

- [ ] Re-running an episode under a different `REPAIR_MODEL` does not silently ship a
      proposal the human never saw under the authority of a verdict for a different one.
- [ ] Whatever the answer is -- re-queue for review, match on the original, record the
      model in the entry -- the reviewer can tell which of their decisions still hold.
- [ ] The `(orig, proposed)` keying still prevents one rejection suppressing a different
      proposal (the reason the pair key exists).
- [ ] A test with two different proposals for one original across a model change.

## Notes

`REPAIR_MODEL` is not recorded in the decision entry today, so there is no way to tell
after the fact which model a verdict was made against. Recording it is probably the
cheapest first step and is useful regardless of which fix is chosen.

## Evidence

<!-- filled at close -->
