# glossary_verify.plot_section_links Plot-section link extraction

Status: open
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

- [ ] `glossary_verify._extract_links()` exists, and `arc_page_links()`
      is refactored to call it (its own body no longer duplicates the
      filter).
- [ ] `glossary_verify.plot_section_links()` exists, matching the plan's
      Task 2 signature.
- [ ] `pytest tests/test_glossary_verify.py -k plot_section_links -q`
      passes all 4 new tests (Plot-only extraction, File:/Image: filter,
      no-heading case, case-insensitive heading).
- [ ] `pytest tests/test_glossary_verify.py -q` (whole file) passes,
      including every pre-existing `test_arc_page_links_*` test — proves
      the refactor changed nothing about `arc_page_links`'s behavior.
- [ ] `ruff check glossary_verify.py tests/test_glossary_verify.py`
      reports 0 findings.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the task open. -->
