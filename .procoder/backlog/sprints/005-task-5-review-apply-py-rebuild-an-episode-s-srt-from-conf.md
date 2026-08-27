# Task 5: review_apply.py -- rebuild an episode's srt from conf.json with stored decisions applied, invalidate its stamp so the merge loop re-muxes, dry-run by default

Status: closed 2026-08-27
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

## Retro

What slowed us down: I built the whole module on an assumption I never checked -- that an
already-generated episode still has its `.srt` on disk. It does not; `mux.py` deletes both
sidecars the moment it stamps. Every one of the first five tests passed against a fixture
that hand-wrote conf + srt + stamp together, a combination this pipeline never produces. A
green suite proved nothing because the fixture described a world that does not exist.

Worse, I then reasoned FORWARD from that wrong premise to a confident conclusion -- that
rebuilding from conf.json would revert every repair in the library -- and reported it as a
defect in the plan. It was not: `merge_pass.sh` re-runs `repair.py` immediately afterwards,
which re-derives the repairs and applies the verdicts. The plan was right and I was wrong,
in exactly the direction sprint 004's own lesson warns about: I did not trace what runs
AFTER the code I was writing. I applied that lesson to `fits_card` and missed it for the
pipeline itself.

What we change next sprint: before writing the first test for a module that touches
existing files, WRITE DOWN the on-disk state of a real instance and verify each file's
existence against the code that creates and deletes it. A fixture is a claim about the
world; it needs the same evidence as any other claim. Concretely: the sidecar lifecycle
lives in `mux.py` and `dub_signs_merge.py`, and neither was read before the module was
designed -- both were one grep away.

Adaptation worth keeping: when a finding contradicts the spec, treat the spec as the
stronger prior until the contradiction is traced end to end. My "the plan's premise is
broken" claim came from a genuine observation (conf.json holds ASR text) plus an untraced
inference (therefore repairs are lost). The observation was right and the inference was
wrong, and the difference was three greps.

Also confirmed again: the adversarial review before closing. It found the load-bearing
defect, and the two silent-failure defects in the sweep, none of which any test caught.

## Result

committed: 4
done: 4 (20260827-an-episode-with-no-conf-json-is-refused-by-name-and-its, 20260827-review-apply-py-on-an-episode-with-a-stored-reject-rewrites, 20260827-review-apply-py-show-invalidates-only-the-episodes-whose, 20260827-without-apply-it-writes-nothing-and-prints-the-plan)
carried: 0
