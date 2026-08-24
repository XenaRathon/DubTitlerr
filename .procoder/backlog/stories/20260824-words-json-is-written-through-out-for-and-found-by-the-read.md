# `words.json` is written through `out_for()` and found by the read path when `OUTPUT_ROOT` is set to a different directory; `SIDECAR_SUFFIXES` parks it.

Status: done 2026-08-24
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 2 of `.procoder/plans/v5-two-tier-idempotency.md`.

Writes redirect onto OUTPUT_ROOT while existence checks use the raw path, relying on mergerfs to unify them. If the new sidecar follows one convention on write and the other on read, the cache misses silently and every episode re-transcribes forever — a failure that would look like normal operation. Done means the sidecar is written and found with OUTPUT_ROOT pointed elsewhere, and that park_stale_sidecars knows its suffix.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `words.json` is written through `out_for()` and found by the read path when `OUTPUT_ROOT` is set to a different directory; `SIDECAR_SUFFIXES` parks it.

## Evidence

- `test_words_json_is_written_through_out_for_and_found_again` sets `MEDIA_ROOT` and
  `OUTPUT_ROOT` to different directories, then asserts the sidecar is NOT at the raw path
  (proving the write redirected) and that `read_words()` still finds it (proving the read
  follows the same convention). Following one convention on write and the other on read
  is a silent cache miss: `words_missing` forever while every episode re-transcribes and
  the pipeline looks healthy.
- `test_the_words_suffix_is_parked_with_the_other_sidecars` asserts `WORDS_SUFFIX` is in
  `generate.SIDECAR_SUFFIXES`, so `park_stale_sidecars` parks it; an unparked
  old-version sidecar would be read by the cached path.
- `test_the_sidecar_is_group_writable_and_atomic` asserts mode `common.SIDECAR_MODE`
  (0664) -- 0644 would mean only the creating uid could ever rewrite it.
- Suite: `1134 passed`. `procoder check`: 0 blocking. Commit `e4a9071`.

