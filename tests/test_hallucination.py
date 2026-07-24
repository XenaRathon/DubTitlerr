"""Unit tests for hallucination.py (B1). Pure functions; plain card dicts."""
import hallucination as h


def card(text, lp=-0.2, nsp=0.1, start=0.0, end=2.0):
    return {"start": start, "end": end, "text": text, "avg_logprob": lp, "no_speech_prob": nsp}


# --- T1: scaffold / constants ------------------------------------------------

def test_constants_and_blocklist():
    assert h.NSP_DROP == 0.95 and h.LP_DROP == -2.0 and h.RUN_COLLAPSE == 4
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
    assert not h.is_repetition("No no no no")          # < 6 tokens, real emphasis
    assert not h.is_repetition("Don't let your guard down")
    assert not h.is_repetition("the cat sat on the mat today")


def test_drop_reason_blocklist():
    assert h.drop_reason(card("Thanks for watching, see you next time")) == "blocklist"


def test_drop_reason_repetition():
    assert h.drop_reason(card("la la la la la la")) == "repetition"


def test_drop_reason_music_requires_both_signals():
    assert h.drop_reason(card("mmm", lp=-2.5, nsp=0.97)) == "music"
    assert h.drop_reason(card("a real quiet line", lp=-1.5, nsp=0.5)) is None   # nsp not high
    assert h.drop_reason(card("a real quiet line", lp=-0.5, nsp=0.9)) is None   # lp not low


def test_drop_reason_keeps_normal_line():
    assert h.drop_reason(card("Don't let your guard down")) is None


# --- T3: flag_reason ---------------------------------------------------------

def test_flag_reason_low_confidence():
    assert h.flag_reason(card("mumbled bit", lp=-0.8, nsp=0.2)) == "low_conf"


def test_flag_reason_maybe_silence():
    assert h.flag_reason(card("faint line", lp=-0.3, nsp=0.6)) == "maybe_silence"


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
    assert len(h.collapse_runs(cards)) == 3       # duplicates not consecutive


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
