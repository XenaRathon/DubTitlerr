# [F-3] The write-back is tested against a signs merge that returns no-signs, empty or build-error, so the outcome is a decision rather than an accident

Status: open
Created: 2026-08-27
Epic: review-loop-followups
Sprint: 009-review-loop-follow-ups-from-the-pre-merge-round-honour-a

## Description

Both reviews reached this path and disagreed about it, which is itself the reason to test it.
Luna claimed the write-back is "not guaranteed to re-run repair" and that signs go silently
absent; the rebuttal rejected the first half on the trace (`merge_pass.sh` re-runs repair on
every write-back pass) and downscoped the second to a transient, recoverable state.

Neither claim is currently pinned by a test. `dub_signs_merge.build()` returns
`"no-signs", 0, 0` before writing any `.ass` (the early return that cost sprint 006 a wrong
answer), and `process_one` can also return `empty` or `build-error`. `review_apply` removes a
stale `.ass` and writes an `.srt`, so what an episode ends up with after a failing signs merge
is currently established only by argument.

## Acceptance criteria

- [ ] With the signs merge returning `no-signs`, a write-back leaves the episode muxable and
      does NOT lose the human's verdict -- asserted on the shipped text.
- [ ] The same for `empty` and `build-error`, which are different failures and need not have
      the same outcome; whatever each does is asserted rather than assumed.
- [ ] A previously signs-bearing episode that now merges without signs is DISTINGUISHABLE in
      the output or the log from one that never had signs. The rebuttal called this
      recoverable; recoverable requires someone noticing.
- [ ] No test in this story asserts a state the pipeline cannot produce -- the fixture is
      built from what `dub_signs_merge` and `mux` actually leave on disk.
