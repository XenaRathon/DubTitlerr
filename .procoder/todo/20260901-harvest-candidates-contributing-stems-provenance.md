# harvest_candidates contributing_stems provenance

Status: closed 2026-09-01
Created: 2026-09-01

## Description

Task 6 of `.procoder/plans/per-episode-glossary-acquisition.md`
(implements spec `[S-6]`). `_candidate()`/`harvest_candidates()`
(`glossary_acquire.py:246-294`) gain one new field,
`contributing_stems: set()`, populated by one added line inside the
existing per-episode loop — deliberately the LIGHT option (a set of which
episodes contributed a token, not full per-occurrence tracking), which is
what lets Task 10's per-token admission union work without a harvest
rewrite. Independent of any other task — can land first or in parallel.
**Important**: this task must also fix the existing exact-set assertion
in `tests/test_glossary_acquire.py::test_candidate_record_carries_source_and_forms`
(it currently asserts the full field-name set of `_candidate()`'s
return dict and will fail once a field is added — add
`"contributing_stems"` to that literal set as part of this task, not as
an unrelated follow-up).

## Acceptance criteria

- [x] `_candidate()` returns a dict including `"contributing_stems":
set()`, and `harvest_candidates()`'s per-episode loop adds the
      current stem to it for every token seen in that episode.
- [x] `test_candidate_record_carries_source_and_forms` is updated to
      include `"contributing_stems"` in its exact-set assertion, and
      passes.
- [x] `pytest tests/test_glossary_acquire.py -k "contributing_stems or carries_source_and_forms" -q`
      passes, including a token contributed by two episodes carrying both
      stems, and a single-episode token carrying exactly one.
- [x] `pytest tests/test_glossary_acquire.py -q` (whole file) passes — no
      other test reads `_candidate`'s key set exhaustively and breaks.
- [x] `ruff check glossary_acquire.py tests/test_glossary_acquire.py`
      reports 0 findings.

## Evidence

- RED: `rtk proxy python3 -m pytest tests/test_glossary_acquire.py -k "contributing_stems or carries_source_and_forms" -q`
  — 3 failed (`AssertionError` on the updated exact-set assertion,
  `KeyError: 'contributing_stems'` on the two new tests). One editing
  mistake along the way: an old_string match left two orphaned
  assertions from the original test body dangling inside a different,
  unrelated new test — caught immediately by ruff's F821 undefined-name
  finding before the run, fixed by moving them back to the right test.
- GREEN: `rtk proxy python3 -m pytest tests/test_glossary_acquire.py -q`
  → 146 passed.
- Full suite: `rtk proxy python3 -m pytest -q` → 100%, no failures.
- Lint: `rtk proxy ruff check glossary_acquire.py tests/test_glossary_acquire.py`
  → "All checks passed!"
- Mutation check (mental): forgetting the added line entirely is caught
  by both new tests (`KeyError`); adding the stem to the wrong
  candidate's set would be caught by the single-episode test's exact
  `{"Ep01"}` assertion.
- Committed: `686e64c feat(glossary_acquire): track which episodes
contributed each harvested token`.
