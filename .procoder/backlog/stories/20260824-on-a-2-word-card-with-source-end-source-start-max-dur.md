# On a 2-word card with `source_end - source_start > MAX_DUR`, `overlap_ref()` returns no reference and `_card_word_probs()` returns empty; both counters move. Unchanged on a 3-word card with the same window, and no activation recorded on a card with no `source_*` keys.

Status: done 2026-08-24
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 6 of `.procoder/plans/v5-two-tier-idempotency.md`.

Whisper emits implausible word timestamps on music-masked audio, and two stages trust them: overlap_ref picks a fansub line from a 7-second window, and _card_word_probs inherits neighbouring cards' probabilities — measured at 20 of 401 gated cards. Done means both return nothing rather than falling back to the display window, which on 99% of gated cards is numerically identical to the window just declared invalid. Treat this as observability: the counters are the value.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] On a 2-word card with `source_end - source_start > MAX_DUR`, `overlap_ref()` returns no reference and `_card_word_probs()` returns empty; both counters move. Unchanged on a 3-word card with the same window, and no activation recorded on a card with no `source_*` keys.

## Evidence

- `hallucination.bad_source_window()` names the condition once; both call sites consult
  it BEFORE their `.get("source_start", c["start"])` default. A guard placed after the
  default would read the very fallback it exists to doubt — the mistake the VAD design
  records invalidating two of its own measurements.
- `tests/test_repair.py::test_process_takes_no_reference_from_an_implausible_source_window`
  drives the real `repair.process()`: an 8.0s span on a one-word card yields
  `skipped_no_ref == 1` and `rule_source_window_activated == 1`, with a fansub line
  deliberately placed inside the bad window to prove it is NOT selected.
- `test_process_still_anchors_a_plausible_window` — an ordinary card keeps its reference
  and reports `evaluated == 1, activated == 0`, which is what makes a dead rule visible.
- `test_card_word_probs_returns_nothing_for_an_implausible_window` — returns `[]`, not
  the display window; the plausible-window sibling still returns `[0.9]`.
- `test_a_card_with_three_words_is_left_alone` and
  `test_a_card_with_no_source_fields_is_never_a_bad_window` pin the scope: the guard must
  not widen silently, and must not fabricate a window it was never given.
- Neither site falls back to the display window. On 99% of gated cards
  `end == source_end` exactly, so a fallback reproduces the window just declared
  implausible and is wider on the displaced 1%.
- Suite: `1173 passed`. `procoder check`: 0 blocking. Commit `e397159`.

