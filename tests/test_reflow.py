"""Unit tests for reflow.py (A1). Pure functions, no whisper/CUDA needed."""
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
