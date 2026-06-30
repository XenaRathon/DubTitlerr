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
