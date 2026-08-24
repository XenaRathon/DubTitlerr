# A glossary edit that changes only `hard_fixes` leaves `initial_prompt` byte-identical, marks **zero** episodes transcription-stale, and re-applies the correction to conf and srt through the card-text path. An edit that changes `initial_prompt` marks the episode transcription-stale. The count of newly-flagged episodes is asserted, not just the flag.

Status: done 2026-08-24
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 3 of `.procoder/plans/v5-two-tier-idempotency.md`.

`mine_glossary.py` appends hard_fixes on every sweep of a watched show, and those never reach `initial_prompt`. Hashing the glossary file would therefore re-queue an entire show for the GPU on edits that changed nothing about the decoder input — converting this spec's own motivating example back into the cost it exists to remove. Done means classification compares the stored prompt STRING, and the test asserts how many episodes were newly flagged, not merely that a flag moved.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] A glossary edit that changes only `hard_fixes` leaves `initial_prompt` byte-identical, marks **zero** episodes transcription-stale, and re-applies the correction to conf and srt through the card-text path. An edit that changes `initial_prompt` marks the episode transcription-stale. The count of newly-flagged episodes is asserted, not just the flag.

## Evidence

- `test_a_hard_fixes_only_edit_flags_nothing_for_the_gpu` asserts the COUNT, not the
  flag: a hard_fixes-only edit yields `tier is None` (zero episodes sent to the GPU)
  while `changed == 1` and the conf actually reads "He used Haki".
- `test_a_prompt_changing_edit_is_flagged_transcription_stale` — an initial_prompt edit
  yields `tier == "transcribe"` and still applies the correction, so a partial text fix
  cannot hide an out-of-date transcript.
- `test_an_episode_with_no_words_sidecar_is_transcription_stale` — the state all 813
  stamped episodes are in today; unknown provenance is not evidence of freshness.
- `test_show_for_matches_the_name_gen_loop_uses` pins the derivation against
  `gen_loop.sh`'s `SHOW_NAME="$show"`. A mismatch would build a prompt whisper never saw
  and mark every episode stale forever.
- `glossary.prompt_for()` is the single derivation; `generate.load_glossary()` now calls
  it, verified live: `generate.INITIAL_PROMPT == glossary.prompt_for(GLOSS, "One Pace")`.
- End-to-end CLI run on a fixture library:

      DRY RUN - 1 episode(s)
        cards changed         : 1
        transcription-stale   : 1   (initial_prompt changed -> needs the GPU)
          -  He used hockey to win
          +  He used Haki to win

- Suite: `1147 passed`. `procoder check`: 0 blocking. Commit `b2fd9c0`.

