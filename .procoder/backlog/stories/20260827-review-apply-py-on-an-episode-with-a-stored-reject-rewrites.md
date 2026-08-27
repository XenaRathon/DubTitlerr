# `review_apply.py` on an episode with a stored `reject` rewrites the `.srt` with the ASR text restored and invalidates the `.dubtitles.done` stamp, WITHOUT invoking the LLM -- it rebuilds from `conf.json` the way `recreate_srt.py` does. Asserted on the backend never being called, because re-running `repair.py` also rebuilds the srt from `conf.json` and would otherwise satisfy this criterion.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 005-task-5-review-apply-py-rebuild-an-episode-s-srt-from-conf

## Description

Task 5. The 45 lines already reviewed are in episodes already generated; a verdict that cannot reach
them is prose. Done means the srt is rebuilt from `conf.json` with the ASR text restored and the
`.dubtitles.done` stamp invalidated so the existing merge loop re-muxes.

The test asserts the LLM is never called. `repair.py` also rebuilds the srt from `conf.json`, so a
criterion checking only the srt would be satisfied by re-running repair -- which is not what this is
for and would cost the whole episode's inference again.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `review_apply.py` on an episode with a stored `reject` rewrites the `.srt` with the ASR text restored and invalidates the `.dubtitles.done` stamp, WITHOUT invoking the LLM -- it rebuilds from `conf.json` the way `recreate_srt.py` does. Asserted on the backend never being called, because re-running `repair.py` also rebuilds the srt from `conf.json` and would otherwise satisfy this criterion.

## Evidence

- `pytest tests/test_review_apply.py` -> 10 passed, including
  `test_an_already_muxed_episode_gets_a_sidecar_and_loses_its_stamp`.
- The LLM assertion is real: `common.llm_chat` is monkeypatched to raise. `repair.py`
  rebuilds the same srt from the same `conf.json`, so a criterion checking only the file
  would be satisfied by re-running repair -- the one thing this module must not do.
- SCOPE CORRECTED MID-SPRINT by the adversarial review. The first implementation read the
  existing `.srt` to learn what shipped. `mux.py:367-371` removes BOTH sidecars right after
  stamping (and `dub_signs_merge.py:188` removes the srt earlier), so a stamped episode has
  no srt at all: the module would have refused every episode in the population it exists
  for. It now WRITES a sidecar rather than editing one, which is what `merge_pass.sh:56`
  globs for.
- Rebuilding from `conf.json` does not lose the repairs: `merge_pass.sh:59` re-runs
  `repair.py` whenever an srt is present with no ass, and [S-4] settles the reviewed lines
  on that pass. My own earlier claim that this reverted repairs was wrong -- I had not
  traced what runs AFTER this module, which is exactly the sprint 004 lesson.
- Mutation: re-opening every episode regardless of verdicts fails 4 tests.
