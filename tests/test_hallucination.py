"""Unit tests for hallucination.py (B1). Pure functions; plain card dicts."""
import hallucination as h


def card(text, lp=-0.2, nsp=0.1, start=0.0, end=2.0):
    return {"start": start, "end": end, "text": text, "avg_logprob": lp, "no_speech_prob": nsp}


# --- T1: scaffold / constants ------------------------------------------------

def test_constants_and_blocklist():
    assert h.NSP_DROP == 0.8 and h.LP_DROP == -1.0 and h.RUN_COLLAPSE == 4
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
    assert h.drop_reason(card("mmm", lp=-1.5, nsp=0.9)) == "music"
    assert h.drop_reason(card("a real quiet line", lp=-1.5, nsp=0.5)) is None   # nsp not high
    assert h.drop_reason(card("a real quiet line", lp=-0.5, nsp=0.9)) is None   # lp not low


def test_drop_reason_keeps_normal_line():
    assert h.drop_reason(card("Don't let your guard down")) is None
