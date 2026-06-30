"""Unit tests for glossary_verify.py pure core (wiki HTTP + LLM are integration)."""
import glossary_verify as gv


def test_constants_present():
    assert gv.TOPK >= 3
    assert 0 < gv.CAND_CUTOFF < 1
    assert gv.VERIFY_MODEL
