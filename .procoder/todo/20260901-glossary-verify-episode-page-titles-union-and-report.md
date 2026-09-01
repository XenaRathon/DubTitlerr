# glossary_verify.episode_page_titles union and report orchestrator

Status: closed 2026-09-01
Created: 2026-09-01

## Description

Task 5 of `.procoder/plans/per-episode-glossary-acquisition.md`
(implements spec `[S-5]`). Thin orchestrator over Task 4's per-page
fetch: `episode_page_titles(wiki_api, show_key, page_titles) ->
(union, resolved_pages, failed_pages)`. The `resolved`/`failed` split is
what makes a partial mapping (some source episodes resolve, some don't)
reportable without a second pass over the same pages — feeds Task 9's
`episode_admission_titles` and Task 10's partial-mapping status. Depends
on Task 4.

## Acceptance criteria

- [x] `glossary_verify.episode_page_titles()` exists, matching the plan's
      Task 5 signature.
- [x] `pytest tests/test_glossary_verify.py -k episode_page_titles -q`
      passes: given one resolvable and one unresolvable page title, the
      union contains only the resolvable page's titles, and the
      unresolvable one is named in `failed_pages`, not silently dropped.
- [x] `ruff check glossary_verify.py tests/test_glossary_verify.py`
      reports 0 findings.

## Evidence

- RED: `rtk proxy python3 -m pytest tests/test_glossary_verify.py -k episode_page_titles -q`
  — 1 failed, `AttributeError: module 'glossary_verify' has no attribute
'episode_page_titles'`.
- GREEN: `rtk proxy python3 -m pytest tests/test_glossary_verify.py -q`
  → 41 passed.
- Full suite: `rtk proxy python3 -m pytest -q` → 100%, no failures.
- Lint: `rtk proxy ruff check glossary_verify.py tests/test_glossary_verify.py`
  → "All checks passed!"
- Mutation check (mental): a page whose fetch returns no titles being
  added to `resolved` instead of `failed` is caught by the test's exact
  split assertion; a union that includes a failed page's (empty) titles
  would still pass the union assertion by coincidence, but the resolved/
  failed lists are asserted independently and exactly, closing that gap.
- Committed: `ae35490 feat(glossary_verify): union episode-page titles,
reporting resolved vs failed pages`.
