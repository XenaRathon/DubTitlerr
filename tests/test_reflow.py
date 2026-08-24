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
        mkword("a", 0.0, 0.3),
        mkword("b", 0.4, 0.7),
        mkword("c", 1.5, 1.8),
        mkword("d", 1.9, 2.2),
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
    gaps[5] = 0.30  # the gap that closes a card (split index 6)
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
    span = [mkword("x" * 200, 0.0, 12.0)]  # too long AND too long-duration
    assert len(reflow.segment_span(span)) == 1


# --- T3b: the pause tier must fire on a PAUSE, not on the largest noise gap ---
#
# Every inter-word gap in continuous speech is a few hundredths of a second. A gate of
# `gap > 0` therefore fires on essentially every piece, picking the largest of a set of
# indistinguishable noise values -- an arbitrary cut, and one that made the clause tier
# unreachable (it needed EVERY gap to be exactly 0.0). Measured: 22% of cards with no
# sentence punctuation still carry a comma the code could never consult.


def test_split_pause_floor_is_a_module_constant():
    assert reflow.SPLIT_PAUSE_MIN > 0
    assert reflow.SPLIT_PAUSE_MIN < reflow.GAP_MAX  # or the tier could never fire


def test_segment_span_splits_at_a_real_pause_among_noise_gaps():
    # 12 x 7-char words = 95 chars (>84). Jittery noise everywhere, one true pause.
    gaps = [0.02, 0.05, 0.03, 0.04, 0.02, 0.30, 0.03, 0.05, 0.02, 0.04, 0.03]
    groups = reflow.segment_span(lay(["alphaaa"] * 12, gaps=gaps))
    assert len(groups) == 2
    assert len(groups[0]) == 6  # the 0.30 s pause, not a noise peak


def test_segment_span_all_noise_gaps_falls_through_to_the_clause():
    """No gap here is a pause -- the largest (0.07) is noise. The comma must decide."""
    texts = ["alphaaa"] * 12
    texts[5] = "alphaa,"
    gaps = [0.03, 0.05, 0.02, 0.04, 0.06, 0.02, 0.03, 0.07, 0.02, 0.05, 0.04]
    groups = reflow.segment_span(lay(texts, gaps=gaps))
    assert len(groups) == 2
    assert len(groups[0]) == 6  # the comma, not the 0.07 gap at 8


def test_segment_span_all_noise_gaps_no_clause_falls_through_to_the_midpoint():
    gaps = [0.03, 0.05, 0.02, 0.04, 0.06, 0.02, 0.03, 0.07, 0.02, 0.05, 0.04]
    groups = reflow.segment_span(lay(["alphaaa"] * 12, gaps=gaps))
    assert len(groups) == 2
    assert abs(len(groups[0]) - len(groups[1])) <= 1  # character midpoint, tier 3


def test_segment_span_equal_pauses_tie_break_prefers_the_midpoint():
    # binary fractions only: the tie-break is an exact float comparison, so 0.02/0.3
    # laid out by accumulation would differ in the last bits and never actually tie.
    gaps = [0.03125] * 11
    gaps[2] = gaps[5] = 0.25  # two qualifying, exactly equal pauses: 3 and 6
    groups = reflow.segment_span(lay(["alphaaa"] * 12, dur=0.25, gaps=gaps))
    assert len(groups[0]) == 6  # 6 is nearer the midpoint (6.0) than 3


def test_segment_span_uniformly_slow_speech_has_no_standout_pause():
    """A fixed floor alone misjudges slow dialogue: every gap clears 0.2 s here, so none
    of them is a pause RELATIVE TO THIS PIECE. The comma decides instead."""
    texts = ["alphaaa"] * 12
    texts[5] = "alphaa,"
    gaps = [0.3] * 11
    gaps[7] = 0.35  # the largest gap, but not a pause RELATIVE to 0.3
    groups = reflow.segment_span(lay(texts, gaps=gaps))
    assert len(groups[0]) == 6  # the comma, not the 0.35 gap at index 8


# --- T4: wrap_balance --------------------------------------------------------


def test_wrap_balance_short_text_stays_one_line():
    assert reflow.wrap_balance("short enough") == "short enough"


def test_wrap_balance_text_at_limit_stays_one_line():
    text = "x" * 42
    assert reflow.wrap_balance(text) == text


def test_wrap_balance_long_text_becomes_two_lines_each_within_limit():
    text = " ".join(["wordy"] * 12)  # 12*5 + 11 = 71 chars > 42
    out = reflow.wrap_balance(text)
    lines = out.split("\n")
    assert len(lines) == 2
    assert all(len(ln) <= reflow.MAX_LINE for ln in lines)
    assert out.replace("\n", " ") == text  # content + order preserved


def test_wrap_balance_splits_evenly():
    text = " ".join(["abcde"] * 10)  # 59 chars -> balanced 5/5
    a, b = reflow.wrap_balance(text).split("\n")
    assert abs(len(a) - len(b)) <= 5


def test_wrap_balance_single_overlong_word_returned_unwrapped():
    word = "z" * 60
    assert reflow.wrap_balance(word) == word  # nothing to split on, no crash


# --- T5: time_cards ----------------------------------------------------------


def test_time_cards_start_is_pinned_to_first_word_onset():
    groups = [sentence(["Hello", "world."], t0=3.2)]
    ((start, _end),), _ = reflow.time_cards(groups)
    assert start == 3.2


def test_time_cards_extends_short_card_to_minimum_duration():
    groups = [[mkword("Oh", 0.5, 0.7)]]  # 0.2s spoken, no trailing card
    ((start, end),), _ = reflow.time_cards(groups)
    assert end == pytest.approx(start + reflow.MIN_DUR)


def test_time_cards_extends_dense_card_for_reading_speed():
    groups = [[mkword("a" * 68, 1.0, 2.0)]]  # 68 chars / 17 cps = 4.0s needed
    ((start, end),), _ = reflow.time_cards(groups)
    assert end == pytest.approx(start + 68 / reflow.MAX_CPS)


def test_time_cards_never_exceeds_max_duration():
    groups = [[mkword("a" * 150, 0.0, 0.5)]]  # would want ~8.8s for cps
    ((_start, end),), _ = reflow.time_cards(groups)
    assert end == pytest.approx(reflow.MAX_DUR)


def test_time_cards_extension_capped_by_next_card_with_gap():
    groups = [[mkword("a" * 50, 0.0, 0.3)], [mkword("b", 1.5, 1.8)]]
    times, _ = reflow.time_cards(groups)
    end0 = times[0][1]
    assert end0 == pytest.approx(1.5 - reflow.MIN_GAP)  # held off the next card


def test_time_cards_never_overlaps_next_card():
    groups = [[mkword("a" * 50, 0.0, 0.3)], [mkword("b" * 50, 1.5, 1.8)]]
    times, _ = reflow.time_cards(groups)
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
    words = sentence(["Hello", "there."], t0=0.0, seg=0) + sentence(["General", "Kenobi."], t0=2.0, seg=1)
    segs = [{"no_speech_prob": 0.1}, {"no_speech_prob": 0.2}]
    cards = reflow.reflow(words, segs)
    assert [c["text"] for c in cards] == ["Hello there.", "General Kenobi."]
    assert cards[0]["no_speech_prob"] == 0.1 and cards[1]["no_speech_prob"] == 0.2
    assert all({"start", "end", "text", "avg_logprob", "no_speech_prob"} <= c.keys() for c in cards)
    assert cards[0]["start"] == 0.0


def test_reflow_tolerates_missing_word_timestamps():
    words = [mkword("Hi", None, None, seg=0), mkword("there.", 0.5, 0.8, seg=0)]
    segs = [{"no_speech_prob": 0.1}]
    cards = reflow.reflow(words, segs)  # must not raise
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
    assert len(cards) == 1  # not an orphaned "I must" at t=5
    assert cards[0]["start"] >= 110.5  # clamped into the segment, no early reveal
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
    assert cards[0]["start"] >= 108  # pulled up to the body, not shown at t=5


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
    assert cards[0]["start"] >= 122.0  # leading "I" pulled to the body, no early reveal


# --- T7: epsilon and duration helpers ----------------------------------------


def test_eps_absorbs_json_round_trip_error():
    """A card the timer set to exactly start+MIN_DUR, re-derived from conf.json's
    3-decimal values, must NOT count as short. Real card from One Pace S30 -- 410 of
    the 1140 cards a naive `< MIN_DUR` flagged are this artifact, not a defect."""
    start, end = 257.42, 258.25  # verbatim from a shipped conf.json
    dur = end - start
    assert dur == 0.8299999999999841  # the artifact is real, not synthetic
    assert dur < reflow.MIN_DUR  # ...a naive comparison calls it short
    assert not reflow.is_short(dur)  # ...and is_short must not


def test_is_short_still_catches_a_real_runt():
    assert reflow.is_short(0.02)
    assert reflow.is_short(reflow.MIN_DUR - 0.01)


def test_card_cps_uses_visible_chars():
    assert reflow.card_cps("ab\ncd", 1.0) == 5.0  # newline counts as one space


# --- T8: is_orphan_group + orphan flag on cards -------------------------------


def test_single_word_group_from_a_previous_segment_is_an_orphan():
    g = [{"text": "Wait", "start": 10.0, "end": 10.2, "prob": 0.9, "seg": 0}]
    nxt = [{"text": "for", "start": 12.0, "end": 12.3, "prob": 0.9, "seg": 1}]
    assert reflow.is_orphan_group(g, nxt) is True


def test_a_legitimate_one_word_utterance_is_not_an_orphan():
    """'Yes.' spoken alone, in its own segment, with silence both sides."""
    g = [{"text": "Yes.", "start": 10.0, "end": 10.6, "prob": 0.9, "seg": 3}]
    nxt = [{"text": "I", "start": 14.0, "end": 14.2, "prob": 0.9, "seg": 4}]
    assert reflow.is_orphan_group(g, nxt) is False


def test_is_orphan_group_false_when_no_next_group():
    g = [{"text": "Wait", "start": 10.0, "end": 10.2, "prob": 0.9, "seg": 0}]
    assert reflow.is_orphan_group(g, None) is False


def test_is_orphan_group_false_when_next_group_same_segment():
    g = [{"text": "Wait", "start": 10.0, "end": 10.2, "prob": 0.9, "seg": 0}]
    nxt = [{"text": "for", "start": 12.0, "end": 12.3, "prob": 0.9, "seg": 0}]
    assert reflow.is_orphan_group(g, nxt) is False


def test_is_orphan_group_false_when_group_too_long():
    g = [
        {"text": "Wait", "start": 10.0, "end": 10.2, "prob": 0.9, "seg": 0},
        {"text": "right", "start": 10.3, "end": 10.5, "prob": 0.9, "seg": 0},
        {"text": "there", "start": 10.6, "end": 10.8, "prob": 0.9, "seg": 0},
    ]
    nxt = [{"text": "for", "start": 12.0, "end": 12.3, "prob": 0.9, "seg": 1}]
    assert reflow.is_orphan_group(g, nxt) is False


def _orphan_words():
    # seg 0: a complete sentence, then a stray "Wait" tacked on at the segment's
    # tail; seg 1 (after a >GAP_MAX silence) is the utterance "Wait" really belongs to.
    return [
        {"text": "Hello", "start": 0.0, "end": 0.3, "prob": 0.9, "seg": 0},
        {"text": "there.", "start": 0.4, "end": 0.7, "prob": 0.9, "seg": 0},
        {"text": "Wait", "start": 0.8, "end": 1.0, "prob": 0.9, "seg": 0},
        {"text": "for", "start": 1.6, "end": 1.9, "prob": 0.9, "seg": 1},
        {"text": "me.", "start": 2.0, "end": 2.3, "prob": 0.9, "seg": 1},
    ]


def _orphan_segments():
    return [
        {"start": 0.0, "end": 1.0, "no_speech_prob": 0.1},
        {"start": 1.6, "end": 2.3, "no_speech_prob": 0.1},
    ]


def test_orphan_flag_reaches_the_card():
    cards = reflow.reflow(_orphan_words(), _orphan_segments())
    assert any(c.get("orphan") for c in cards)


def test_reflow_end_to_end_two_sentences_across_a_gap_marks_no_orphans():
    # regression: the flag must be additive only -- unrelated existing scenarios
    # (no cross-segment stranded runt) stay unflagged.
    words = sentence(["Hello", "there."], t0=0.0, seg=0) + sentence(["General", "Kenobi."], t0=2.0, seg=1)
    segs = [{"no_speech_prob": 0.1}, {"no_speech_prob": 0.2}]
    cards = reflow.reflow(words, segs)
    assert all(c.get("orphan") is False for c in cards)


def test_fragment_after_an_unfinished_clause_is_not_an_orphan():
    """A short fragment trailing an UNFINISHED clause may be its continuation, so it
    must stay mergeable. Only timing distinguishes this from the orphan case above --
    which is why the predicate consults the predecessor's punctuation, not just gaps."""
    prev = [
        {"text": "I", "start": 0.0, "end": 0.2, "prob": 0.9, "seg": 0},
        {"text": "went", "start": 0.3, "end": 0.6, "prob": 0.9, "seg": 0},
    ]
    group = [{"text": "home", "start": 0.7, "end": 0.9, "prob": 0.9, "seg": 0}]
    nxt = [{"text": "Later", "start": 3.0, "end": 3.4, "prob": 0.9, "seg": 1}]
    assert reflow.is_orphan_group(group, nxt, prev) is False


def test_fragment_after_a_finished_sentence_is_an_orphan():
    """Same timing, but the predecessor is complete -- nothing can continue it."""
    prev = [
        {"text": "I", "start": 0.0, "end": 0.2, "prob": 0.9, "seg": 0},
        {"text": "went.", "start": 0.3, "end": 0.6, "prob": 0.9, "seg": 0},
    ]
    group = [{"text": "Wait", "start": 0.7, "end": 0.9, "prob": 0.9, "seg": 0}]
    nxt = [{"text": "for", "start": 3.0, "end": 3.4, "prob": 0.9, "seg": 1}]
    assert reflow.is_orphan_group(group, nxt, prev) is True


def test_fragment_split_from_its_predecessor_by_a_pause_is_an_orphan():
    """Unfinished predecessor, but a real pause separates them -- not a continuation."""
    prev = [
        {"text": "I", "start": 0.0, "end": 0.2, "prob": 0.9, "seg": 0},
        {"text": "went", "start": 0.3, "end": 0.6, "prob": 0.9, "seg": 0},
    ]
    group = [{"text": "Wait", "start": 2.0, "end": 2.2, "prob": 0.9, "seg": 0}]
    nxt = [{"text": "for", "start": 5.0, "end": 5.4, "prob": 0.9, "seg": 1}]
    assert reflow.is_orphan_group(group, nxt, prev) is True


# --- T9: merge_runts (backward merge of too-short groups) --------------------


def _two_groups(gap, pred_text, runt_text, pd, rd, seg=0):
    """Two single-"word" groups: a predecessor spanning [0, pd] and a runt
    starting `gap` after it, spanning `rd`. Internal word-splitting doesn't
    matter to merge legality -- only total text length and the extreme
    timestamps do -- so one word per group keeps the arithmetic exact."""
    p = [mkword(pred_text, 0.0, pd, seg=seg)]
    start = pd + gap
    r = [mkword(runt_text, start, start + rd, seg=seg)]
    return [p, r]


def _two_shorts(pd, rd, gap):
    return _two_groups(gap, "Hi", "Bye", pd, rd)


def _corpus_like_groups():
    """Four groups, same segment throughout (so orphan detection never engages):
    a normal sentence, two short runts in a row (each legally mergeable, the
    second only once the first has already been absorbed into the predecessor),
    and a final normal sentence separated by a real pause."""
    g0 = [mkword("Hello there.", 0.0, 1.0, seg=0)]
    g1 = [mkword("Wait", 1.08, 1.28, seg=0)]
    g2 = [mkword("for", 1.36, 1.56, seg=0)]
    g3 = [mkword("General Kenobi.", 2.16, 3.16, seg=0)]
    return [g0, g1, g2, g3]


def _orphan_then_utterance():
    """Same shape as _orphan_words()/_orphan_segments() above, but as groups:
    a finished sentence, then a short fragment ("Wait") that is an orphan --
    its true utterance ("for me.") starts in the next segment after a real
    pause. The orphan guard must keep "Wait" from merging into "Hello there."
    even though it is short and otherwise legal."""
    g0 = [mkword("Hello", 0.0, 0.3, seg=0), mkword("there.", 0.4, 0.7, seg=0)]
    g1 = [mkword("Wait", 0.8, 1.0, seg=0)]
    g2 = [mkword("for", 1.6, 1.9, seg=1), mkword("me.", 2.0, 2.3, seg=1)]
    return [g0, g1, g2]


CASES = [  # (gap, pred_text, runt_text, pred_dur, runt_dur, should_merge, why)
    (0.08, "It's a", "monster.", 1.0, 0.30, True, "ordinary sentence tail"),
    (0.60, "It's a", "monster.", 1.0, 0.30, False, "gap exceeds GAP_MAX"),
    # NB: this row is 79 chars -- UNDER MAX_CHARS. It is rejected at 57 cps. Kept as a
    # valid rejection, relabelled honestly; the row below is what isolates MAX_CHARS.
    (0.08, "x" * 70, "monster.", 1.0, 0.30, False, "short+dense: rejected on cps"),
    # 89 chars (over 84) at 16.5 cps and 5.38s span -- both other gates pass, so only
    # MAX_CHARS can reject it. Without this the MAX_CHARS gate is never exercised.
    (0.08, "x" * 80, "monster.", 5.0, 0.30, False, "merged text over MAX_CHARS"),
    (0.08, "It's a", "monster.", 6.9, 0.30, False, "merged span over MAX_DUR"),
    (0.08, "a" * 30, "b" * 20, 2.0, 0.30, False, "merged cps over MAX_CPS"),
    (0.08, "Done.", "Next.", 1.0, 0.30, True, "sentence-integrity is a PREFERENCE"),
]


@pytest.mark.parametrize("gap,pred,runt,pd,rd,expect,why", CASES)
def test_merge_legality(gap, pred, runt, pd, rd, expect, why):
    groups = _two_groups(gap, pred, runt, pd, rd)
    out, merges = reflow.merge_runts(groups)
    assert (len(out) == 1) is expect, why


def test_merge_is_idempotent():
    g = _corpus_like_groups()
    once, _ = reflow.merge_runts(g)
    twice, m2 = reflow.merge_runts(once)
    assert twice == once and m2 == []


def test_merge_preserves_every_word_in_order():
    g = _corpus_like_groups()
    out, _ = reflow.merge_runts(g)
    assert [w["text"] for grp in out for w in grp] == [w["text"] for grp in g for w in grp]


def test_orphan_is_never_merged_backward():
    groups = _orphan_then_utterance()
    out, merges = reflow.merge_runts(groups)
    # NOTE: with merges == [] the output group count can only equal the input
    # count (3) -- merge_runts never drops groups, it only merges or keeps them.
    # The brief's draft asserted len(out) == 2, which is unreachable whenever
    # merges == [] on a 3-group input; see task-6-report.md.
    assert len(out) == 3 and merges == []


def test_two_short_groups_may_merge_and_still_be_short():
    """Both parts 0.20s -> merged 0.40s, still under MIN_DUR. Not a failure:
    Task 7 handles it. (Rejected groq A1-E1 claimed this could not happen.)"""
    out, merges = reflow.merge_runts(_two_shorts(0.20, 0.20, gap=0.05))
    assert len(out) == 1
    assert reflow.is_short(out[0][-1]["end"] - out[0][0]["start"])


def test_merge_log_collects_merge_records_from_reflow():
    """generate.py needs the per-episode merge count for the QC sidecar
    (merged_backward). reflow() takes an optional out-param so the public
    return type (a plain list of cards) never changes for existing callers."""
    words = sentence(["Fine."], t0=0.0, dur=1.0, gap=0.08, seg=0) + sentence(["Monster."], t0=1.08, dur=0.30, seg=0)
    segs = [{"no_speech_prob": 0.1}]
    log = []
    cards = reflow.reflow(words, segs, merge_log=log)
    assert len(cards) == 1
    assert len(log) == 1
    assert log[0]["reason"] == "runt_backward_merge"


# --- T10: time_cards forward steal + cascade ---------------------------------


def _overlapping_pair(pred_end=0.083, succ_start=0.050):
    """The shipped defect, in shape: the degenerate branch ends the predecessor at
    start+MIN_GAP without ever consulting the successor, so it ends AFTER the
    successor starts -- 9 such pairs ship today ('Huh.' running -0.083s into
    "Let's be honest."). Shifting by the MIN_DUR extension delta alone preserves the
    overlap; the pre-existing gap deficit has to be absorbed too."""
    return [[mkword("Huh.", 0.0, pred_end, seg=0)], [mkword("Let's be honest.", succ_start, succ_start + 1.4, seg=1)]]


def _runt_then_long(runt_dur=0.10, gap=0.05, succ_dur=2.85):
    """A runt whose successor carries surplus duration: the successor absorbs the
    whole shift by simply getting shorter, so its END must not move."""
    t = runt_dur + gap
    return [[mkword("Oh", 0.0, runt_dur, seg=0)], [mkword("A much longer line here.", t, t + succ_dur, seg=0)]]


def _runt_then_tight_chain(n=3):
    """A runt followed by cards that are exactly MIN_DUR long, exactly MIN_GAP
    apart: zero surplus and zero gap slack anywhere, so the shift has to travel."""
    groups = [[mkword("Oh", 0.0, 0.10, seg=0)]]
    t = 0.15
    for i in range(n):
        groups.append([mkword(f"Line {i}.", t, t + reflow.MIN_DUR, seg=0)])
        t += reflow.MIN_DUR + reflow.MIN_GAP
    return groups


def _single_short_group():
    return [[mkword("Oh", 0.1, 0.2, seg=0)]]


def _dense_no_slack_chain():
    """The tight chain, tailed by a runt that ends just shy of a 3.0s audio track:
    every card is inside the media, and there is nowhere for a shift to go."""
    groups = _runt_then_tight_chain(3)
    groups.append([mkword("Last.", 2.889, 2.99, seg=0)])
    return groups


def _shifted(groups, dt):
    return [[{**w, "start": w["start"] + dt, "end": w["end"] + dt} for w in g] for g in groups]


def _mixed_corpus():
    return (
        _overlapping_pair()
        + _shifted(_runt_then_long(), 10.0)
        + _shifted(_runt_then_tight_chain(3), 20.0)
        + [[mkword("The end.", 30.0, 31.5, seg=9)]]
    )


def test_steal_absorbs_a_preexisting_overlap_not_just_the_deficit():
    """The 9 live overlaps: predecessor ends AFTER successor starts."""
    groups = _overlapping_pair(pred_end=0.083, succ_start=0.050)
    times, _ = reflow.time_cards(groups)
    for (a, b), (c, _d) in zip(times, times[1:]):
        assert a < b
        assert c - b >= reflow.MIN_GAP - reflow.EPS
    assert times[0][1] - times[0][0] >= reflow.MIN_DUR - reflow.EPS


def test_the_cascade_record_names_the_preexisting_deficit():
    _, records = reflow.time_cards(_overlapping_pair())
    assert records[0]["preexisting_gap_deficit"] > 0  # the shipped overlap, +MIN_GAP


def test_surplus_successor_terminates_the_cascade_in_one_hop():
    times, records = reflow.time_cards(_runt_then_long())
    assert records[0]["hops"] == 1
    assert times[1][1] == pytest.approx(_runt_then_long()[1][-1]["end"], abs=1e-6)  # end unmoved
    assert times[1][0] > _runt_then_long()[1][0]["start"]  # start moved


def test_zero_surplus_successor_propagates():
    _, records = reflow.time_cards(_runt_then_tight_chain())
    assert records[0]["hops"] > 1


def test_last_card_runt_extends_but_never_past_the_audio():
    times, _ = reflow.time_cards(_single_short_group(), audio_duration=0.5)
    assert times[-1][1] <= 0.5 + reflow.EPS
    assert times[-1][0] < times[-1][1]


def test_infeasible_cascade_raises_rather_than_emitting_junk():
    with pytest.raises(reflow.CascadeInfeasible) as e:
        reflow.time_cards(_dense_no_slack_chain(), audio_duration=3.0)
    assert e.value.requested == pytest.approx(e.value.applied + e.value.residual, abs=1e-6)
    assert e.value.residual > 0


def test_dense_chain_is_feasible_when_the_audio_length_is_unknown():
    times, _ = reflow.time_cards(_dense_no_slack_chain())  # audio_duration=None
    for (_a, b), (c, _d) in zip(times, times[1:]):
        assert c - b >= reflow.MIN_GAP - reflow.EPS


def test_steal_never_reveals_a_card_earlier_than_its_onset():
    """Late is acceptable, early is not -- an early caption spoils its own line."""
    groups = _runt_then_tight_chain(4)
    times, _ = reflow.time_cards(groups)
    for (start, _end), g in zip(times, groups):
        assert start >= g[0]["start"] - reflow.EPS


def test_the_whole_stream_satisfies_the_profile_after_stealing():
    times, records = reflow.time_cards(_mixed_corpus())
    for start, end in times:
        assert start < end
        assert end - start >= reflow.MIN_DUR - reflow.EPS
    for (_a, b), (c, _d) in zip(times, times[1:]):
        assert c - b >= reflow.MIN_GAP - reflow.EPS
    assert records
    for r in records:
        assert r["requested_shift"] > reflow.EPS
        assert r["hops"] >= 1


def test_a_cascade_record_carries_the_duration_each_hop_found():
    """B1's event schema names dur_before, and it is unrecoverable from the finished
    timings: a displaced card whose end had to move ends at exactly MIN_DUR whatever it
    was before. The cascade is the only place that still knows."""
    groups = [[mkword("Oh.", 0.0, 0.10, seg=0)], [mkword("A much longer line here.", 0.15, 3.0, seg=0)]]
    times, records = reflow.time_cards(groups)
    assert len(records) == 1
    r = records[0]
    assert set(r["dur_before"]) == set(r["displaced"])
    assert r["dur_before"][1] == pytest.approx(2.85, abs=reflow.EPS)  # 3.0 - 0.15, pre-steal
    assert times[1][1] - times[1][0] < r["dur_before"][1]  # it really lost time


def test_a_successful_steal_records_only_what_it_can_measure():
    """applied_shift and residual_shift were constants wearing meaningful names. _cascade
    returns its ORIGINAL request on every success path, so every forward_steal record
    carried applied == requested and residual == 0.0 -- zero nonzero residuals over
    thousands of generated streams. A future aggregate reporter would read them and
    conclude "steals always fully fit", a claim the fields are incapable of making.

    They stay on CascadeInfeasible, where the two really do differ and the identity is a
    live invariant rather than an arithmetic restatement."""
    times, records = reflow.time_cards(_mixed_corpus())
    assert records
    for r in records:
        assert "applied_shift" not in r
        assert "residual_shift" not in r
        assert r["requested_shift"] > reflow.EPS and r["hops"] >= 1
    groups = [[mkword("Oh.", 0.0, 0.02, seg=0)], [mkword("And then this.", 0.05, 0.9, seg=0)]]
    with pytest.raises(reflow.CascadeInfeasible) as ei:
        reflow.time_cards(groups, audio_duration=0.5)
    e = ei.value
    assert e.residual > reflow.EPS and e.applied >= 0.0
    assert e.requested == pytest.approx(e.applied + e.residual, abs=reflow.EPS)


def test_a_stream_that_needs_nothing_records_no_cascades():
    groups = [[mkword("Hello there.", 0.0, 1.2, seg=0)], [mkword("General Kenobi.", 2.0, 3.4, seg=0)]]
    times, records = reflow.time_cards(groups)
    assert records == []
    assert times == [(0.0, 1.2), (2.0, 3.4)]


# --- T11: source timing vs display timing (C6) -------------------------------


def _runt_then_surplus_words():
    """A runt that has to steal time forward, followed by a card with the surplus to
    give it: the successor's DISPLAY start moves later, its spoken onset does not."""
    return [mkword("Oh.", 0.0, 0.10, seg=0), mkword("A much longer line here.", 0.15, 3.0, seg=0)]


def test_reflow_emits_the_spoken_span_as_the_source_window():
    words = _runt_then_surplus_words()
    segs = [{"start": 0.0, "end": 3.0, "no_speech_prob": 0.1}]
    cards = reflow.reflow(words, segs)
    assert len(cards) == 2
    assert (cards[0]["source_start"], cards[0]["source_end"]) == (0.0, 0.10)
    assert (cards[1]["source_start"], cards[1]["source_end"]) == (0.15, 3.0)


def test_source_start_is_the_onset_even_when_the_display_start_was_stolen_forward():
    """Task 7 pushes a successor's display start later; the audio it describes did not
    move, so repair must still be able to find the evidence window."""
    words = _runt_then_surplus_words()
    segs = [{"start": 0.0, "end": 3.0, "no_speech_prob": 0.1}]
    cards = reflow.reflow(words, segs)
    assert cards[1]["start"] > cards[1]["source_start"] + reflow.EPS  # displaced
    assert cards[1]["source_start"] == 0.15  # onset unmoved


def test_source_end_ignores_the_readability_extension():
    """A short card's display end is extended into trailing silence; the spoken span is
    not."""
    words = [mkword("Oh.", 0.0, 0.10, seg=0)]
    segs = [{"start": 0.0, "end": 5.0, "no_speech_prob": 0.1}]
    (card,) = reflow.reflow(words, segs)
    assert card["end"] - card["start"] >= reflow.MIN_DUR - reflow.EPS
    assert card["source_end"] == 0.10


def test_merged_card_source_window_is_the_union():
    """merge_runts() concatenates word lists, so the merged card's span runs from the
    FIRST group's onset to the LAST group's final word end."""
    words = sentence(["Fine."], t0=0.0, dur=1.0, gap=0.08, seg=0) + sentence(["Monster."], t0=1.08, dur=0.30, seg=0)
    segs = [{"no_speech_prob": 0.1}]
    log = []
    (card,) = reflow.reflow(words, segs, merge_log=log)
    assert log and log[0]["reason"] == "runt_backward_merge"
    assert card["source_start"] == 0.0
    assert card["source_end"] == pytest.approx(1.38, abs=reflow.EPS)


def test_reflow_threads_audio_duration_into_the_cascade():
    """The runt's forward steal puts its successor's start at 0.913s; declare the audio
    0.9s long and the shift no longer fits, which only time_cards() can know."""
    words = _runt_then_surplus_words()
    segs = [{"start": 0.0, "end": 3.0, "no_speech_prob": 0.1}]
    with pytest.raises(reflow.CascadeInfeasible):
        reflow.reflow(words, segs, audio_duration=0.9)


def test_reflow_without_an_audio_duration_stays_unbounded():
    words = _runt_then_surplus_words()
    segs = [{"start": 0.0, "end": 3.0, "no_speech_prob": 0.1}]
    cards = reflow.reflow(words, segs)  # audio_duration defaults to None
    assert [c["start"] for c in cards] == [0.0, pytest.approx(0.913, abs=reflow.EPS)]


def test_cascade_log_collects_cascade_records_from_reflow():
    """generate.py needs time_cards()'s per-cascade records for the QC sidecar
    (stolen / displaced / cascade_depth). Like merge_log, cascade_log is an optional
    out-param, so the public return type stays a plain list of cards."""
    words = sentence(["Oh."], t0=0.0, dur=0.10, seg=0) + sentence(["A much longer line here."], t0=0.15, dur=2.85, seg=0)
    segs = [{"no_speech_prob": 0.1}]
    log: list[dict] = []
    cards = reflow.reflow(words, segs, cascade_log=log)
    assert len(cards) == 2
    assert len(log) == 1
    assert log[0]["reason"] == "forward_steal"
    assert log[0]["hops"] == 1
    assert log[0]["displaced"] == [1]  # the successor's start moved
    assert log[0]["shortened"] == [1]  # ...while its end did not


def test_cascade_record_separates_a_displaced_card_from_a_shortened_one():
    """A zero-surplus chain displaces every hop, but a card whose end has to move with
    its start is not "shortened by a neighbour" -- the two counters must not conflate."""
    _times, records = reflow.time_cards(_runt_then_tight_chain(3))
    r = records[0]
    assert r["hops"] > 1
    assert r["displaced"] == list(range(1, 1 + r["hops"]))
    assert set(r["shortened"]) <= set(r["displaced"])


def test_merge_census_counts_a_short_target_too():
    """The absorbed group is short by definition; the TARGET may be too. Once merged its
    span covers both, so the fact is unrecoverable downstream -- a baseline that omits it
    undercounts, and always downward, flattering the before/after comparison."""
    groups = _two_shorts(0.40, 0.40, gap=0.05)
    out, merges = reflow.merge_runts(groups)
    assert len(merges) == 1
    assert merges[0]["short_groups_before"] == 2  # BOTH groups were short


def test_merge_census_excludes_a_long_target():
    groups = _two_groups(0.08, "It's a", "monster.", 2.0, 0.30)
    _out, merges = reflow.merge_runts(groups)
    assert merges and merges[0]["short_groups_before"] == 1  # only the runt
