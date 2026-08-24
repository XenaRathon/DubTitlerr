# On an episode where `_clamp_to_segments` actually moved at least one word and at least one segment carries a non-zero `no_speech_prob`, a cached re-run from `words.json` produces cards **identical to the original run's**, including each card's `no_speech_prob` — asserted against the original production run, not against a second cache-shaped run.

Status: done 2026-08-24
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 2 of `.procoder/plans/v5-two-tier-idempotency.md`.

This is the criterion the external review flagged as the one most able to pass while the feature is broken. Per-segment `no_speech_prob` and the clamp bounds live only on segment dicts and cannot be recovered from the word list, so a cached replay that omits them silently produces different cards and zeroed confidences. Done means the replay is compared against the ORIGINAL production run on an episode where the transforms demonstrably fired — not against a second cache-shaped run, which would validate the bug.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] On an episode where `_clamp_to_segments` actually moved at least one word and at least one segment carries a non-zero `no_speech_prob`, a cached re-run from `words.json` produces cards **identical to the original run's**, including each card's `no_speech_prob` — asserted against the original production run, not against a second cache-shaped run.

## Evidence

- `test_a_replay_from_the_sidecar_reproduces_the_original_cards` compares the replay
  against the ORIGINAL `reflow.reflow(words, segments, audio_duration)` result -- not
  against a second replay-shaped run -- on start/end/text, `no_speech_prob` and
  `source_start`.
- `test_the_fixture_actually_exercises_clamping_and_nsp` guards the guard: it asserts
  `_clamp_to_segments` really moved the leading word (0.1s -> 1.0s) and that at least one
  card carries a non-zero nsp. Without it the round-trip could pass while proving nothing.
- `test_a_replay_without_segments_would_lose_the_confidences` pins WHY segments are
  persisted: with them a card reports nsp 0.42, without them every card reports 0.0 --
  which would silently disable the music drop rule and the maybe_silence flag.
- Design correction recorded in the commit and back-propagated to spec and plan: the
  words are stored PRE-transform, because reflow's three word transforms are pure and
  `_card_word_probs()` joins against the untransformed list, so post-transform storage
  would make the replay diverge for no gain.
- Suite: `1134 passed`. `procoder check`: 0 blocking. Commit `e4a9071`.

