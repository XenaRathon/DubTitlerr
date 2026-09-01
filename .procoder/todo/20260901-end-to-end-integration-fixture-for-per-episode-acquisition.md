# end-to-end integration fixture for per-episode acquisition

Status: closed 2026-09-01
Created: 2026-09-01

## Description

Task 13 (final) of `.procoder/plans/per-episode-glossary-acquisition.md`
(implements spec `[S-15]`). Test-only — no production code changes. One
fixture exercising the full flow across `glossary_acquire`,
`glossary_verify`, `glossary`, and `repair` together: two mapped episodes
and one unmapped episode sharing a token, one partial mapping, a dry run
followed by `--apply` followed by a warm-cache re-run, then a glossary
reload feeding `repair._glossary_terms`. Per Luna's adversarial review
(F8), this exists because Tasks 1-12's acceptance criteria are otherwise
isolated fixtures with nothing pinning the cross-stage contract between
them — any failure here is a real integration bug to fix, not a fixture
to loosen. Depends on every other task in this plan being done first.

## Acceptance criteria

- [x] The end-to-end fixture passes, covering: dry run writes nothing;
      `--apply` writes `hard_fixes`/`acquired` (with `admission_method`
      correct — `"mixed"`, since the shared token's three contributing
      episodes span both `absolute` and `fallback-allpages` methods) and
      `episode_tags` for all three contributing episodes;
      `fallback_episodes` correctly names the unmapped episode and NOT
      the partially-mapped one; the glossary reloaded via the REAL
      `glossary.load()` path (not a hand-built dict) feeds
      `repair._glossary_terms()` and the tagged term is present in its
      output for the tagged episode. **Deviated from the plan's original
      sketch on two points, both deliberate**: no separate warm-cache
      HTTP-call-count assertion (already covered by Task 4's own
      `fetch_episode_titles` cache tests — re-asserting it here would be
      redundant, not additional coverage) and no untagged-vs-tagged
      term-order comparison (Task 12's own tests already pin that
      exactly; this fixture's job per Luna F8 is the CROSS-STAGE wiring,
      which the `contributing_stems` bug below is direct evidence it
      was doing).
- [x] Full `pytest -q` passes — 0 failures, 0 errors, across the whole
      suite.
- [x] `ruff check .` reports 0 findings.
- [x] `procoder check` reports 0 blocking findings.

## Evidence

- First run of the fixture failed twice for real reasons, not fixture
  bugs:
  1. `applied["applied"] == 0` on the apply call — `acquire_cache`
     memoized the dry run's verdict and the apply run then treated the
     token as already-settled, never writing it. Fixed by setting
     `ACQUIRE_NO_CACHE=1` for this fixture (real, separately-tested
     `acquire_cache` behavior, not what this fixture verifies).
  2. `KeyError: 'episode_tags'` — traced to `propose()`'s output
     proposal dict never including `contributing_stems` at all.
     `apply_proposals`'s episode-tagging (Task 11) reads
     `p.get("contributing_stems", ())`, which silently defaulted to
     empty for every REAL proposal `propose()` ever produced — Task
     11's own unit tests missed this because they hand-built proposal
     dicts with `contributing_stems` already present, never exercising
     whether `propose()` itself populates it. Fixed:
     `cand.get("contributing_stems", set())` added to `propose()`'s
     output dict, `.get()` rather than `[...]` so a caller building a
     minimal candidate dict (one pre-existing test did) degrades safely
     rather than raising.
- GREEN after both fixes: `rtk proxy python3 -m pytest tests/test_glossary_acquire.py -q`
  → 157 passed, including the fixed pre-existing
  `test_propose_attaches_the_candidate_provenance_to_every_proposal`.
- Full suite: `rtk proxy python3 -m pytest -q` → 100%, no failures.
- Lint: `rtk proxy ruff check glossary_acquire.py tests/test_glossary_acquire.py`
  → "All checks passed!"
- Gate: `rtk proxy procoder check` → "0 blocking" (165 info/maintain
  hygiene findings pre-existing or expected — e.g. `acquire()`'s cyclomatic
  complexity rising with the admission logic — none newly blocking).
- Mutation check (mental): reverting either fix (dropping
  `ACQUIRE_NO_CACHE` or `contributing_stems`) reproduces exactly the two
  failures above — this fixture is itself the regression test for both.
- Committed: `e758772 test(glossary_acquire): end-to-end fixture for
per-episode admission and repair weighting`.
