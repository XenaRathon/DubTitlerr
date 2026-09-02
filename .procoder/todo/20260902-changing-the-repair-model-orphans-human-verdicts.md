# Changing the repair model orphans existing human verdicts

Status: closed 2026-09-02
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

- [x] Re-running under a different `REPAIR_MODEL` no longer ships silently: an orphaned
      APPROVAL is queued as `verdict_stale_proposal` and counted in the run summary.
      `tests/test_repair.py::test_an_approval_orphaned_by_a_new_proposal_is_queued_not_silent`
- [x] The reviewer can tell which decisions still hold: the queue entry carries
      `approved_text` (what they endorsed), `proposed_text` (what the model now says) and
      `model` (which model moved), and the review page offers the full verdict set on it.
- [x] The `(orig, proposed)` keying is untouched, and a superseded REJECTION is explicitly
      not flagged -- that is the designed flow `lookup`'s docstring protects.
      `tests/test_repair.py::test_a_superseded_rejection_is_not_flagged_as_stale`
- [x] Mutation-checked both ways: dropping the check fails the first test, widening it to
      all verdicts fails the boundary test.

## Evidence

Implemented on `feat/review-sorting`, 2026-09-02.

Chosen approach: SURFACE, do not guess. Matching on the original alone was rejected --
`accept`/`force` endorse the model's wording, and re-applying an old approval to new
wording would be the same class of error in the other direction.

- `repair.process`: when `lookup` misses but the original carries an APPLYING verdict, the
  card is queued as `verdict_stale_proposal` with `approved_text`, `proposed_text` and
  `model`, and counted in the run summary. Narrowed to approvals: a superseded rejection is
  the designed flow and flagging it would bury the signal in noise.
- `review_server.OFFERED` gains the reason with the full verdict set, so the reviewer can
  rule on the NEW wording -- `force` included, since new wording may trip a gate the old
  wording did not.
- `decisions.record` now keeps the verbatim wording for `accept` as well as `force`, so the
  queue shows what was approved rather than the case-folded match key. This does not make
  `accept` rescuable: `forced_text` filters on the verdict, not on the presence of `text`.
- 3 new tests, mutation-checked in both directions. Full suite green, ruff clean.

The original note suggested recording `REPAIR_MODEL` in the decision entry as the cheapest
first step. It is recorded on the QUEUE entry instead, which is where it is actually read:
the decision store answers "what did the human decide", and the model that produced a
proposal is a property of the proposal, not of the decision.
