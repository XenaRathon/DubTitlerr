"""Unit tests for reflow.py (A1). Pure functions, no whisper/CUDA needed."""
import pytest

import reflow


def mkword(text, start, end, prob=0.9, seg=0):
    return {"text": text, "start": start, "end": end, "prob": prob, "seg": seg}


def sentence(words, t0=0.0, dur=0.3, gap=0.1, seg=0, prob=0.9):
    """Build a list of word dicts laid out back-to-back from t0."""
    out, t = [], t0
    for w in words:
        out.append(mkword(w, t, t + dur, prob=prob, seg=seg))
        t += dur + gap
    return out


def lay(texts, dur=0.3, gaps=0.0, t0=0.0, seg=0, prob=0.9):
    """Build words with explicit per-position gaps. `gaps` is a scalar applied
    after every word, or a list of len(texts)-1 gaps (gap after word i)."""
    out, t = [], t0
    for i, w in enumerate(texts):
        out.append(mkword(w, t, t + dur, prob=prob, seg=seg))
        if i < len(texts) - 1:
            t += dur + (gaps if isinstance(gaps, (int, float)) else gaps[i])
    return out


# --- T1: scaffold / contracts ------------------------------------------------

def test_module_exposes_netflix_profile_constants():
    assert reflow.MAX_LINE == 42
    assert reflow.MAX_LINES == 2
    assert reflow.MAX_CHARS == 84
    assert reflow.MAX_CPS == 17.0
    assert reflow.MIN_DUR == 0.83
    assert reflow.MAX_DUR == 7.0
    assert reflow.GAP_MAX == 0.5


# --- T2: split_spans ---------------------------------------------------------

def test_split_spans_keeps_tightly_spaced_words_in_one_span():
    words = sentence(["a", "b", "c"], gap=0.1)
    spans = reflow.split_spans(words)
    assert len(spans) == 1
    assert [w["text"] for w in spans[0]] == ["a", "b", "c"]


def test_split_spans_breaks_on_gap_over_half_second():
    # "a b" then a 0.8s silence then "c d"
    words = [
        mkword("a", 0.0, 0.3), mkword("b", 0.4, 0.7),
        mkword("c", 1.5, 1.8), mkword("d", 1.9, 2.2),
    ]
    spans = reflow.split_spans(words)
    assert [[w["text"] for w in s] for s in spans] == [["a", "b"], ["c", "d"]]


def test_split_spans_gap_exactly_half_second_does_not_break():
    # gap == GAP_MAX is not "over" the threshold -> stays together
    words = [mkword("a", 0.0, 1.0), mkword("b", 1.5, 2.0)]
    assert len(reflow.split_spans(words)) == 1


def test_split_spans_empty_input():
    assert reflow.split_spans([]) == []


# --- T3: segment_span --------------------------------------------------------

def test_segment_span_splits_on_sentence_punctuation():
    span = sentence(["Hi", "there.", "Bye", "now!"])
    groups = reflow.segment_span(span)
    assert [[w["text"] for w in g] for g in groups] == [["Hi", "there."], ["Bye", "now!"]]


def test_segment_span_keeps_a_fitting_piece_whole():
    span = sentence(["short", "and", "sweet"])
    assert len(reflow.segment_span(span)) == 1


def test_segment_span_overflow_cuts_at_largest_pause():
    # 12 identical 7-char words = 95 chars (>84). Bigger gap after word 6.
    gaps = [0.05] * 11
    gaps[5] = 0.30          # the gap that closes a card (split index 6)
    span = lay(["alphaaa"] * 12, gaps=gaps)
    groups = reflow.segment_span(span)
    assert len(groups) == 2
    assert len(groups[0]) == 6


def test_segment_span_overflow_no_pause_cuts_at_clause():
    # all words abut (gap 0) -> no pause tier; a comma decides the break
    texts = ["alphaaa"] * 12
    texts[5] = "alphaa,"
    span = lay(texts, gaps=0.0)
    groups = reflow.segment_span(span)
    assert len(groups) == 2
    assert len(groups[0]) == 6


def test_segment_span_overflow_no_pause_no_clause_word_wraps_near_midpoint():
    span = lay(["alphaaa"] * 12, gaps=0.0)
    groups = reflow.segment_span(span)
    assert len(groups) == 2
    assert abs(len(groups[0]) - len(groups[1])) <= 1


def test_segment_span_overflow_by_duration_even_when_text_short():
    # short text but >7s spoken -> must still split (gap 0.4 <= 0.5 keeps one span)
    span = lay(["aaa", "aaa"], dur=3.5, gaps=[0.4])
    assert len(reflow.segment_span(span)) == 2


def test_segment_span_single_unsplittable_word_returned_as_is():
    span = [mkword("x" * 200, 0.0, 12.0)]   # too long AND too long-duration
    assert len(reflow.segment_span(span)) == 1


# --- T4: wrap_balance --------------------------------------------------------

def test_wrap_balance_short_text_stays_one_line():
    assert reflow.wrap_balance("short enough") == "short enough"


def test_wrap_balance_text_at_limit_stays_one_line():
    text = "x" * 42
    assert reflow.wrap_balance(text) == text


def test_wrap_balance_long_text_becomes_two_lines_each_within_limit():
    text = " ".join(["wordy"] * 12)   # 12*5 + 11 = 71 chars > 42
    out = reflow.wrap_balance(text)
    lines = out.split("\n")
    assert len(lines) == 2
    assert all(len(ln) <= reflow.MAX_LINE for ln in lines)
    assert out.replace("\n", " ") == text     # content + order preserved


def test_wrap_balance_splits_evenly():
    text = " ".join(["abcde"] * 10)    # 59 chars -> balanced 5/5
    a, b = reflow.wrap_balance(text).split("\n")
    assert abs(len(a) - len(b)) <= 5


def test_wrap_balance_single_overlong_word_returned_unwrapped():
    word = "z" * 60
    assert reflow.wrap_balance(word) == word    # nothing to split on, no crash


# --- T5: time_cards ----------------------------------------------------------

def test_time_cards_start_is_pinned_to_first_word_onset():
    groups = [sentence(["Hello", "world."], t0=3.2)]
    (start, _end), = reflow.time_cards(groups)
    assert start == 3.2


def test_time_cards_extends_short_card_to_minimum_duration():
    groups = [[mkword("Oh", 0.5, 0.7)]]      # 0.2s spoken, no trailing card
    (start, end), = reflow.time_cards(groups)
    assert end == pytest.approx(start + reflow.MIN_DUR)


def test_time_cards_extends_dense_card_for_reading_speed():
    groups = [[mkword("a" * 68, 1.0, 2.0)]]  # 68 chars / 17 cps = 4.0s needed
    (start, end), = reflow.time_cards(groups)
    assert end == pytest.approx(start + 68 / reflow.MAX_CPS)


def test_time_cards_never_exceeds_max_duration():
    groups = [[mkword("a" * 150, 0.0, 0.5)]]  # would want ~8.8s for cps
    (_start, end), = reflow.time_cards(groups)
    assert end == pytest.approx(reflow.MAX_DUR)


def test_time_cards_extension_capped_by_next_card_with_gap():
    groups = [[mkword("a" * 50, 0.0, 0.3)], [mkword("b", 1.5, 1.8)]]
    times = reflow.time_cards(groups)
    end0 = times[0][1]
    assert end0 == pytest.approx(1.5 - reflow.MIN_GAP)   # held off the next card


def test_time_cards_never_overlaps_next_card():
    groups = [[mkword("a" * 50, 0.0, 0.3)], [mkword("b" * 50, 1.5, 1.8)]]
    times = reflow.time_cards(groups)
    assert times[0][1] <= times[1][0] - reflow.MIN_GAP + 1e-9


# --- T6: card_confidence + reflow() + edges ----------------------------------

def test_card_confidence_avg_logprob_is_mean_word_logprob():
    import math
    words = [mkword("a", 0, 0.3, prob=0.9), mkword("b", 0.4, 0.7, prob=0.9)]
    segs = [{"start": 0, "end": 1, "no_speech_prob": 0.1}]
    avg, _ = reflow.card_confidence(words, segs)
    assert avg == pytest.approx(math.log(0.9))


def test_card_confidence_no_speech_prob_is_max_over_source_segments():
    words = [mkword("a", 0, 0.3, seg=0), mkword("b", 0.4, 0.7, seg=1)]
    segs = [{"no_speech_prob": 0.1}, {"no_speech_prob": 0.7}]
    _, nsp = reflow.card_confidence(words, segs)
    assert nsp == 0.7


def test_card_confidence_clamps_zero_probability():
    import math
    words = [mkword("a", 0, 0.3, prob=0.0)]
    segs = [{"no_speech_prob": 0.1}]
    avg, _ = reflow.card_confidence(words, segs)
    assert avg == pytest.approx(math.log(reflow.PROB_FLOOR))


def test_reflow_end_to_end_two_sentences_across_a_gap():
    words = sentence(["Hello", "there."], t0=0.0, seg=0) + \
        sentence(["General", "Kenobi."], t0=2.0, seg=1)
    segs = [{"no_speech_prob": 0.1}, {"no_speech_prob": 0.2}]
    cards = reflow.reflow(words, segs)
    assert [c["text"] for c in cards] == ["Hello there.", "General Kenobi."]
    assert cards[0]["no_speech_prob"] == 0.1 and cards[1]["no_speech_prob"] == 0.2
    assert all({"start", "end", "text", "avg_logprob", "no_speech_prob"} <= c.keys() for c in cards)
    assert cards[0]["start"] == 0.0


def test_reflow_tolerates_missing_word_timestamps():
    words = [mkword("Hi", None, None, seg=0), mkword("there.", 0.5, 0.8, seg=0)]
    segs = [{"no_speech_prob": 0.1}]
    cards = reflow.reflow(words, segs)        # must not raise
    assert len(cards) >= 1
    assert all(isinstance(c["start"], float) and isinstance(c["end"], float) for c in cards)


def test_reflow_drops_blank_cards():
    words = [mkword("   ", 0.0, 0.3, seg=0)]
    segs = [{"no_speech_prob": 0.1}]
    assert reflow.reflow(words, segs) == []


def test_reflow_clamps_word_timestamps_into_their_segment_bounds():
    # whisper's word DTW sometimes times a segment's leading words far too early;
    # those words must not strand into an orphan card shown long before the line.
    words = [
        {"text": "I", "start": 5.0, "end": 5.2, "prob": 0.9, "seg": 0},
        {"text": "must", "start": 5.3, "end": 5.5, "prob": 0.9, "seg": 0},
        {"text": "admit.", "start": 110.7, "end": 111.2, "prob": 0.9, "seg": 0},
    ]
    segs = [{"start": 110.5, "end": 111.5, "no_speech_prob": 0.1}]
    cards = reflow.reflow(words, segs)
    assert len(cards) == 1                 # not an orphaned "I must" at t=5
    assert cards[0]["start"] >= 110.5      # clamped into the segment, no early reveal
    assert cards[0]["text"] == "I must admit."


def test_reflow_dejitters_large_intra_segment_word_gap():
    # ONE segment whose leading words are mis-timed early while the body is ~105s
    # later (a real faster-whisper word-alignment artifact, words within bounds).
    # The leading cluster must be pulled forward, not stranded as an early card.
    words = [
        {"text": "I", "start": 5.11, "end": 5.67, "prob": 0.9, "seg": 0},
        {"text": "must", "start": 5.67, "end": 6.23, "prob": 0.9, "seg": 0},
        {"text": "admit.", "start": 110.71, "end": 111.20, "prob": 0.9, "seg": 0},
    ]
    segs = [{"start": 5.11, "end": 111.20, "no_speech_prob": 0.04}]
    cards = reflow.reflow(words, segs)
    assert len(cards) == 1
    assert cards[0]["text"] == "I must admit."
    assert cards[0]["start"] >= 108        # pulled up to the body, not shown at t=5


def test_reflow_no_tiny_fragment_from_small_intra_segment_gap():
    # a ~1.3s gap INSIDE one segment is an artifact, not a pause: the leading word
    # must join its body, not become a lone card (splits happen at segment gaps only).
    words = [
        {"text": "I", "start": 121.19, "end": 121.41, "prob": 0.9, "seg": 0},
        {"text": "couldn't", "start": 122.72, "end": 123.20, "prob": 0.9, "seg": 0},
        {"text": "win.", "start": 123.20, "end": 123.60, "prob": 0.9, "seg": 0},
    ]
    segs = [{"start": 121.19, "end": 123.60, "no_speech_prob": 0.1}]
    cards = reflow.reflow(words, segs)
    assert len(cards) == 1
    assert cards[0]["text"] == "I couldn't win."
    assert cards[0]["start"] >= 122.0     # leading "I" pulled to the body, no early reveal
