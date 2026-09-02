# Acquire cache: memoise the escalate adjudications, not the final verdicts

Status: closed
Created: 2026-08-29
Closed: 2026-09-02
Interim removed: `ACQUIRE_NO_CACHE=1` on dry runs in `gen_loop.sh` (no longer needed)

## Description

`acquire_cache` folds cached verdicts into `settled` (`glossary_acquire.acquire()`), and
`propose()` skips `settled`. A dry run therefore banks verdicts that a later `--apply` run
never proposes. Proven in-session on 2026-08-28: two byte-identical dry invocations gave
`proposed 641` then `proposed 0`.

The 2026-08-29 handoff and the DeepSeek review both framed this as an `--apply` problem.
**It is wider than that, and the reason is the verdict vocabulary.**

`glossary_acquire` produces exactly three verdicts: `apply`, `known`, `flag`. There is no
`junk` verdict at all — `acquire_cache.remember()` invents it by mapping `flag` -> `"junk"`
(`acquire_cache.py:158`). And all three write glossary state in `apply_proposals()`:

| verdict | what it writes                     |
| ------- | ---------------------------------- |
| `apply` | `hard_fixes` + `acquired`          |
| `known` | `known`                            |
| `flag`  | `flagged` — the human review queue |

**So there is no verdict a dry run may safely skip.** Every cached verdict suppresses a
write that `--apply` was meant to make.

## Measured blast radius (2026-08-29, five cache files — the handoff named three)

| show                        | total      | apply  | known     | flag (stored as "junk") |
| --------------------------- | ---------- | ------ | --------- | ----------------------- |
| One Pace                    | 10,238     | 22     | 1,346     | 8,870                   |
| SPY x FAMILY                | 701        | 0      | 116       | 585                     |
| JUJUTSU KAISEN              | 593        | 0      | 105       | 488                     |
| Sword Art Online            | 641        | 0      | 63        | 578                     |
| Reborn as a Vending Machine | 211        | 0      | 24        | 187                     |
| **total**                   | **12,384** | **22** | **1,654** | **10,708**              |

The `flag` column is the one nobody had counted: **10,708 terms computed for the review
queue, banked as "junk", that would never surface for a human to review.** The SAO file was
deleted on 2026-08-29 (backup: `/tmp/sao-acquire-cache.bak.json` in `dubtitle-review`); the
other four remain.

Note also `is_fresh` (`acquire_cache.py:118-120`): `if entry["verdict"] != "junk": return True`
serves `apply` and `known` verdicts unconditionally and forever, with no recycling check.
Only flag-derived entries get the growth/anchor recycling logic — backwards from what safety
would want.

## Why the three reviewed options are all wrong

- **(a) gate `save()` on `apply`** — correct, but removes the cache in the current dry-only
  production mode, which is exactly the timeout it was built to fix (the stage exceeded its
  budget three sweeps running before the cache existed).
- **(b) replay cached verdicts into `apply_proposals`** — the cache stores only
  `verdict/count/reason/canonical/floor_anchor`; a proposal needs `score`, `variant_count`,
  `canonical_count`, `bound`, `source`, `context`. Cannot be rebuilt from what is stored.
- **(c) stamp entries with a run_id** — does not help: the problem is not _which_ run
  applied, it is that skipping any verdict destroys the proposal.

The information the skip destroys IS the report. You cannot both skip work on a dry run and
have the dry run report what it would do — as long as what is cached is the _verdict_.

## The fix

Cache the expensive INTERMEDIATE, not the outcome: memoise `escalate()`'s LLM adjudications,
keyed on the token and its context. That is the 71% of runtime the cache docstring names.
Every token then still flows through `propose()` and `source_gate()` on every run, so the
report is complete and nothing is suppressed, while the LLM cost is paid once.

Also fold in R4 from `REVIEW-2026-08-29-handoff-and-codebase.md`: the token x title join runs
BEFORE the cache is consulted, so the module's other dominant cost is repaid every sweep
regardless. That review's own rebuttal notes its proposed fix is incomplete (`unmatched()`
needs the full join to know which tokens resolve to nothing), so measure before designing.

## Acceptance criteria

- [x] A dry run and an `--apply` run over the same corpus propose the SAME set of terms.
- [x] Two consecutive dry runs report the same `proposed` count (today: 641 then 0).
- [x] A cached escalate adjudication is reused — asserted on the LLM call count, not runtime.
- [x] `acquire_cache`'s docstring contract ("must never change what the pipeline decides")
      holds under test, with a non-empty cache.
- [x] The four remaining cache files are handled (deleted, or migrated to the new shape).
- [x] The `ACQUIRE_NO_CACHE=1` interim is removed from `gen_loop.sh`.

## Evidence

Implemented in `1bf78a8` (fix(acquire_cache): memoise escalate's LLM adjudication, not the
verdict). `acquire_cache.py` rewritten: `skippable`/`is_fresh`/`stale_canonical`/`recycles`/
`STRUCTURAL_REASONS`/`JUNK_RECHECK_GROWTH`/`remember` (the old per-token verdict cache and
its staleness apparatus) removed; `escalation_for`/`remember_escalation` added, keyed on the
`(variant, canonical)` pair. `glossary_acquire.escalate()` now consults/updates this cache
per-pair instead of skipping tokens via `settled`; `acquire()` no longer folds any cache
result into `settled` at all -- every token reaches `propose()`/`source_gate()` on every run.

All 6 acceptance criteria:

- Dry run == apply run proposal set: `test_a_dry_run_and_an_apply_run_propose_the_same_terms`
  reproduces the exact 2026-08-29 regression shape (Smokey/Smoker fixture) and asserts the
  flagged-term set is identical across a dry run, a second dry run, and an apply run.
- Two dry runs same `proposed` count: same test, `first["proposed"] == second["proposed"]`.
- Cached escalate adjudication reused, asserted on LLM call count:
  `test_escalate_reuses_a_cached_adjudication_instead_of_calling_the_llm_again` -- `calls ==
["Deccan"]` after two `escalate()` calls sharing one cache dict.
- Cache pair-keyed, not per-side: `test_escalate_caches_by_the_pair_not_either_side_alone`.
- `acquire_cache`'s contract holds under a non-empty cache: covered by the same test (the
  second `escalate()` call runs against the cache the first call populated).
- The four cache files named in the blast-radius measurement (SPY x FAMILY, JUJUTSU KAISEN,
  Reborn as a Vending Machine, One Pace) deleted from vm102's live `GLOSSARY_DIR`
  (`/home/claude/dubtitle-config/glossaries/`) -- nothing to migrate, since the old shape
  never stored a per-pair adjudication. Two more of the same old shape (One Pace,
  MARRIAGETOXIN) found and deleted from fasc's own local glossaries dir as the same class of
  now-stale file, though outside the originally-measured set.
- `ACQUIRE_NO_CACHE=1` removed from `gen_loop.sh`'s acquire invocation.

Full suite green (`.venv/bin/python -m pytest -q`), `ruff check .` clean. The existing
`test_end_to_end_admission_tagging_and_repair_weighting` fixture's `ACQUIRE_NO_CACHE=1`
workaround (needed under the old cache) was removed and the test still passes unmodified
otherwise -- direct confirmation the fix closes the gap that workaround existed for.
