# [F-1] A `--review` CLI verdict reaches the decision store, so a human's "needs fixing" is honoured on the next run instead of being silently dropped

Status: open
Created: 2026-08-27
Epic: review-loop-followups
Sprint: 009-review-loop-follow-ups-from-the-pre-merge-round-honour-a

## Description

Raised as a residual risk in the GLM rebuttal, verified: `unresolved.py` does not import
`decisions` at all, so `unresolved.resolve()` sets a flag on a queue entry and writes nothing
durable. `repair.py` suppresses re-application only on a stored VERDICT, and suppresses
re-queueing on a pair already present in the queue file.

So a reviewer who walks the queue with `python3 unresolved.py --review` and answers
"needs fixing" gets: the entry marked resolved, no verdict recorded, the repair still applied
on every subsequent run, and no new queue entry to remind them. Their judgement is dropped in
silence, and the queue's own audit trail records that they made one.

The shipped text is unaffected TODAY only because the repair would have been applied anyway.
That is not a defence — it means the CLI's reject is indistinguishable from its accept.

The server path does both writes (`review_server.handle_decide`), so this is specifically the
CLI's gap.

## Acceptance criteria

- [ ] A `--review` answer of "needs fixing" records a `reject` verdict in the decision store
      for that entry's `(original, proposed)` pair, not only the resolved flag.
- [ ] A `--review` answer of "keep as-is" records the matching verdict, and the two are
      distinguishable in the store -- asserted on the stored verdict, since both answers
      currently produce an identical queue state.
- [ ] `repair.py` on the next run honours that verdict, asserted on the shipped SRT.
- [ ] The store write failing is reported to the operator rather than swallowed: a review
      that silently discards a decision is the failure this loop exists to prevent.
- [ ] `unresolved.py` remains import-safe for `mux.py` and `repair.py` (no import cycle).
