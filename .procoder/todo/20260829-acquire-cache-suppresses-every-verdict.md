# Acquire cache: memoise the escalate adjudications, not the final verdicts

Status: open
Created: 2026-08-29
Interim shipped: `ACQUIRE_NO_CACHE=1` on dry runs in `gen_loop.sh`

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

- [ ] A dry run and an `--apply` run over the same corpus propose the SAME set of terms.
- [ ] Two consecutive dry runs report the same `proposed` count (today: 641 then 0).
- [ ] A cached escalate adjudication is reused — asserted on the LLM call count, not runtime.
- [ ] `acquire_cache`'s docstring contract ("must never change what the pipeline decides")
      holds under test, with a non-empty cache.
- [ ] The four remaining cache files are handled (deleted, or migrated to the new shape).
- [ ] The `ACQUIRE_NO_CACHE=1` interim is removed from `gen_loop.sh`.

## Evidence

Pending.
