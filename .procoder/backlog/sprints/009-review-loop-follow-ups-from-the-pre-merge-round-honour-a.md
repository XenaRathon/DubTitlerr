# Review-loop follow-ups from the pre-merge round: honour a CLI verdict, coalesce competing proposals, pin the failing-signs write-back, bound concurrency

Status: active
Created: 2026-08-27

## Goal

Everything the pre-merge adversarial round left open, and nothing else. The gating item — an
unauthenticated request pinning a worker thread forever, because
`BaseHTTPRequestHandler.timeout` is None and `StreamRequestHandler.setup()` only calls
`settimeout()` when it is not — landed in `3bd20a4` with the inline-handler and
partial-failure-reporting fixes.

Four items remain, in descending order of how much they matter to a human using this:

**[F-1] is the one that changes behaviour.** A `--review` CLI answer of "needs fixing" marks
the queue entry resolved and writes nothing durable, because `unresolved.py` does not import
`decisions` at all. The repair is re-applied on the next run and never re-queued, so the
reviewer's judgement is dropped in silence while the audit trail records that they made one.
The CLI's reject is currently indistinguishable from its accept.

**[F-2]** is the surviving tail of Luna's finding 3, conceded in the rebuttal: the re-queue
suppression keys on the `(original, proposed)` pair, so a CHANGED proposal appends a second
pending entry for the same card. Two competing items, and settling one leaves a gated episode
held on the other.

**[F-3]** pins a path both reviews reached and disagreed about — the write-back against a
signs merge returning `no-signs`/`empty`/`build-error`. The rebuttal won the argument on the
trace; the outcome should be a decision with a test behind it rather than a settled argument.

**[F-4]** bounds concurrency. The deadline converted an indefinite pin into a sustained
churn; this bounds the churn. Availability of the review service only, never the pipeline.

## Not in scope

Finding 4's "held forever" and Finding 5's "signs silently absent" were rejected on the trace
and are not reopened. `mux.held_for_review` makes the durable verdict the hold's authority,
and `merge_pass.sh` re-runs repair on every write-back pass.

## Carried from the sprint 007/008 retros

For each guard, ask what input makes the GUARD PASS while the property it protects is FALSE.
When a test enforces a rule over a list, assert the list's own membership too. And read a
function from its `def` line before making a control-flow claim about it — `dub_signs_merge`
is in scope again this sprint, and its early return is exactly what cost sprint 006 a wrong
answer.
