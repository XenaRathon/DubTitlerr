# glossary_verify.plot_section_links Plot-section link extraction

Status: closed 2026-09-01
Created: 2026-09-01

## Description

Task 2 of `.procoder/plans/per-episode-glossary-acquisition.md`
(implements spec `[S-2]`). Measured 2026-08-29: a wiki EPISODE page's
Plot section yields 26-30 correct per-episode candidates versus 1,281+
franchise-wide, zero navbox pollution. This task adds
`glossary_verify.plot_section_links(wikitext) -> set[str]`, which slices
to the `== Plot ==` section and extracts `[[...]]` links, and extracts the
existing `arc_page_links` filter logic (template/ref strip,
Category:/File:/Image:/w: drop, bare Chapter/Episode/Volume N drop) into a
new shared private helper `_extract_links()` so the two functions cannot
drift. Done means `arc_page_links`'s own existing tests still pass
unchanged after the refactor, proving nothing broke.

## Acceptance criteria

- [x] `glossary_verify._extract_links()` exists, and `arc_page_links()`
      is refactored to call it (its own body no longer duplicates the
      filter).
- [x] `glossary_verify.plot_section_links()` exists, matching the plan's
      Task 2 signature.
- [x] `pytest tests/test_glossary_verify.py -k plot_section_links -q`
      passes all 4 new tests (Plot-only extraction, File:/Image: filter,
      no-heading case, case-insensitive heading).
- [x] `pytest tests/test_glossary_verify.py -q` (whole file) passes,
      including every pre-existing `test_arc_page_links_*` test — proves
      the refactor changed nothing about `arc_page_links`'s behavior.
- [x] `ruff check glossary_verify.py tests/test_glossary_verify.py`
      reports 0 findings.

## Evidence

- RED: `rtk proxy python3 -m pytest tests/test_glossary_verify.py -k plot_section_links -q`
  — 4 failed, `AttributeError: module 'glossary_verify' has no attribute
'plot_section_links'`.
- GREEN: `_extract_links()` factored out of `arc_page_links`'s existing
  body (byte-identical logic, just relocated), `plot_section_links()`
  added on top of it. `rtk proxy python3 -m pytest tests/test_glossary_verify.py -q`
  → 32 passed (all 4 new tests + all pre-existing `arc_page_links` tests
  unchanged).
- Full suite: `rtk proxy python3 -m pytest -q` → 100%, no failures.
- Lint: `rtk proxy ruff check glossary_verify.py tests/test_glossary_verify.py`
  → "All checks passed!" (caught and fixed one real issue mid-cycle: a
  leftover `return out` dead-code line from the pre-refactor function
  body, flagged as F821 undefined name).
- Mutation check (mental): a missing Plot-section slice (returning
  whole-page links) is caught by
  `test_plot_section_links_extracts_only_the_plot_section`'s assertion
  that Trivia-section and pre-heading content are excluded; a dropped
  File:/Image: filter is caught by
  `test_plot_section_links_filters_file_and_image_links`'s exact-set
  assertion.
- Committed: `6cabdf3 feat(glossary_verify): extract Plot-section links,
sharing arc_page_links' filter`.
