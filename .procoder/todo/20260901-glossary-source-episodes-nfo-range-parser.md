# glossary.source_episodes .nfo range parser

Status: closed 2026-09-01
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

- [x] `glossary.source_episodes()` exists in `glossary.py`, matching the
      plan's Task 1 signature and docstring.
- [x] `pytest tests/test_glossary.py -k source_episodes -q` passes all 4
      tests from the plan (range, comma/single/mixed, absent/missing
      file, truncated file).
- [x] `ruff check glossary.py tests/test_glossary.py` reports 0 findings.
- [x] Full `pytest -q` still passes (no regression to existing
      `glossary.py` tests).

## Evidence

TDD cycle followed: RED first (4 tests written against the plan's literal
code, run before any implementation existed).

- RED: `rtk proxy python3 -m pytest tests/test_glossary.py -k source_episodes -q`
  — 4 failed, all `AttributeError: module 'glossary' has no attribute
'source_episodes'` (the right reason — confirmed via the raw log, not
  the RTK-summarized output which misreported "No tests collected" on a
  stale cache; see note below).
- GREEN: same command after implementing `source_episodes()` in
  `glossary.py` — `rtk proxy python3 -m pytest tests/test_glossary.py -k source_episodes -q`
  → `....` (4 passed).
- Whole-file regression: `rtk proxy python3 -m pytest tests/test_glossary.py -q`
  → 39 passed.
- Full suite: `rtk proxy python3 -m pytest -q` → 100%, no failures.
- Lint: `rtk proxy ruff check glossary.py tests/test_glossary.py` →
  "All checks passed!"
- Gate: `procoder check` (via `rtk proxy`, see note) → 0 unformatted,
  0 blocking after the `.prettierignore` fix and `docs: none` ack.
- Mutation check (mental): wrong regex, off-by-one in the range
  expansion, or an unconditional `return []` are each caught by at least
  one of the 4 tests (range/comma/single/mixed all assert exact list
  contents, not just truthiness).
- Committed: `404e9ad feat(glossary): parse a re-cut episode's
.nfo source-episode mapping`.

Note: the RTK hook wrapping `pytest`/`git commit` gave stale/misleading
output twice during this task (a pytest run reporting "No tests
collected" against an old log, and a `git commit` gate rejecting a
state that a fresh standalone `procoder check` already showed clean).
`rtk proxy <cmd>` (raw, unfiltered) was used to get ground truth both
times and is what the commands above reflect.
