# wire per-token admission filtering into acquire

Status: closed 2026-09-01
Created: 2026-09-01

## Description

Task 10 of `.procoder/plans/per-episode-glossary-acquisition.md`
(implements spec `[S-8]`, `[S-12]`, `[S-13]`'s acquire-level half, and
`[S-14]`). The core of the whole spec: for each harvested token, builds
the admission set as the union of the per-episode title sets (Task 9) of
**only that token's own** `contributing_stems` (Task 6) — not one union
across the whole run's `scope`, which was the design the planning phase
found self-defeating (a single unmapped episode's fallback would
otherwise widen admission for every other episode's tokens too). Filters
`resolved` into `resolved_admitted` and passes it to **both** `propose()`
and `unmatched()` — corrected from an earlier spec draft that would have
kept `unmatched()` on the unfiltered dict, which (verified against
`unmatched()`'s real `t not in resolved` exclusion test) would make an
admission-rejected token invisible to both functions and silently drop
it entirely. Also adds `admission_method` per proposal, `nfo_present`/
`nfo_parsed`/`nfo_missing`/`nfo_parse_failed` counters and the
`nfo_parsed == 0` warning, and `fallback_episodes` on `acquire()`'s
return. Depends on Tasks 6 and 9.

## Acceptance criteria

- [x] Re-running the SAO dry-pass fixture no longer proposes
      `What -> Whale` / `Whose -> Horse` (the 2026-08-29 measurement's
      exact regression case).
- [x] A token whose only contributing episode is unmapped is admitted
      against the full title set (`admission_method="fallback"`); a
      DIFFERENT token harvested only from mapped episodes in the same
      run is NOT widened by that unrelated episode's fallback
      (`admission_method="tight"`) — the specific bug found during
      design.
- [x] A token contributed by both a mapped and an unmapped episode gets
      `admission_method="mixed"`.
- [x] An admission-rejected token (resolves against `allpages`, excluded
      from its episode's admitted set) still reaches
      `glossary_verify.adjudicate()` (tier-B) rather than vanishing.
- [x] A name exclusive to a missing source page in a partially-resolved
      episode also reaches tier-B, distinctly from a name that never
      resolves against `allpages` at all — both land in `adjudicated`,
      per the plan's dedicated partial-mapping test.
- [x] A run where every found `.nfo` fails to parse (`nfo_present > 0`,
      `nfo_parsed == 0`) emits a `WARNING` log line naming `.nfo`,
      captured via `capsys`.
- [x] `pytest tests/test_glossary_acquire.py -q` (whole file) passes,
      including every pre-existing test — confirms a show with neither
      pattern field declared is byte-identical to today.
- [x] `ruff check glossary_acquire.py tests/test_glossary_acquire.py`
      reports 0 findings.

## Evidence

- RED: `rtk proxy python3 -m pytest tests/test_glossary_acquire.py -k "admission_scoping_removes or per_token_union or admission_method_tight or tier_b or partial_mapping_exclusive or warns_when_nfo" -q`
  — 6 failed: `KeyError: 'admission_method'`/`'nfo_present'`, and the
  partial-mapping test failing because the admission-rejection mechanism
  didn't exist yet.
- GREEN, with two real test-authoring bugs found and fixed along the
  way (not implementation bugs):
  1. The acquire()-level tests write `conf.json` via `_write_conf` but
     never created a matching video file, so `common.find_video()`
     returned `None` and admission scoping silently no-opped for every
     episode (`if not video: continue`). Fixed by creating a real
     (empty) `.mkv` per written episode, matching Task 9's own test
     convention.
  2. `unmatched()`'s own contract is MID-SENTENCE tokens only
     (`t in midsentence`) — two fixture sentences put the target name
     as the FIRST word, so it was never mid-sentence regardless of
     whether the admission-rejection code was correct. Fixed by
     rewording the fixture text so the target name isn't
     sentence-initial. Caught by the test failing with the token simply
     absent from `adjudicated`, not by inspection.
     Also two mock-shape mismatches: an empty `episode_page_titles` mock
     return falls through to `fallback-allpages` rather than a tight
     admission that excludes the token (different code path); and
     `episode_page_titles` is called ONCE with ALL page titles together,
     not once per page — a mock checking for a single-page list never
     matched.
     `rtk proxy python3 -m pytest tests/test_glossary_acquire.py -q` → 156
     passed.
- Full suite: `rtk proxy python3 -m pytest -q` → 100%, no failures —
  confirms every show without a pattern field declared stays
  byte-identical.
- Lint: `rtk proxy ruff check glossary_acquire.py tests/test_glossary_acquire.py`
  → "All checks passed!"
- Mutation check (mental): swapping `resolved` for `resolved_admitted`
  back in either `propose()` or `unmatched()`'s call site would be
  caught by the admission-rejected/partial-mapping tests (the token
  would vanish from both, not reach `adjudicated`); reverting the
  per-token union to a per-run union would be caught by the
  cross-token-leak test (`Yolko`'s `admission_method` would flip from
  `"tight"` to `"mixed"`/`"fallback"`).
- Committed: `960b118 feat(glossary_acquire): scope wiki admission per
token, report fallback/partial provenance and .nfo health`.
