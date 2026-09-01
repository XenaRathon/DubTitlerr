# harvest_candidates contributing_stems provenance

Status: open
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

- [ ] `_candidate()` returns a dict including `"contributing_stems":
set()`, and `harvest_candidates()`'s per-episode loop adds the
      current stem to it for every token seen in that episode.
- [ ] `test_candidate_record_carries_source_and_forms` is updated to
      include `"contributing_stems"` in its exact-set assertion, and
      passes.
- [ ] `pytest tests/test_glossary_acquire.py -k "contributing_stems or carries_source_and_forms" -q`
      passes, including a token contributed by two episodes carrying both
      stems, and a single-episode token carrying exactly one.
- [ ] `pytest tests/test_glossary_acquire.py -q` (whole file) passes — no
      other test reads `_candidate`'s key set exhaustively and breaks.
- [ ] `ruff check glossary_acquire.py tests/test_glossary_acquire.py`
      reports 0 findings.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the task open. -->
