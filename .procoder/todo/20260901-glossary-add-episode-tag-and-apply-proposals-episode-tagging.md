# glossary.add_episode_tag and apply_proposals episode tagging

Status: closed 2026-09-01
Created: 2026-09-01

## Description

Task 11 of `.procoder/plans/per-episode-glossary-acquisition.md`
(implements spec `[S-9]`). New `glossary.add_episode_tag(gloss, term,
episode_keys)` writes `gloss["episode_tags"][term.lower()]` (unioned,
sorted — same shape as `arc_tags`, but a direct write, not a
membership-discovery scan like `tag_names_by_arc`, since the caller
already knows exactly which episodes produced the proposal). Wired into
`apply_proposals()` via a new optional `episode_keys_by_stem` parameter.
**Load-bearing detail**: tags are keyed on the proposal's **canonical**
spelling, not the harvested variant — `repair._glossary_terms` iterates
`token_fixes`/`phrase_fixes` values (the split form of `hard_fixes`,
which `apply_proposals` writes keyed on variant with canonical as the
value), so tagging the variant would write a key `_glossary_terms` never
looks up. Depends on Tasks 6 and 8; its test only proves what it claims
once Task 7 (the `load_dict` fix) has also landed.

## Acceptance criteria

- [x] `glossary.add_episode_tag()` exists, matching the plan's Task 11
      signature; a second call for the same term unions rather than
      overwrites its episode-key list.
- [x] `apply_proposals()` accepts `episode_keys_by_stem` and tags the
      **canonical**, not the variant, confirmed by a test asserting the
      variant's lowercased form is absent from `episode_tags`.
- [x] `pytest tests/test_glossary.py tests/test_glossary_acquire.py -k "add_episode_tag or tags_episodes_keyed" -q`
      passes.
- [x] `pytest tests/test_glossary_acquire.py -q` (whole file) passes,
      including `test_apply_proposals_writes_hard_fixes_and_provenance`
      and every other pre-existing `apply_proposals` test unchanged —
      confirms the new parameter is additive and optional.
- [x] `ruff check glossary.py glossary_acquire.py tests/test_glossary.py tests/test_glossary_acquire.py`
      reports 0 findings.

## Evidence

- RED: `AttributeError: module 'glossary' has no attribute
'add_episode_tag'`; `TypeError: apply_proposals() got an unexpected
keyword argument 'episode_keys_by_stem'`.
- GREEN, plus one gap closed from Task 10 along the way:
  `admission_method` (S-12) had only been threaded onto the transient
  `acquire()` report, not the WRITTEN `acquired`/`flagged` glossary
  entry — added to `_provenance()` so it survives onto disk, per the
  spec's actual requirement (a reviewer must be able to tell a
  fallback-backed proposal from a tight one by reading the glossary
  file alone, not just the run's console output).
  `rtk proxy python3 -m pytest tests/test_glossary.py tests/test_glossary_acquire.py -q`
  → all passed.
- Full suite: `rtk proxy python3 -m pytest -q` → 100%, no failures.
- Lint: `rtk proxy ruff check glossary.py glossary_acquire.py tests/test_glossary.py tests/test_glossary_acquire.py`
  → "All checks passed!"
- Mutation check (mental): keying on `p["variant"]` instead of
  `p["canonical"]` is caught directly by
  `test_apply_proposals_tags_episodes_keyed_on_canonical`'s explicit
  "variant absent" assertion; omitting the `episode_keys_by_stem`
  guard is caught by the no-op test (`"episode_tags" not in g`).
- Committed: `7debd2c feat(glossary,glossary_acquire): tag an acquired
term's canonical with the episodes that produced it`.
