# Bumping `TEXT_VERSION` alone leaves `stale_tiers()` free of `"transcribe"`; bumping `TRANSCRIBE_VERSION` marks both. Both constants' docstrings name the decoder-affecting settings that require a transcribe bump.

Status: done 2026-08-24
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 1 of `.procoder/plans/v5-two-tier-idempotency.md`.

The pipeline needs to decide which tier is behind without anyone remembering to set a flag. Done means a `TEXT_VERSION` bump marks only the text tier and a `TRANSCRIBE_VERSION` bump marks both, and both constants carry the ported bump manual naming the decoder-affecting settings — model, beam size, compute type, whisper thresholds, initial_prompt — because no mechanical signal detects a change to those.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] Bumping `TEXT_VERSION` alone leaves `stale_tiers()` free of `"transcribe"`; bumping `TRANSCRIBE_VERSION` marks both. Both constants' docstrings name the decoder-affecting settings that require a transcribe bump.

## Evidence

- `test_bumping_text_alone_never_marks_the_transcribe_tier` — with both tiers current
  on the stamp, bumping `TEXT_VERSION` yields exactly `{"text"}`. This is the property
  the whole split exists for: a text change never reaches the GPU.
- `test_bumping_transcribe_marks_both_tiers` — bumping `TRANSCRIBE_VERSION` yields
  `{"transcribe", "text"}`, because new words invalidate everything derived from them.
- `test_stamp_valid_is_exactly_nothing_stale` — `stamp_valid()` keeps its signature and
  meaning, so no caller had to move; it is now `not stale_tiers(...)`.
- Both constants' docstrings in `common.py` name the decoder-affecting settings that
  require a transcribe bump — the whisper model, `WHISPER_BEAM_SIZE`, compute type,
  whisper's thresholds, vad settings, and `initial_prompt` — and state plainly that
  nothing detects a change to them mechanically, so the comment is the only guard.
- `test_write_stamp_still_records_a_legacy_version_key` — `version` is still written
  (= `TEXT_VERSION`) so an older build and `scripts/migrate_write_v1_stamps.py` do not
  read new stamps as pre-versioning, which would re-transcribe the library.
- Full suite: `1123 passed`. `procoder check`: 0 blocking. Commit `1cb718a`.

