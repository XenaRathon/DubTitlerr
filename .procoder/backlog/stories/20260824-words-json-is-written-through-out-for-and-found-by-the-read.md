# `words.json` is written through `out_for()` and found by the read path when `OUTPUT_ROOT` is set to a different directory; `SIDECAR_SUFFIXES` parks it.

Status: open
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 2 of `.procoder/plans/v5-two-tier-idempotency.md`.

Writes redirect onto OUTPUT_ROOT while existence checks use the raw path, relying on mergerfs to unify them. If the new sidecar follows one convention on write and the other on read, the cache misses silently and every episode re-transcribes forever — a failure that would look like normal operation. Done means the sidecar is written and found with OUTPUT_ROOT pointed elsewhere, and that park_stale_sidecars knows its suffix.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `words.json` is written through `out_for()` and found by the read path when `OUTPUT_ROOT` is set to a different directory; `SIDECAR_SUFFIXES` parks it.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

