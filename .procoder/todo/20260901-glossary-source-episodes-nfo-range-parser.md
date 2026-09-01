# glossary.source_episodes .nfo range parser

Status: open
Created: 2026-09-01

## Description

Task 1 of `.procoder/plans/per-episode-glossary-acquisition.md`
(implements spec `[S-1]`). A re-cut show like One Pace has no wiki page of
its own; its `.nfo` carries `Covers anime episode(s): 628 - 631`, the
absolute source-episode numbers the wiki DOES have pages for. This task
adds `glossary.source_episodes(nfo_path) -> list[int]`, a pure, regex-only
parser (no XML parser — `.nfo` files are untrusted third-party input,
matching `glossary.arc_for()`'s existing precedent) that turns that line
into `[628, 629, 630, 631]`. Done means the plan's Task 1 literal test
code is in the tree, passing, and the function handles range/comma/
single/mixed forms plus absence and malformed input without raising.

## Acceptance criteria

- [ ] `glossary.source_episodes()` exists in `glossary.py`, matching the
      plan's Task 1 signature and docstring.
- [ ] `pytest tests/test_glossary.py -k source_episodes -q` passes all 4
      tests from the plan (range, comma/single/mixed, absent/missing
      file, truncated file).
- [ ] `ruff check glossary.py tests/test_glossary.py` reports 0 findings.
- [ ] Full `pytest -q` still passes (no regression to existing
      `glossary.py` tests).

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the task open. -->
