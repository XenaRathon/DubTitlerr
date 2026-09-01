# wire per-token admission filtering into acquire

Status: open
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

- [ ] Re-running the SAO dry-pass fixture no longer proposes
      `What -> Whale` / `Whose -> Horse` (the 2026-08-29 measurement's
      exact regression case).
- [ ] A token whose only contributing episode is unmapped is admitted
      against the full title set (`admission_method="fallback"`); a
      DIFFERENT token harvested only from mapped episodes in the same
      run is NOT widened by that unrelated episode's fallback
      (`admission_method="tight"`) — the specific bug found during
      design.
- [ ] A token contributed by both a mapped and an unmapped episode gets
      `admission_method="mixed"`.
- [ ] An admission-rejected token (resolves against `allpages`, excluded
      from its episode's admitted set) still reaches
      `glossary_verify.adjudicate()` (tier-B) rather than vanishing.
- [ ] A name exclusive to a missing source page in a partially-resolved
      episode also reaches tier-B, distinctly from a name that never
      resolves against `allpages` at all — both land in `adjudicated`,
      per the plan's dedicated partial-mapping test.
- [ ] A run where every found `.nfo` fails to parse (`nfo_present > 0`,
      `nfo_parsed == 0`) emits a `WARNING` log line naming `.nfo`,
      captured via `capsys`.
- [ ] `pytest tests/test_glossary_acquire.py -q` (whole file) passes,
      including every pre-existing test — confirms a show with neither
      pattern field declared is byte-identical to today.
- [ ] `ruff check glossary_acquire.py tests/test_glossary_acquire.py`
      reports 0 findings.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the task open. -->
