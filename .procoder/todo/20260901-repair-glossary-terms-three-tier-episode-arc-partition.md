# repair._glossary_terms three-tier episode/arc partition

Status: closed 2026-09-01
Created: 2026-09-01

## Description

Task 12 of `.procoder/plans/per-episode-glossary-acquisition.md`
(implements spec `[S-10]`). `_glossary_terms(gloss, arc=None,
episode=None)` becomes a 3-tier stable partition: episode-tagged terms
first, then arc-tagged terms not already placed, then everything else —
same 1000-char whole-term cap, same de-dup pass. Deliberately
**asymmetric** between the two tiers (the plan's own description had a
self-contradiction here, corrected during implementation): the arc tier
keeps its existing untagged-defaults-IN rule, but the episode tier does
**not** default an episode-untagged term in the way the arc tier does —
it simply falls through to the (unchanged) arc-tier logic below it. That
asymmetry is exactly what keeps `episode=None` byte-identical to today's
2-tier behavior: with the episode tier never populated, the rest of the
function runs exactly as it did before this parameter existed.
`build_prompt()` and `process()` thread the new `episode =
ordering.episode_key(video)` alongside the existing `arc` resolution.
Depends on Tasks 7 and 8 — its own tests use hand-built glossary dicts
(matching existing convention) so they don't directly exercise Task 7's
fix, but the feature is dead without it.

## Acceptance criteria

- [x] `_glossary_terms()` and `build_prompt()` both accept `episode=None`
      additively.
- [x] `pytest tests/test_repair.py -k "episode_tag_outranks or untagged_term_still or episode_none_matches" -q`
      passes: an episode-and-arc-tagged term outranks an arc-only-tagged
      term; an untagged term still appears; `episode=None` is
      byte-identical to omitting the argument.
- [x] `pytest tests/test_repair.py -q` (whole file) passes, including
      every pre-existing `_glossary_terms`/`build_prompt` test unchanged.
- [x] `ruff check repair.py tests/test_repair.py` reports 0 findings.

## Evidence

- RED: `rtk proxy python3 -m pytest tests/test_repair.py -k "episode_tag_outranks or episode_untagged_falls or untagged_term_still or episode_none_matches" -q`
  — 4 failed, `TypeError: _glossary_terms() got an unexpected keyword
argument 'episode'`.
- GREEN: also added
  `test_glossary_terms_episode_untagged_falls_through_to_arc_tier`,
  beyond the plan's original 3 tests, specifically to pin the
  asymmetric-tiers correction above (an episode-untagged,
  arc-tagged term must still outrank a different-arc term).
  `rtk proxy python3 -m pytest tests/test_repair.py -q` → all passed,
  including every pre-existing arc-tag test byte-identical.
- Full suite: `rtk proxy python3 -m pytest -q` → 100%, no failures.
- Lint: `rtk proxy ruff check repair.py tests/test_repair.py` → "All
  checks passed!"
- Mutation check (mental): defaulting an episode-untagged term IN (mirroring
  the arc tier's own rule) would be caught by
  `test_glossary_terms_episode_none_matches_today_2tier_behavior` — it
  would change term order for every existing 2-tier caller, breaking the
  identity assertion; swapping the episode/arc tier order would be caught
  by `test_glossary_terms_episode_tag_outranks_arc_tag`.
- Committed: `d986dcf feat(repair): weight the repair prompt by episode
tags ahead of arc tags`.
