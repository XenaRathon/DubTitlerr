# A v4 stamp (`{"version": 4, ...}`) parses, reports both tiers as 4, and raises nothing. With `TRANSCRIBE_VERSION = 4` / `TEXT_VERSION = 5`, it reports text-stale and transcribe-fresh — asserted on the real constants, so the assertion fails if adoption is ever set to 5/5.

Status: open
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 1 of `.procoder/plans/v5-two-tier-idempotency.md`.

The operator has 813 stamps written before tiers existed, 576 of them at v4. Splitting the version must not read those as stale: they are transcribe-fresh and only text-stale. Done means `stale_tiers()` returns `{"text"}` for a v4 stamp and `{"transcribe", "text"}` for a v2 one, and a test asserts the real adoption constants (4/5) so that setting them to 5/5 — which would burn roughly two GPU-days re-transcribing episodes whose audio never changed — fails loudly.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] A v4 stamp (`{"version": 4, ...}`) parses, reports both tiers as 4, and raises nothing. With `TRANSCRIBE_VERSION = 4` / `TEXT_VERSION = 5`, it reports text-stale and transcribe-fresh — asserted on the real constants, so the assertion fails if adoption is ever set to 5/5.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

