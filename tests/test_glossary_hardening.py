"""Hardening: malformed adjudications, punctuation around a term, the two-letter minimum's documented behaviour."""

import json

import pytest

import glossary
import glossary_verify as gv


def base(**extra):
    return {"show": "S", "names": ["Zoro", "Nami"], "phrases": [], "hard_fixes": {}, **extra}


# ---- C: apply_results trusts nothing about an adjudication -------------- ---


@pytest.mark.parametrize(
    "adj",
    [
        ["Roronoa Zoro", "high"],
        "Roronoa Zoro",
        None,
        7,
        {"canonical": ["Roronoa Zoro"], "confidence": "high"},
        {"canonical": {"x": 1}, "confidence": "high"},
        {"canonical": 5, "confidence": "high"},
        {"canonical": "Roronoa Zoro", "confidence": ["high"]},
        {"canonical": "Roronoa Zoro", "confidence": {"x": 1}},
        {},
    ],
)
def test_a_malformed_adjudication_is_a_no_match_and_never_a_write_or_a_crash(monkeypatch, adj):
    monkeypatch.setenv("VERIFY_QUEUE_NO_MATCH", "1")  # the queue is off by default since phase 27
    out = gv.apply_results(base(), {"Zoro": adj})
    assert "Roronoa Zoro" not in out["names"] + out["phrases"]
    assert out["flagged"]["Zoro"] == "no-match" and "Zoro" in out["verified"]


def test_a_well_formed_adjudication_is_untouched():
    out = gv.apply_results(base(), {"Zoro": {"canonical": "Roronoa Zoro", "confidence": "high", "dub_note": ""}})
    assert "Roronoa Zoro" in out["phrases"] and "flagged" not in out


def test_clean_adjudication_reports_what_it_repaired():
    assert gv.clean_adjudication({"canonical": "A B", "confidence": "high"}) == (
        {"canonical": "A B", "confidence": "high"},
        False,
    )
    assert gv.clean_adjudication({"canonical": "A B", "confidence": "HIGH"})[0]["confidence"] == "high"
    assert gv.clean_adjudication(["x"]) == ({"canonical": "", "confidence": "none"}, True)
    assert gv.clean_adjudication({"canonical": ["x"], "confidence": "high"})[1] is True
    assert gv.clean_adjudication({"canonical": "A", "confidence": "certain"}) == ({"canonical": "A", "confidence": "low"}, True)


def test_is_no_match_survives_a_malformed_adjudication():
    assert gv.is_no_match(["x"]) is True and gv.is_no_match({"canonical": ["x"], "confidence": "high"}) is True


def test_verify_counts_malformed_adjudications_in_the_report(tmp_path, monkeypatch):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(base(wiki="https://x.fandom.com/api.php")))
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: ["Roronoa Zoro"])
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    answers = {"Zoro": ["bad"], "Nami": {"canonical": "Nami", "confidence": "high"}}
    monkeypatch.setattr(gv, "adjudicate", lambda term, cands, show: answers[term])
    rep = gv.verify(str(path))
    assert rep["malformed"] == 1 and rep["checked"] == 2


def test_a_well_formed_run_has_no_malformed_key(tmp_path, monkeypatch):
    """GUARD (passes on the old code): the default report shape."""
    path = tmp_path / "g.json"
    path.write_text(json.dumps(base(wiki="https://x.fandom.com/api.php")))
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: ["Roronoa Zoro"])
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    monkeypatch.setattr(gv, "adjudicate", lambda term, cands, show: {"canonical": term, "confidence": "high", "dub_note": ""})
    assert "malformed" not in gv.verify(str(path))


# ---- D: a term with punctuation around it ------------------------------- ---


@pytest.fixture
def words(monkeypatch):
    monkeypatch.setattr(glossary, "_ORDINARY", {"castle", "government"})


@pytest.mark.parametrize(
    "term", ["castle", "Castle", "castle!", "castle.", "(castle)", "'castle'", "“castle”", "castle,", "-castle-", "castle2"]
)
def test_surrounding_non_letters_do_not_hide_an_ordinary_word(words, term):
    assert glossary.is_ordinary_word(term)


@pytest.mark.parametrize("term", ["Hancock!", "hancock", "", "!!!", "3", "---", "o'clock", "cast le"])
def test_names_and_non_words_are_not_ordinary(words, term):
    assert not glossary.is_ordinary_word(term)


def test_the_guard_flags_a_punctuated_common_word(words, monkeypatch):
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    out = gv.apply_results(base(names=["castle!"]), {"castle!": {"canonical": "Drum Castle", "confidence": "high"}})
    assert out["flagged"]["castle!"]["reason"] in ("common-word", "respelling-needs-review")


def test_is_english_the_fuzzy_path_is_untouched(monkeypatch):
    monkeypatch.setattr(glossary, "_WORDS", {"castle"})
    assert glossary.is_english("castle") and not glossary.is_english("castle!")


# ---- the two-letter minimum is documented and flags rather than loses --- ---


def test_a_term_under_the_two_letter_minimum_is_flagged_for_review_not_lost(monkeypatch):
    monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "1")
    out = gv.apply_results(base(names=["G-5"]), {"G-5": {"canonical": "Marine Base G-5", "confidence": "high"}})
    assert out["flagged"]["G-5"] == {"reason": "respelling-needs-review", "canonical": "Marine Base G-5"}
    assert "G-5" in out["names"] + out["phrases"] or "G-5" in out["names"]  # the term itself is still there


def test_dr_k_has_three_letters_and_is_not_held_back_by_the_minimum(monkeypatch):
    monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "1")
    assert gv._whole_word("Dr. K", "The Dr. K Clinic")


def test_the_docstring_says_the_minimum_flags_for_review():
    assert "flagged for review" in gv.auto_writes.__doc__ and "G-5" in gv.auto_writes.__doc__
