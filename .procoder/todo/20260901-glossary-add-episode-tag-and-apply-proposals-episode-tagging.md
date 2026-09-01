# glossary.add_episode_tag and apply_proposals episode tagging

Status: open
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

- [ ] `glossary.add_episode_tag()` exists, matching the plan's Task 11
      signature; a second call for the same term unions rather than
      overwrites its episode-key list.
- [ ] `apply_proposals()` accepts `episode_keys_by_stem` and tags the
      **canonical**, not the variant, confirmed by a test asserting the
      variant's lowercased form is absent from `episode_tags`.
- [ ] `pytest tests/test_glossary.py tests/test_glossary_acquire.py -k "add_episode_tag or tags_episodes_keyed" -q`
      passes.
- [ ] `pytest tests/test_glossary_acquire.py -q` (whole file) passes,
      including `test_apply_proposals_writes_hard_fixes_and_provenance`
      and every other pre-existing `apply_proposals` test unchanged —
      confirms the new parameter is additive and optional.
- [ ] `ruff check glossary.py glossary_acquire.py tests/test_glossary.py tests/test_glossary_acquire.py`
      reports 0 findings.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the task open. -->
