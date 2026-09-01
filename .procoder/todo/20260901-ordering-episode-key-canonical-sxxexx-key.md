# ordering.episode_key canonical SxxExx key

Status: closed 2026-09-01
Created: 2026-09-01

## Description

Task 8 of `.procoder/plans/per-episode-glossary-acquisition.md` (support
for spec `[S-7]`/`[S-9]`/`[S-10]`). Adds
`ordering.episode_key(path) -> str | None`, formatting the existing
`season_ep()` (`ordering.py:31-36`, today used only for watch-order
sorting) into `"SxxExx"`, or `None` when there's no `SxxExx` in the
filename. One canonical stringification, shared by
`episode_admission_titles` (Task 9), `apply_proposals`'s episode tagging
(Task 11), and `repair.py`'s prompt weighting (Task 12) — so none of them
can spell the same episode's key differently. Small, independent, no
dependencies.

## Acceptance criteria

- [x] `ordering.episode_key()` exists, matching the plan's Task 8
      signature.
- [x] `pytest tests/test_ordering.py -k episode_key -q` passes: a
      zero-padded `"S20E01"`/`"S01E10"` for a real `SxxExx` path, `None`
      for a path with no season tag.
- [x] `pytest tests/test_ordering.py -q` (whole file) passes.
- [x] `ruff check ordering.py tests/test_ordering.py` reports 0 findings.

## Evidence

- RED: `rtk proxy python3 -m pytest tests/test_ordering.py -k episode_key -q`
  — 2 failed, `AttributeError: module 'ordering' has no attribute
'episode_key'`.
- GREEN: `rtk proxy python3 -m pytest tests/test_ordering.py -q` → 18
  passed. `ruff format` flagged one real docstring-quoting issue
  (`""""SxxExx"` needing a space before the leading quote) — fixed.
- Full suite: `rtk proxy python3 -m pytest -q` → 100%, no failures.
- Lint: `rtk proxy ruff check ordering.py tests/test_ordering.py` →
  "All checks passed!"; `ruff format --check ordering.py` → "1 file
  already formatted".
- Mutation check (mental): returning the raw `(s, e)` tuple instead of
  the formatted string, or skipping the `NO_SEASON` check, are both
  caught by the two tests' exact-value assertions.
- Committed: `90b30f2 feat(ordering): a canonical SxxExx episode key`.
