# [F-3] The write-back is tested against a signs merge that returns no-signs, empty or build-error, so the outcome is a decision rather than an accident

Status: done 2026-08-27
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

- [x] With the signs merge returning `no-signs`, a write-back leaves the episode muxable and
      does NOT lose the human's verdict -- asserted on the shipped text.
- [x] The same for `empty` and `build-error`, which are different failures and need not have
      the same outcome; whatever each does is asserted rather than assumed.
- [x] A previously signs-bearing episode that now merges without signs is DISTINGUISHABLE in
      the output or the log from one that never had signs. The rebuttal called this
      recoverable; recoverable requires someone noticing.
- [x] No test in this story asserts a state the pipeline cannot produce -- the fixture is
      built from what `dub_signs_merge` and `mux` actually leave on disk.

## Evidence

- Four characterisation tests, which is what this story asked for -- the path was untested
  and the two pre-merge reviews disagreed about it, so the outcome is now asserted rather
  than argued.
- `test_a_write_back_leaves_a_muxable_sidecar_when_signs_cannot_be_merged`:
  `dub_signs_merge.build()` returns `"no-signs", 0, 0` at :127 BEFORE writing any `.ass` and
  before removing the srt, so `mux.sub_source` falls back to the srt and the episode still
  muxes carrying the verdict. Recoverable, as the rebuttal argued, and now pinned.
- `test_the_write_back_is_idempotent_across_a_failed_signs_pass`: a failing signs merge
  leaves the srt, so the next sweep runs the whole thing again -- a second write-back must
  not compound.
- `test_an_episode_that_never_had_signs_is_handled_the_same_way` is the counterpart, so the
  suite is not just describing the ass-removal branch.
- `test_removing_a_stale_ass_is_recorded_so_a_lost_signs_pass_is_noticeable`: "recoverable"
  requires someone noticing, and once the ass is gone nothing downstream can tell an episode
  that HAD signs from one that never did. The result distinguishes them.
- All four passed on arrival (they pin existing behaviour) and are held by mutation instead:
  stale ass not removed (5 tests), `ass_dropped` always reported (2), no srt written (7).
- `dub_signs_merge` was read from its `def` line this time, per the sprint 006 lesson.
