# Task 5: review_apply.py -- rebuild an episode's srt from conf.json with stored decisions applied, invalidate its stamp so the merge loop re-muxes, dry-run by default

Status: active
Created: 2026-08-27

## Goal

Task 4 made a verdict change what the NEXT run of an episode ships. That leaves every
episode already generated -- the whole library -- carrying text a reviewer has since ruled
on, with no way to act on it short of re-running the pipeline. This sprint closes that:
`review_apply.py` rebuilds an episode's `.srt` from its `conf.json` with stored decisions
applied and invalidates the `.dubtitles.done` stamp, so the merge loop the container
already runs re-muxes it. One episode, or a sweep of a whole show.

It rebuilds the way `recreate_srt.py` does rather than calling `repair.process()`. That is
the point of the module: no LLM, no network, no re-judging -- the decisions are already
made, and re-running repair would be free to reach different conclusions than the ones the
human reviewed. The test asserts the backend is never called, because `repair.process()`
also rebuilds the srt from `conf.json` and a criterion that only checks the srt would be
satisfied by the very thing this task exists to avoid.

Dry-run by default, matching `mux.py` and `glossary_acquire.py`. A show sweep invalidates
only the episodes whose text actually changes, so a stamp is never thrown away for an
episode this had no opinion about.

## Carried from the sprint 004 retro

When a change introduces an authority, enumerate every EXISTING actor that can still write
the same value AFTER it has spoken. Here the value is the shipped `.srt` and the stamp, and
the other actors are `repair.process()` (rebuilds the same srt), the merge loop (reads the
stamp), and `generate.py` (writes both). A test per actor, not per function.

Also kept: run the adversarial review BEFORE closing stories.
