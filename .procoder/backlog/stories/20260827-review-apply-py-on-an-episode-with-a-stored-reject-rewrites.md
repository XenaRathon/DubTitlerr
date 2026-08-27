# `review_apply.py` on an episode with a stored `reject` rewrites the `.srt` with the ASR text restored and invalidates the `.dubtitles.done` stamp, WITHOUT invoking the LLM -- it rebuilds from `conf.json` the way `recreate_srt.py` does. Asserted on the backend never being called, because re-running `repair.py` also rebuilds the srt from `conf.json` and would otherwise satisfy this criterion.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

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

- [ ] `review_apply.py` on an episode with a stored `reject` rewrites the `.srt` with the ASR text restored and invalidates the `.dubtitles.done` stamp, WITHOUT invoking the LLM -- it rebuilds from `conf.json` the way `recreate_srt.py` does. Asserted on the backend never being called, because re-running `repair.py` also rebuilds the srt from `conf.json` and would otherwise satisfy this criterion.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
