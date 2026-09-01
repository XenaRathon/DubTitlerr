# end-to-end integration fixture for per-episode acquisition

Status: open
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

- [ ] The end-to-end fixture from the plan's Task 13 passes: no unrelated
      token widened by the unmapped episode's fallback;
      `admission_method`/`partial_pages` present and correct in the
      written glossary; a warm-cache second run makes no page-fetch HTTP
      calls; the reloaded glossary's `episode_tags` measurably changes
      `_glossary_terms`'s term order for the tagged episode versus an
      untagged one.
- [ ] Full `pytest -q` passes — 0 failures, 0 errors, across the whole
      suite.
- [ ] `ruff check .` reports 0 findings.
- [ ] `procoder check` reports 0 blocking findings.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the task open. -->
