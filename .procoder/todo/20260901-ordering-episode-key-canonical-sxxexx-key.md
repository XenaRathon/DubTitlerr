# ordering.episode_key canonical SxxExx key

Status: open
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

- [ ] `ordering.episode_key()` exists, matching the plan's Task 8
      signature.
- [ ] `pytest tests/test_ordering.py -k episode_key -q` passes: a
      zero-padded `"S20E01"`/`"S01E10"` for a real `SxxExx` path, `None`
      for a path with no season tag.
- [ ] `pytest tests/test_ordering.py -q` (whole file) passes.
- [ ] `ruff check ordering.py tests/test_ordering.py` reports 0 findings.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the task open. -->
