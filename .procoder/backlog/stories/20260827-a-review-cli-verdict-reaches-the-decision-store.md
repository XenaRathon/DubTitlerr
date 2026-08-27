# [F-1] A `--review` CLI verdict reaches the decision store, so a human's "needs fixing" is honoured on the next run instead of being silently dropped

Status: done 2026-08-27
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

- [x] A `--review` answer of "needs fixing" records a `reject` verdict in the decision store
      for that entry's `(original, proposed)` pair, not only the resolved flag.
- [x] A `--review` answer of "keep as-is" records the matching verdict, and the two are
      distinguishable in the store -- asserted on the stored verdict, since both answers
      currently produce an identical queue state.
- [x] `repair.py` on the next run honours that verdict, asserted on the shipped SRT.
- [x] The store write failing is reported to the operator rather than swallowed: a review
      that silently discards a decision is the failure this loop exists to prevent.
- [x] `unresolved.py` remains import-safe for `mux.py` and `repair.py` (no import cycle).

## Evidence

- `test_needs_fixing_on_an_applied_repair_records_a_reject`,
  `test_keep_as_is_and_needs_fixing_are_distinguishable_in_the_store`,
  `test_needs_fixing_on_a_refused_repair_records_a_force`,
  `test_a_store_write_failure_is_reported_not_swallowed` -- all RED first.
- The mapping is PER STAGE, because "keep as-is" is about the CARD and the card shows
  different things depending on why the entry was queued. On `repair_applied`/`accepted` the
  repair shipped, so k=accept / f=reject. On `repair`/`rejected_guard` the repair was
  REFUSED and the card shows the ASR, so k=reject (endorsing the refusal) and f=force
  (the ASR is wrong, admit the refused proposal). Recording `reject` for "needs fixing" on
  both would silently invert the reviewer's meaning on half of them -- pinned by a mutation
  that collapses the two stages, which fails the force test.
- The VERDICT is written before the flag, and an unsaved verdict leaves the entry PENDING:
  marking it resolved would hide the loss from the next walk, which is the one place it
  would still be visible.
- Entries with no `proposed_text` (`no_reference`, `llm_empty`) have no pair to key on and
  are left alone -- they were never decisions.
- No import cycle: `decisions.py` imports only stdlib, verified.
- Mutations caught: verdict not recorded at all (4 tests), both stages given the same
  mapping (1), entry resolved despite a failed store write (1).
