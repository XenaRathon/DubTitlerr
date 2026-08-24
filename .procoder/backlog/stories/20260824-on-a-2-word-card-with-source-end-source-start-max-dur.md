# On a 2-word card with `source_end - source_start > MAX_DUR`, `overlap_ref()` returns no reference and `_card_word_probs()` returns empty; both counters move. Unchanged on a 3-word card with the same window, and no activation recorded on a card with no `source_*` keys.

Status: open
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 6 of `.procoder/plans/v5-two-tier-idempotency.md`.

Whisper emits implausible word timestamps on music-masked audio, and two stages trust them: overlap_ref picks a fansub line from a 7-second window, and _card_word_probs inherits neighbouring cards' probabilities — measured at 20 of 401 gated cards. Done means both return nothing rather than falling back to the display window, which on 99% of gated cards is numerically identical to the window just declared invalid. Treat this as observability: the counters are the value.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] On a 2-word card with `source_end - source_start > MAX_DUR`, `overlap_ref()` returns no reference and `_card_word_probs()` returns empty; both counters move. Unchanged on a 3-word card with the same window, and no activation recorded on a card with no `source_*` keys.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

