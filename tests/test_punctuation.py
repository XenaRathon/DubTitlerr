"""Punctuation restoration (R1-R7 of
docs/superpowers/specs/2026-08-20-punctuation-restoration-design.md).

No test here may reach a model: every one either exercises a pure function or stubs
``punctuation.llm_chat``. The end-to-end case runs the restored words through the real
``reflow()`` -- that is the whole point of restoring BEFORE the split rather than in
repair.py afterwards.
"""

import punctuation
import qc
import reflow

APOS = chr(0x2019)  # constructed, never typed: an editor that normalises a
# literal curly apostrophe would silently disable the guard
# this file exists to pin (and the test would still pass).


def _words(seg_texts, dt=0.3, t0=1.0):
    """Whisper-shaped word dicts + their segment records, contiguous in time."""
    words, segments, t = [], [], t0
    for si, txt in enumerate(seg_texts):
        s = t
        for tok in txt.split():
            words.append({"text": tok, "start": round(t, 3), "end": round(t + dt, 3), "prob": 0.9, "seg": si})
            t = round(t + dt, 3)
        segments.append({"start": s, "end": t, "no_speech_prob": 0.01})
    return words, segments


def _stub(monkeypatch, answers):
    """Replace the transport. ``answers`` is a str, a list (one per call) or a callable."""
    calls = []

    def fake(prompt, **kw):
        calls.append({"prompt": prompt, **kw})
        if callable(answers):
            return answers(prompt)
        if isinstance(answers, list):
            return answers[len(calls) - 1]
        return answers

    monkeypatch.setattr(punctuation, "llm_chat", fake)
    return calls


# --- R4: the mechanical guard ----------------------------------------------------


def test_accept_punctuation_and_casing_only():
    assert punctuation.accept_restoration("we have to go it is way too dangerous", "We have to go. It is way too dangerous!")


def test_reject_added_word():
    assert not punctuation.accept_restoration("we have to go", "We have to go now.")


def test_reject_dropped_word():
    assert not punctuation.accept_restoration("we have to go now", "We have to go.")


def test_reject_substituted_word():
    assert not punctuation.accept_restoration("we have to go", "We have to leave.")


def test_reject_reordering():
    assert not punctuation.accept_restoration("we have to go", "To go we have.")


def test_curly_and_straight_apostrophes_normalise_equal():
    """A model that tidies quote style must not be rejected for it -- inside a word
    (``don't``) as well as at its edges."""
    assert punctuation.accept_restoration("we can" + APOS + "t stay", "We can't stay.")
    assert punctuation.accept_restoration("we can't stay", "We can" + APOS + "t stay.")
    assert punctuation.normalise("can" + APOS + "t") == punctuation.normalise("can't")


def test_standalone_punctuation_tokens_are_not_words():
    """An em dash the model inserts between words adds no token to compare."""
    assert punctuation.accept_restoration("wait for me", "Wait " + chr(0x2014) + " wait for me!") is False
    assert punctuation.accept_restoration("wait for me", "Wait " + chr(0x2014) + " for me!")


# --- R1: run detection ------------------------------------------------------------


def test_a_lone_unpunctuated_segment_is_not_a_run():
    texts = ["He went home.", "and then it stopped", "That was it."]
    assert punctuation.find_runs(texts, 2) == []


def test_consecutive_unpunctuated_segments_are_a_run():
    texts = ["He went home.", "and then it stopped", "so we ran", "That was it."]
    assert punctuation.find_runs(texts, 2) == [(1, 3)]


def test_min_run_filters_shorter_runs():
    texts = ["A.", "one two", "three four", "B.", "five", "six", "seven", "C."]
    assert punctuation.find_runs(texts, 3) == [(4, 7)]


def test_min_run_below_two_still_never_sends_a_lone_segment():
    """R1 is structural, not a tunable: a lone fragment between two punctuated
    segments is never sent however low RESTORE_MIN_RUN is set."""
    texts = ["A.", "alone here", "B."]
    assert punctuation.find_runs(texts, 1) == []
    assert punctuation.find_runs(texts, 0) == []


def test_a_segment_with_internal_sentence_punctuation_is_not_a_candidate():
    texts = ["one two", "he left. so did she", "three four"]
    assert punctuation.find_runs(texts, 2) == []


def test_ellipsis_counts_as_sentence_terminal():
    texts = ["well" + chr(0x2026), "no idea", "not sure"]
    assert punctuation.find_runs(texts, 2) == [(1, 3)]


def test_segment_texts_are_rebuilt_from_the_words():
    words, segments = _words(["one two", "three"])
    assert punctuation.segment_texts(words, len(segments)) == ["one two", "three"]


# --- R5: mapping back onto the timestamped words ----------------------------------


def test_restored_tokens_land_on_the_right_words_and_timestamps_never_move(monkeypatch):
    words, segments = _words(["we have to go", "it is way too dangerous"])
    before = [(w["start"], w["end"], w["prob"], w["seg"]) for w in words]
    _stub(monkeypatch, "We have to go. It is way too dangerous!")
    punctuation.restore(words, segments)
    assert [w["text"] for w in words] == ["We", "have", "to", "go.", "It", "is", "way", "too", "dangerous!"]
    assert [(w["start"], w["end"], w["prob"], w["seg"]) for w in words] == before


def test_a_word_dict_holding_a_whole_segment_takes_all_its_tokens(monkeypatch):
    """generate.py's no-word-timestamps fallback appends the WHOLE segment as one
    'word'. The mapping is per word DICT, not per token, so that case still works."""
    words = [
        {"text": "we have to go", "start": 1.0, "end": 3.0, "prob": 0.9, "seg": 0},
        {"text": "it is dangerous", "start": 3.0, "end": 5.0, "prob": 0.9, "seg": 1},
    ]
    segments = [{"start": 1.0, "end": 3.0, "no_speech_prob": 0.0}, {"start": 3.0, "end": 5.0, "no_speech_prob": 0.0}]
    _stub(monkeypatch, "We have to go. It is dangerous.")
    punctuation.restore(words, segments)
    assert [w["text"] for w in words] == ["We have to go.", "It is dangerous."]
    assert (words[0]["start"], words[1]["end"]) == (1.0, 5.0)


# --- R6: every failure path leaves Whisper's words alone --------------------------


def test_empty_answer_leaves_the_words_untouched(monkeypatch):
    words, segments = _words(["we have to go", "it is dangerous"])
    before = [dict(w) for w in words]
    _stub(monkeypatch, "")
    rec = qc.Recorder()
    punctuation.restore(words, segments, rec)
    assert words == before
    assert rec.counters["restore_empty"] == 1
    assert rec.counters["restore_accepted"] == 0


def test_transport_failure_leaves_the_words_untouched(monkeypatch):
    """llm_chat swallows transport errors and returns ''. If it ever raised, the pass
    still must not cost the episode."""
    words, segments = _words(["we have to go", "it is dangerous"])
    before = [dict(w) for w in words]

    def boom(prompt, **kw):
        raise OSError("connection refused")

    monkeypatch.setattr(punctuation, "llm_chat", boom)
    rec = qc.Recorder()
    punctuation.restore(words, segments, rec)
    assert words == before


def test_guard_rejection_leaves_the_words_untouched_and_is_recorded(monkeypatch):
    words, segments = _words(["we have to go", "it is dangerous"])
    before = [dict(w) for w in words]
    _stub(monkeypatch, "We have to leave now. It is really dangerous.")
    rec = qc.Recorder()
    punctuation.restore(words, segments, rec)
    assert words == before
    assert rec.counters["restore_rejected_guard"] == 1
    assert rec.counters["restore_words_repunctuated"] == 0
    ev = [e for e in rec.build(show="S", episode="E", stem="x")["events"] if e.get("reason") == "restore_rejected"]
    assert len(ev) == 1 and ev[0]["segments"] == [0, 2]


def test_rejected_run_events_are_bounded(monkeypatch):
    words, segments = _words(["a b", "c d", "Ok."] * 60)
    _stub(monkeypatch, "totally different words entirely")
    rec = qc.Recorder()
    punctuation.restore(words, segments, rec)
    ev = [e for e in rec.build(show="S", episode="E", stem="x")["events"] if e.get("reason") == "restore_rejected"]
    assert 0 < len(ev) <= punctuation.MAX_REJECT_EVENTS


def test_disabled_by_env_makes_no_calls(monkeypatch):
    words, segments = _words(["we have to go", "it is dangerous"])
    before = [dict(w) for w in words]
    calls = _stub(monkeypatch, "We have to go. It is dangerous.")
    monkeypatch.setattr(punctuation, "RESTORE_PUNCTUATION", "0")
    rec = qc.Recorder()
    punctuation.restore(words, segments, rec)
    assert calls == [] and words == before
    assert rec.counters["restore_runs_sent"] == 0


def test_no_words_is_a_no_op(monkeypatch):
    calls = _stub(monkeypatch, "anything")
    punctuation.restore([], [], qc.Recorder())
    assert calls == []


# --- R2/R7: one call per run, and the counters ------------------------------------


def test_one_call_per_run_covering_the_whole_stretch(monkeypatch):
    words, segments = _words(["one two", "three four", "Done.", "five six", "seven eight"])
    calls = _stub(monkeypatch, lambda p: "")
    rec = qc.Recorder()
    punctuation.restore(words, segments, rec)
    assert len(calls) == 2
    assert "one two three four" in calls[0]["prompt"] or "one two\nthree four" in calls[0]["prompt"]
    assert "Done." not in calls[0]["prompt"] and "Done." not in calls[1]["prompt"]
    assert rec.counters["restore_runs_seen"] == 2
    assert rec.counters["restore_runs_sent"] == 2


def test_counters_on_the_happy_path(monkeypatch):
    words, segments = _words(["we have to go", "it is dangerous"])
    _stub(monkeypatch, "We have to go. It is dangerous.")
    rec = qc.Recorder()
    punctuation.restore(words, segments, rec)
    c = rec.counters
    assert c["restore_runs_seen"] == 1 and c["restore_runs_sent"] == 1
    assert c["restore_accepted"] == 1 and c["restore_rejected_guard"] == 0
    assert c["restore_empty"] == 0
    assert c["restore_words_repunctuated"] == 4  # We, go., It, dangerous.


def test_qc_declares_every_restore_counter():
    for name in (
        "restore_runs_seen",
        "restore_runs_sent",
        "restore_accepted",
        "restore_rejected_guard",
        "restore_empty",
        "restore_words_repunctuated",
    ):
        assert name in qc.COUNTERS
        assert qc.Recorder().build(show="S", episode="E", stem="x")["counters"][name] == 0


def test_the_run_is_not_truncated_to_one_line(monkeypatch):
    """A run is multi-line: first_line=True would cut the answer to its first sentence
    and the guard would then reject every long run."""
    words, segments = _words(["one two three four five", "six seven eight nine ten"])
    calls = _stub(monkeypatch, "One two three four five. Six seven eight nine ten.")
    punctuation.restore(words, segments)
    assert calls[0]["first_line"] is False
    assert calls[0]["max_tokens"] >= 4 * 10


def test_max_tokens_scales_with_the_run(monkeypatch):
    small, seg_s = _words(["a b", "c d"])
    big, seg_b = _words([" ".join(f"w{i}" for i in range(20))] * 6)
    calls = _stub(monkeypatch, "")
    punctuation.restore(small, seg_s)
    punctuation.restore(big, seg_b)
    assert calls[1]["max_tokens"] > calls[0]["max_tokens"]
    assert calls[1]["max_tokens"] <= punctuation.RESTORE_MAX_TOKENS


# --- end to end: the split moves because the punctuation is there -----------------

UNPUNCTUATED = ["we have to go somewhere else", "they all died out there at sea and nobody ever came back home"]
RESTORED = "We have to go somewhere else. They all died out there at sea and nobody ever came back home."


def test_without_restoration_reflow_splits_on_character_balance():
    words, segments = _words(UNPUNCTUATED)
    cards = reflow.reflow(words, segments)
    assert cards[0]["text"].replace("\n", " ").lower() != "we have to go somewhere else."


def test_with_restoration_reflow_splits_at_the_restored_sentence_boundary(monkeypatch):
    words, segments = _words(UNPUNCTUATED)
    _stub(monkeypatch, RESTORED)
    punctuation.restore(words, segments)
    cards = reflow.reflow(words, segments)
    assert cards[0]["text"].replace("\n", " ") == "We have to go somewhere else."
    assert cards[1]["text"].replace("\n", " ").startswith("They all died")


# --- dash splitting and the contraction whitelist -----------------------------
# Both come from a LIVE run against the real model: 3 of 7 rejections were the model
# writing "tempo<em-dash>you" for "tempo you" -- pure punctuation that normalise() saw
# as one token instead of two.


def test_em_dash_between_words_is_a_separator_not_a_word_change():
    em = chr(0x2014)
    assert punctuation.accept_restoration("the tempo you want", f"The tempo{em}you want.")


def test_en_dash_too():
    en = chr(0x2013)
    assert punctuation.accept_restoration("sunny there is something", f"Sunny{en}there is something.")


def test_hyphen_is_not_split_because_it_is_word_internal():
    """Splitting hyphens would break real words, so a hyphen inserted BETWEEN two words
    is still a rejection -- the conservative side of an ambiguous mark."""
    assert not punctuation.accept_restoration("district f 16", "District f-16.")


def test_contraction_allowed_when_the_bare_form_is_not_a_word(monkeypatch):
    monkeypatch.setattr(punctuation, "WORDS", frozenset({"we", "go", "well", "its"}))
    assert punctuation.accept_restoration("dont go", "Don't go.")
    assert punctuation.accept_restoration("theres smoke", "There's smoke.")


def test_contraction_BLOCKED_when_the_bare_form_is_a_real_word(monkeypatch):
    """well/we'll and its/it's are different sentences. The guard must not let the model
    choose between them."""
    monkeypatch.setattr(punctuation, "WORDS", frozenset({"well", "its", "go"}))
    assert not punctuation.accept_restoration("well go", "We'll go.")
    assert not punctuation.accept_restoration("its go", "It's go.")


def test_removing_an_apostrophe_is_still_a_rejection(monkeypatch):
    monkeypatch.setattr(punctuation, "WORDS", frozenset())
    assert not punctuation.accept_restoration("don't go", "Dont go.")


def test_missing_wordlist_means_no_contraction_allowance(monkeypatch):
    """A dev box without wamerican must be STRICTER, never looser."""
    monkeypatch.setattr(punctuation, "WORDS", frozenset())
    assert not punctuation.accept_restoration("dont go", "Don't go.")
