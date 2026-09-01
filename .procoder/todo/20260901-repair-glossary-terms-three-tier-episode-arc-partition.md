# repair._glossary_terms three-tier episode/arc partition

Status: open
Created: 2026-09-01

## Description

Task 12 of `.procoder/plans/per-episode-glossary-acquisition.md`
(implements spec `[S-10]`). `_glossary_terms(gloss, arc=None,
episode=None)` becomes a 3-tier stable partition: episode-tagged terms
first, then arc-tagged terms not already placed, then everything else —
same untagged-defaults-IN semantics independently for both tiers, same
1000-char whole-term cap, same de-dup pass. Deliberately asymmetric
versus the arc tier: an episode-untagged term is not defaulted into the
episode-first tier the way an arc-untagged term defaults into the arc
tier, so `episode=None` reproduces today's 2-tier behavior byte-for-byte.
`build_prompt()` and `process()` thread the new `episode =
ordering.episode_key(video)` alongside the existing `arc` resolution.
Depends on Tasks 7 and 8 — its own tests use hand-built glossary dicts
(matching existing convention) so they don't directly exercise Task 7's
fix, but the feature is dead without it.

## Acceptance criteria

- [ ] `_glossary_terms()` and `build_prompt()` both accept `episode=None`
      additively.
- [ ] `pytest tests/test_repair.py -k "episode_tag_outranks or untagged_term_still or episode_none_matches" -q`
      passes: an episode-and-arc-tagged term outranks an arc-only-tagged
      term; an untagged term still appears; `episode=None` is
      byte-identical to omitting the argument.
- [ ] `pytest tests/test_repair.py -q` (whole file) passes, including
      every pre-existing `_glossary_terms`/`build_prompt` test unchanged.
- [ ] `ruff check repair.py tests/test_repair.py` reports 0 findings.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the task open. -->
