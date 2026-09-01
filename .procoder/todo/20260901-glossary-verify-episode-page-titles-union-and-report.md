# glossary_verify.episode_page_titles union and report orchestrator

Status: open
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

- [ ] `glossary_verify.episode_page_titles()` exists, matching the plan's
      Task 5 signature.
- [ ] `pytest tests/test_glossary_verify.py -k episode_page_titles -q`
      passes: given one resolvable and one unresolvable page title, the
      union contains only the resolvable page's titles, and the
      unresolvable one is named in `failed_pages`, not silently dropped.
- [ ] `ruff check glossary_verify.py tests/test_glossary_verify.py`
      reports 0 findings.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the task open. -->
