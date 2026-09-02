"""card_split: split a human correction across two cards when the single card it is
repairing is too narrow to hold it, but a legal split exists.

.procoder/todo/20260829-split-a-card-so-a-human-correction-fits.md. Scope settled
2026-09-02: human `correct`/`force` verdicts only (never a machine repair proposal,
which stays refused by fits_card exactly as today); `over_cps` refusals (the card was
already too fast before the human touched it) are explicitly OUT of scope and never
reach this module -- only `over_line_len`/`over_chars` shapes are fixed by splitting."""

import pytest

import card_split as cs
import reflow


def test_sentence_end_ranks_above_clause_end_and_word_boundary():
    """'Hi there. More.' has a sentence end after 'there.', a word boundary after 'Hi', and
    (with no comma) no clause end at all. The sentence end must be the first candidate."""
    candidates = cs._candidates("Hi there. More.")
    assert candidates[0] == len("Hi there. ")


def test_clause_end_ranks_above_plain_word_boundary():
    candidates = cs._candidates("Hi, there friend")
    assert candidates[0] == len("Hi, ")


def test_word_boundary_is_the_fallback_when_no_punctuation_exists():
    candidates = cs._candidates("one two three")
    assert candidates == [len("one "), len("one two ")]


# --- duration allocation ------------------------------------------------------


def test_duration_split_word_aligns_when_word_count_matches():
    """3 original words, corrected text also 3 words (2 + 1 across the split) -- reuse the
    ORIGINAL card's real timing for the cut point instead of guessing from characters."""
    words = [
        {"text": "one", "start": 0.0, "end": 2.0},
        {"text": "two", "start": 2.0, "end": 3.0},
        {"text": "three", "start": 3.0, "end": 4.0},
    ]
    dur1, dur2 = cs._duration_split("one two", "three", 4.0, words)
    avail = 4.0 - reflow.MIN_GAP
    expected_dur1 = (words[1]["end"] - words[0]["start"]) / (words[-1]["end"] - words[0]["start"]) * avail
    assert dur1 == pytest.approx(expected_dur1)
    assert dur2 == pytest.approx(avail - expected_dur1)


def test_duration_split_falls_back_to_proportional_when_word_count_differs():
    """The corrected text has 1+2=3 words but only 2 original words are supplied -- nothing
    to align position-for-position, so fall back to character share."""
    words = [{"text": "ab", "start": 0.0, "end": 3.0}, {"text": "cd", "start": 3.0, "end": 6.0}]
    dur1, dur2 = cs._duration_split("a", "b c", 6.0, words)
    avail = 6.0 - reflow.MIN_GAP
    total_chars = len("a") + len("b c")
    assert dur1 == pytest.approx(avail * len("a") / total_chars)
    assert dur2 == pytest.approx(avail * len("b c") / total_chars)


def test_duration_split_is_proportional_when_no_word_data_given():
    dur1, dur2 = cs._duration_split("ab", "abcd", 6.0, None)
    avail = 6.0 - reflow.MIN_GAP
    assert dur1 == pytest.approx(avail * 2 / 6)
    assert dur2 == pytest.approx(avail * 4 / 6)


# --- find_legal_split ----------------------------------------------------------
#
# Fixture verified directly against reflow, not guessed: at 10.0s the whole 84-char line
# wraps to a 44-char second line (over_line_len only -- no over_cps, keeping this test
# clear of the explicitly-out-of-scope fault). The sentence-boundary split gives two
# individually legal, single-line halves with zero layout faults.
_FULL_TEXT = "The captain ordered everyone to abandon ship at once. Nobody thought twice about it."
_HALF1 = "The captain ordered everyone to abandon ship at once."
_HALF2 = "Nobody thought twice about it."


def test_find_legal_split_splits_an_over_line_len_card_at_the_sentence_boundary():
    result = cs.find_legal_split(_FULL_TEXT, start=100.0, end=110.0, words=None)
    assert result is not None
    card1, card2 = result
    assert card1["text"] == _HALF1
    assert card2["text"] == _HALF2
    assert not reflow.layout_faults(reflow.wrap_balance(card1["text"]), card1["end"] - card1["start"])
    assert not reflow.layout_faults(reflow.wrap_balance(card2["text"]), card2["end"] - card2["start"])


def test_find_legal_split_places_min_gap_between_the_two_halves():
    card1, card2 = cs.find_legal_split(_FULL_TEXT, start=100.0, end=110.0, words=None)
    assert card2["start"] - card1["end"] == pytest.approx(reflow.MIN_GAP)
    assert card1["start"] == 100.0
    assert card2["end"] == 110.0


def test_find_legal_split_returns_none_when_the_card_is_too_short_for_any_split():
    """Even split in half, MIN_DUR (0.83s) cannot be cleared on a 1.0s card -- no legal
    split exists, and the caller's existing refusal path must still fire."""
    assert cs.find_legal_split(_FULL_TEXT, start=0.0, end=1.0, words=None) is None


def test_find_legal_split_tries_candidates_in_ranked_order_and_skips_degenerate_ones(monkeypatch):
    """_candidates ranks sentence end first; a candidate whose cut point produces an EMPTY
    second half (an out-of-range or trailing position) must be skipped, not accepted as a
    zero-length card, and the search must continue to the next-ranked candidate."""
    monkeypatch.setattr(cs, "_candidates", lambda text: [1000, len("legal part one ")])
    text = "legal part one legal part two"
    result = cs.find_legal_split(text, start=0.0, end=10.0, words=None)
    assert result is not None
    card1, _card2 = result
    assert card1["text"] == "legal part one"


def test_duration_split_falls_back_when_a_word_has_no_timing():
    """A word with start/end None (punctuation.restore can insert one) must not crash the
    alignment path -- fall back to proportional rather than raising."""
    words = [
        {"text": "one", "start": 0.0, "end": None},
        {"text": "two", "start": None, "end": 2.0},
    ]
    dur1, dur2 = cs._duration_split("one", "two", 4.0, words)
    avail = 4.0 - reflow.MIN_GAP
    total_chars = len("one") + len("two")
    assert dur1 == pytest.approx(avail * len("one") / total_chars)
    assert dur2 == pytest.approx(avail * len("two") / total_chars)
