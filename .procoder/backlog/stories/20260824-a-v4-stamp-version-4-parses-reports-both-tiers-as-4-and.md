# A v4 stamp (`{"version": 4, ...}`) parses, reports both tiers as 4, and raises nothing. With `TRANSCRIBE_VERSION = 4` / `TEXT_VERSION = 5`, it reports text-stale and transcribe-fresh — asserted on the real constants, so the assertion fails if adoption is ever set to 5/5.

Status: done 2026-08-24
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 1 of `.procoder/plans/v5-two-tier-idempotency.md`.

The operator has 813 stamps written before tiers existed, 576 of them at v4. Splitting the version must not read those as stale: they are transcribe-fresh and only text-stale. Done means `stale_tiers()` returns `{"text"}` for a v4 stamp and `{"transcribe", "text"}` for a v2 one, and a test asserts the real adoption constants (4/5) so that setting them to 5/5 — which would burn roughly two GPU-days re-transcribing episodes whose audio never changed — fails loudly.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] A v4 stamp (`{"version": 4, ...}`) parses, reports both tiers as 4, and raises nothing. With `TRANSCRIBE_VERSION = 4` / `TEXT_VERSION = 5`, it reports text-stale and transcribe-fresh — asserted on the real constants, so the assertion fails if adoption is ever set to 5/5.

## Evidence

- `python3 -m pytest tests/test_common.py -k "legacy_stamp or adoption or v2_stamp"` —
  `test_a_legacy_stamp_reads_both_tiers_from_its_single_version` proves a v4 stamp
  carrying only `version` reads as `{"text"}`; `test_a_v2_stamp_is_stale_in_both_tiers`
  proves a v2 one reads as both. Neither raises.
- `test_adoption_constants_do_not_retranscribe_the_library` asserts
  `TRANSCRIBE_VERSION == 4 and TEXT_VERSION == 5` on the real module constants, so
  adoption at 5/5 fails the suite rather than silently re-transcribing 576 episodes.
- `test_a_corrupt_tier_value_is_stale_not_an_exception` covers the hand-edited stamp:
  stale, not an exception, so one bad sidecar cannot abort a sweep.
- Behaviour checked against the shipped constants, not only fixtures:

      constants          : 4 5
      v4 legacy stamp    : ['text']                <- 576 live episodes
      v2 legacy stamp    : ['text', 'transcribe']  <- 236 live episodes
      fresh v5 stamp     : current
      no stamp           : ['text', 'transcribe']

- Full suite: `1123 passed` (was 1,114). `procoder check`: 0 blocking.
- Commit `1cb718a`.

