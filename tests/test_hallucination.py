"""Unit tests for hallucination.py (B1). Pure functions; plain card dicts."""

import hallucination as h


def card(text, lp=-0.2, nsp=0.1, start=0.0, end=2.0):
    return {"start": start, "end": end, "text": text, "avg_logprob": lp, "no_speech_prob": nsp}


# --- T1: scaffold / constants ------------------------------------------------


def test_constants_and_blocklist():
    assert h.LP_FLAG == -0.6 and h.RUN_COLLAPSE == 4
    assert h.BLOCKLIST.search("Subtitles by the community")
    assert h.BLOCKLIST.search("please subscribe to our channel")
    assert not h.BLOCKLIST.search("I subscribe to that philosophy of life")


# --- T2: is_repetition + drop_reason -----------------------------------------


def test_is_repetition_single_word_loop():
    assert h.is_repetition("go go go go go go")
    assert h.is_repetition("die die die die die die die")


def test_is_repetition_ngram_loop():
    assert h.is_repetition("I'm fine I'm fine I'm fine I'm fine")


def test_is_repetition_ignores_short_emphatic_and_normal_lines():
    assert not h.is_repetition("No no no no")  # < 6 tokens, real emphasis
    assert not h.is_repetition("Don't let your guard down")
    assert not h.is_repetition("the cat sat on the mat today")


def test_drop_reason_blocklist():
    assert h.drop_reason(card("Thanks for watching, see you next time")) == "blocklist"


def test_drop_reason_repetition():
    assert h.drop_reason(card("la la la la la la")) == "repetition"


def test_drop_reason_keeps_normal_line():
    assert h.drop_reason(card("Don't let your guard down")) is None


# --- T3: flag_reason ---------------------------------------------------------


def test_flag_reason_low_confidence():
    assert h.flag_reason(card("mumbled bit", lp=-0.8, nsp=0.2)) == "low_conf"


def test_flag_reason_none_for_clean_line():
    assert h.flag_reason(card("Don't let your guard down")) is None


# --- T4: collapse_runs -------------------------------------------------------


def run(text, n, t0=0.0, step=2.0):
    return [card(text, start=t0 + i * step, end=t0 + i * step + 1.5) for i in range(n)]


def test_collapse_runs_merges_four_plus_identical():
    cards = run("Help me!", 5)
    out = h.collapse_runs(cards)
    assert len(out) == 1
    assert out[0]["start"] == cards[0]["start"]
    assert out[0]["end"] == cards[-1]["end"]


def test_collapse_runs_leaves_three_or_fewer():
    cards = run("Run!", 3)
    assert len(h.collapse_runs(cards)) == 3


def test_collapse_runs_treats_case_punct_as_near_identical():
    cards = [card("Run!"), card("run"), card("RUN."), card("Run")]
    assert len(h.collapse_runs(cards)) == 1


def test_collapse_runs_only_consecutive():
    cards = [card("A line here"), card("B line there"), card("A line here")]
    assert len(h.collapse_runs(cards)) == 3  # duplicates not consecutive


def test_collapse_runs_mixed_sequence():
    cards = run("loop", 4) + [card("a distinct ending line")]
    out = h.collapse_runs(cards)
    assert len(out) == 2 and out[1]["text"] == "a distinct ending line"


# --- V2 C8: BLOCKLIST loaded from data/hallucination_blocklist.txt, inline fallback ----


def test_blocklist_loads_from_data_file():
    """The real data/hallucination_blocklist.txt (repo-relative, present in this checkout)
    reproduces the exact same compiled pattern as the inline fallback."""
    loaded = h._load_blocklist("data/hallucination_blocklist.txt")
    fallback = h._load_blocklist("data/does_not_exist.txt")
    assert loaded.pattern == fallback.pattern == h._BLOCKLIST_PATTERN_FALLBACK


def test_blocklist_falls_back_when_data_file_missing():
    """Missing/unreadable data file -> falls back to the pre-C8 inline pattern, not an
    empty (always-matching-nothing) regex."""
    bl = h._load_blocklist("data/nope_this_file_does_not_exist.txt")
    assert bl.search("please subscribe to our channel")
    assert not bl.search("I subscribe to that philosophy of life")


def test_blocklist_data_file_comments_and_blanks_are_skipped(tmp_path):
    f = tmp_path / "blocklist.txt"
    f.write_text("# a comment\n\nfoo-pattern\n  \nbar-pattern\n")
    bl = h._load_blocklist(str(f))
    assert bl.search("has a foo-pattern in it")
    assert bl.search("has a bar-pattern in it")
    assert not bl.search("neither pattern here")


# --- liveness counters (2026-08-22) -------------------------------------------------


def test_drop_reason_records_evaluated_and_activated():
    """A rule that never fires must be distinguishable from a rule never reached: a
    successful episode with zero drops looks identical to one where the rule is dead.
    This instrument is what proved `music` could never fire, which is why ADR 0002 deleted
    it rather than tuning it -- so the counters must keep working for what remains."""
    import qc

    rec = qc.Recorder()
    speech = {"text": "Hello there.", "no_speech_prob": 0.1, "avg_logprob": -0.2}
    assert h.drop_reason(speech, rec=rec) is None
    assert rec.counters["rule_blocklist_evaluated"] == 1
    assert rec.counters["rule_blocklist_activated"] == 0
    assert rec.counters["rule_repetition_evaluated"] == 1
    assert rec.counters["rule_repetition_activated"] == 0

    assert h.drop_reason({"text": "To be continued...", "no_speech_prob": 0.1, "avg_logprob": -0.2}, rec=rec) == "blocklist"
    assert rec.counters["rule_blocklist_activated"] == 1
    # short-circuit: later rules are NOT evaluated once one fires
    assert rec.counters["rule_repetition_evaluated"] == 1


def test_flag_reason_records_liveness():
    import qc

    rec = qc.Recorder()
    h.flag_reason({"avg_logprob": -0.2, "no_speech_prob": 0.1}, rec=rec)
    assert rec.counters["rule_low_conf_evaluated"] == 1
    assert rec.counters["rule_low_conf_activated"] == 0
    h.flag_reason({"avg_logprob": -9.0, "no_speech_prob": 0.1}, rec=rec)
    assert rec.counters["rule_low_conf_activated"] == 1


def test_rec_is_optional_and_behaviour_is_unchanged():
    """tools/ and existing callers invoke these bare; the signature must stay compatible."""
    assert h.drop_reason({"text": "To be continued...", "no_speech_prob": 0.1, "avg_logprob": -0.2}) == "blocklist"
    assert h.flag_reason({"avg_logprob": -9.0, "no_speech_prob": 0.1}) == "low_conf"


# --- implausible source window (VAD design S6; spec v5, S-6) -------------------


def _card(text, ss=None, se=None, start=0.0, end=1.0):
    c = {"text": text, "start": start, "end": end}
    if ss is not None:
        c["source_start"] = ss
    if se is not None:
        c["source_end"] = se
    return c


def test_a_two_word_card_spanning_more_than_max_dur_is_a_bad_window():
    """VAD design S6: whisper emits an implausible word timestamp on music-masked audio.
    'disobeys' and 'it' each came back with a 7.0s span for ONE word."""
    import hallucination as h
    import reflow

    assert h.bad_source_window(_card("it", ss=0.0, se=reflow.MAX_DUR + 0.5))


def test_a_card_with_three_words_is_left_alone():
    """The guard is scoped to 1-2 word cards on purpose: a long span across several words
    is ordinary dialogue, and widening this silently would start discarding real evidence."""
    import hallucination as h
    import reflow

    assert not h.bad_source_window(_card("it was him", ss=0.0, se=reflow.MAX_DUR + 0.5))


def test_a_short_span_is_not_a_bad_window():
    import hallucination as h

    assert not h.bad_source_window(_card("it", ss=1.0, se=2.0))


def test_a_card_with_no_source_fields_is_never_a_bad_window():
    """The VAD design records TWO of its own measurements invalidated by a .get() default
    silently answering the question asked. The guard must not fabricate a window."""
    import hallucination as h

    assert not h.bad_source_window(_card("it"))
    assert not h.bad_source_window(_card("it", ss=0.0))
    assert not h.bad_source_window(_card("it", se=9.0))


def test_the_guard_records_liveness_like_every_other_rule():
    """evaluated>0 with activated==0 is the dead-rule signal; the counters ARE the value
    of this guard -- it is observability, not recovery."""
    import hallucination as h
    import qc
    import reflow

    rec = qc.Recorder()
    h.bad_source_window(_card("it", ss=1.0, se=2.0), rec=rec)
    assert rec.counters["rule_source_window_evaluated"] == 1
    assert rec.counters["rule_source_window_activated"] == 0

    h.bad_source_window(_card("it", ss=0.0, se=reflow.MAX_DUR + 0.5), rec=rec)
    assert rec.counters["rule_source_window_evaluated"] == 2
    assert rec.counters["rule_source_window_activated"] == 1


def test_a_card_with_no_source_fields_records_no_activation():
    import hallucination as h
    import qc

    rec = qc.Recorder()
    h.bad_source_window(_card("it"), rec=rec)
    assert rec.counters["rule_source_window_activated"] == 0


# --- the nsp-gated rules are gone (ADR 0002) ----------------------------------


def test_the_nsp_gated_rules_are_not_reintroduced():
    """`music` and `maybe_silence` were deleted 2026-08-24, not tuned. Measured: `music`
    caught 0 of 353,879 cards, and it stays at 0 even on large-v3, whose nsp IS live --
    none of its 6 segments over nsp 0.95 also has avg_logprob < -2.0. The conjunction does
    not occur in this material, so no model change revives it, and every reachable
    relaxation destroys more real dialogue than it saves (precision peaks near 20%).

    If this test fails, someone re-added a rule on the intuition that an unreachable
    threshold is a bug. Read .procoder/adr/0002 before changing it: the precision ceiling
    is the thing to beat, not the threshold."""
    import hallucination as h

    assert not hasattr(h, "NSP_DROP"), "the music rule was re-added; see ADR 0002"
    assert not hasattr(h, "LP_DROP"), "the music rule was re-added; see ADR 0002"
    assert not hasattr(h, "NSP_FLAG"), "maybe_silence was re-added; see ADR 0002"


def test_drop_reason_no_longer_reads_no_speech_prob():
    """The production decoder returns nsp of exactly 0.0, so a gate that consults it is
    deciding on a field nothing populates."""
    import hallucination as h

    assert h.drop_reason({"text": "a real line", "no_speech_prob": 0.99, "avg_logprob": -9.0}) is None


def test_the_surviving_rules_still_fire():
    """Deleting the dead ones must not disturb the live ones."""
    import hallucination as h

    assert h.drop_reason({"text": "To be continued...", "avg_logprob": -0.2}) == "blocklist"
    assert h.flag_reason({"avg_logprob": -0.9}) == "low_conf"
    assert h.flag_reason({"avg_logprob": -0.1}) is None


def test_a_high_nsp_card_is_no_longer_flagged():
    import hallucination as h

    assert h.flag_reason({"avg_logprob": -0.1, "no_speech_prob": 0.99}) is None


# --- CJK in an English dub -------------------------------------------------------------


def test_japanese_script_in_an_english_dub_is_dropped():
    """R-song-drop. The dub track is English BY CONSTRUCTION, so a card carrying Japanese
    script is not a low-confidence English line -- it is whisper falling back to the
    Japanese it heard under a song it could not transcribe. Measured on MARRIAGETOXIN
    S01E02, whose release captions no song lyrics at all and therefore cannot be helped by
    the signs-track song-span drop."""
    for text in (
        "Run, run, run, 背中合わせ, run!",
        "欲しいの Toxic ずっとここにいるよ不思議なほど",
        "Tock of, 抱えたままで.",
        "そこにいるよ君はどうする?",
        "Stemina, 僕らを振れ!",
    ):
        assert h.drop_reason({"text": text}) == "cjk_in_english_dub", text


def test_ordinary_english_dialogue_is_untouched_by_the_cjk_rule():
    """The whole risk of this rule is deleting real dialogue. It has no threshold, so the
    only way it can misfire is on a genuinely English line -- including one naming Japanese
    people and places, which a dub says in romaji, never in kana."""
    for text in (
        "I saw Spandam at the gate.",
        "Hikaru Gero. Here comes the real treat.",
        "We're heading to Osaka, then Kyoto.",
        "Let's get one thing straight: you and I are not friends.",
        "No mama, lots of time.",
    ):
        assert h.drop_reason({"text": text}) != "cjk_in_english_dub", text


def test_the_cjk_rule_is_counted_like_every_other_gate():
    """It has to show up in the run's counters, or a rule that starts deleting the wrong
    thing does it invisibly."""

    class Rec:
        def __init__(self):
            self.n = {}

        def count(self, k, v=1):
            self.n[k] = self.n.get(k, 0) + v

    rec = Rec()
    h.drop_reason({"text": "君はどうする?"}, rec=rec)
    assert any("cjk" in k for k in rec.n), rec.n
