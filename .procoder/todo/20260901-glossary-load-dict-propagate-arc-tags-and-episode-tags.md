# glossary.load_dict propagate arc_tags and episode_tags

Status: open
Created: 2026-09-01

## Description

Task 7 of `.procoder/plans/per-episode-glossary-acquisition.md`
(implements spec `[S-16]`). **Bug fix, discovered during implementation
planning, not requested by adversarial review**: `glossary.load_dict()`
(`glossary.py:66-84`) returns a dict listing exactly `show`, `names`,
`phrases`, `token_fixes`, `phrase_fixes`, `initial_prompt`,
`unanchored_repair` — `arc_tags` is not among them. `repair.py:process()`
resolves its working `gloss` via `glossary_for(video)` -> `glossary.load()`
-> `load_dict()`, and that exact `gloss` is what reaches
`_glossary_terms`, whose weighting reads `gloss.get("arc_tags")`. So in
production `_glossary_terms` never sees a populated `arc_tags`, regardless
of what the glossary JSON file on disk holds. Every existing arc-tag test
hand-builds its `gloss` dict with `arc_tags` set directly, bypassing
`load_dict` entirely — which is why this has never failed a test. This
means the already-shipped `arc-scoped-acquisition-and-per-season-prompt`
spec's season-weighted repair prompt has been unreachable in production
since it landed, not merely inert from low coverage as that spec's own
measurement concluded. Without this fix, this new spec's `episode_tags`
field would ship with the identical defect. Independent of every other
task — should land early since Tasks 11 and 12 depend on it being fixed
for their own tests to mean anything against the real code path.

## Acceptance criteria

- [ ] `load_dict()`'s returned dict includes `"arc_tags"` and
      `"episode_tags"`, each defaulting to `{}` when absent from the
      input config.
- [ ] `pytest tests/test_glossary.py -k "load_dict_propagates or load_reaches_repair" -q`
      passes, including the regression test that goes through the REAL
      `glossary.load(path)` -> `repair._glossary_terms()` path (not a
      hand-built dict) and confirms an arc-tagged term is actually
      reordered.
- [ ] `pytest tests/test_glossary.py tests/test_repair.py -q` (both
      files) passes, including every existing `_tagged_gloss()`-based
      arc-tag test in `test_repair.py` unchanged.
- [ ] `ruff check glossary.py tests/test_glossary.py` reports 0 findings.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the task open. -->
