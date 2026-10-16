"""VERIFY_QUEUE_BLOCKED_EXPANSIONS=0: an expansion that a write guard blocked is verified and counted, not queued. A real
respelling is always queued. Synthetic data only."""

import json

import pytest

import glossary
import glossary_acquire as ga
import glossary_verify as gv


def high(canon):
    return {"canonical": canon, "confidence": "high", "dub_note": ""}


def base(**extra):
    return {"show": "S", "names": [], "phrases": [], "hard_fixes": {}, **extra}


@pytest.fixture
def guards(monkeypatch):
    """Both write guards on, a tiny word list that knows 'government' as a word, an arc universe that lacks 'Zou Island'."""
    monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "1")
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    monkeypatch.setattr(glossary, "_ORDINARY", {"government", "castle"})


# term -> (canonical, what the flag-0 run does with it)
CASES = {
    "D": ("Monkey D. Luffy", "expansion-guarded"),  # more tokens: a real expansion the whole-word guard refused
    "Castle": ("Hancock Castle", "common-word"),
    "Government": ("World Government", "common-word"),
}
# One-token spelling fixes: never droppable, whatever is_expansion says.
RESPELLINGS = {"Usop": "Usopp", "Burn": "Coburn", "Raftel": "Ratel", "Jabra": "Jabari", "Kaidou": "Kaido", "Lufy": "Luffy"}


def apply(terms_to_canon, **extra):
    g = base(names=list(terms_to_canon), **extra)
    return gv.apply_results(g, {t: high(c) for t, c in terms_to_canon.items()})


# ---- default: byte-identical, queued under the legacy reasons ------ ----


def test_by_default_blocked_expansions_are_queued_under_the_legacy_reason_strings(guards, monkeypatch):
    """GUARD (passes on the old code)."""
    monkeypatch.delenv("VERIFY_QUEUE_BLOCKED_EXPANSIONS", raising=False)
    terms = {**{t: c for t, (c, _r) in CASES.items()}, **RESPELLINGS}
    out = apply(terms)
    assert out["flagged"]["Usop"] == {"reason": "respelling-needs-review", "canonical": "Usopp"}
    assert out["flagged"]["D"] == {"reason": "respelling-needs-review", "canonical": "Monkey D. Luffy"}
    assert out["flagged"]["Government"] == {"reason": "common-word", "canonical": "World Government"}
    monkeypatch.setenv("VERIFY_QUEUE_BLOCKED_EXPANSIONS", "1")
    assert apply(terms) == out


# ---- off: verified, not queued ------------------------------------- ----


def test_with_the_queue_off_blocked_expansions_are_verified_but_not_flagged(guards, monkeypatch):
    monkeypatch.setenv("VERIFY_QUEUE_BLOCKED_EXPANSIONS", "0")
    out = apply({t: c for t, (c, _r) in CASES.items()})
    assert "flagged" not in out
    assert sorted(out["verified"]) == ["Castle", "D", "Government"]
    assert out["phrases"] == [] and sorted(out["names"]) == ["Castle", "D", "Government"]  # nothing was written either


@pytest.mark.parametrize("term,canon", sorted(RESPELLINGS.items()))
def test_a_one_token_spelling_fix_is_always_queued_even_if_is_expansion_says_expansion(guards, monkeypatch, term, canon):
    """Usop -> Usopp and Burn -> Coburn are expansions to is_expansion but spelling fixes to a reader; the correct spelling would
    never be offered again if they were dropped."""
    monkeypatch.setenv("VERIFY_QUEUE_BLOCKED_EXPANSIONS", "0")
    out = apply({term: canon})
    assert out["flagged"][term] == {"reason": "respelling-needs-review", "canonical": canon}


def test_a_same_token_common_word_block_is_queued_too(monkeypatch):
    """Without the whole-word guard a common word can be 'expanded' into one token (Castle -> Castles): not droppable."""
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "0")
    monkeypatch.setattr(glossary, "_ORDINARY", {"castle"})
    monkeypatch.setenv("VERIFY_QUEUE_BLOCKED_EXPANSIONS", "0")
    out = apply({"Castle": "Castles", "Castle Rock": "Hancock Castle Rock"})
    assert out["flagged"]["Castle"] == {"reason": "common-word", "canonical": "Castles"}


def test_a_real_respelling_is_always_queued(guards, monkeypatch):
    monkeypatch.setenv("VERIFY_QUEUE_BLOCKED_EXPANSIONS", "0")
    out = apply({"Raftel": "Ratel"})
    assert out["flagged"]["Raftel"] == {"reason": "respelling-needs-review", "canonical": "Ratel"}


def test_the_arc_gate_block_is_not_queued_when_off(monkeypatch):
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    monkeypatch.setenv("VERIFY_QUEUE_BLOCKED_EXPANSIONS", "0")
    arcs = {"arc_titles": {"Wano": ["Kaido"]}, "arc_coverage": {"Wano": {"titles": 1, "redirects": True}}}
    monkeypatch.setenv("ARC_MIN_TITLES", "1")
    out = apply({"Zou": "Zou Island"}, **arcs)
    assert "flagged" not in out
    monkeypatch.delenv("VERIFY_QUEUE_BLOCKED_EXPANSIONS")
    assert apply({"Zou": "Zou Island"}, **arcs)["flagged"]["Zou"]["reason"] == "not-in-arc-pages"


def test_a_written_expansion_is_unaffected(guards, monkeypatch):
    monkeypatch.setenv("VERIFY_QUEUE_BLOCKED_EXPANSIONS", "0")
    out = apply({"Zoro": "Roronoa Zoro"})
    assert "Roronoa Zoro" in out["phrases"] and "flagged" not in out


def test_low_confidence_and_no_match_are_not_this_flags_business(guards, monkeypatch):
    monkeypatch.setenv("VERIFY_QUEUE_BLOCKED_EXPANSIONS", "0")
    out = gv.apply_results(base(names=["A"]), {"A": {"canonical": "Alpha", "confidence": "low"}})
    assert out["flagged"]["A"]["reason"] == "low-confidence"


# ---- the report ---------------------------------------------------- ----


def _verify(tmp_path, monkeypatch):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(base(names=["D", "Usop", "Government", "Raftel", "Zoro"], wiki="https://x.fandom.com/api.php")))
    answers = {"D": "Monkey D. Luffy", "Usop": "Usopp", "Government": "World Government"}
    answers |= {"Raftel": "Ratel", "Zoro": "Roronoa Zoro"}
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: list(answers.values()))
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    monkeypatch.setattr(gv, "adjudicate", lambda term, cands, show: high(answers[term]))
    return gv.verify(str(path)), json.loads(path.read_text())


def test_the_report_counts_blocked_expansions_with_a_breakdown_only_when_off(guards, tmp_path, monkeypatch):
    monkeypatch.delenv("VERIFY_QUEUE_BLOCKED_EXPANSIONS", raising=False)
    rep, _ = _verify(tmp_path, monkeypatch)
    assert "blocked_expansions" not in rep and "blocked_expansions_by_reason" not in rep  # default report shape
    monkeypatch.setenv("VERIFY_QUEUE_BLOCKED_EXPANSIONS", "0")
    rep, saved = _verify(tmp_path, monkeypatch)
    assert rep["blocked_expansions"] == 2
    assert rep["blocked_expansions_by_reason"] == {"common-word": 1, "expansion-guarded": 1}
    assert set(saved["flagged"]) == {"Raftel", "Usop"}  # the spelling fixes are queued
    assert rep["applied"] == 1  # Zoro -> Roronoa Zoro


# ---- old stored entries still work in review ----------------------- ----


def test_review_still_orders_and_accepts_old_entries_and_the_new_reason():
    g = {
        "flagged": {
            "Usop": {"reason": "respelling-needs-review", "canonical": "Usopp"},
            "Gov": {"reason": "common-word", "canonical": "World Government"},
            "Guarded": {"reason": "expansion-guarded", "canonical": "Guarded Name"},
        }
    }
    decisions, _ = ga.review_groups(g)
    assert [i["reason"] for i in decisions] == ["respelling-needs-review", "common-word", "expansion-guarded"]
    out = ga.record_decision(dict(g, names=[], phrases=[]), "Guarded", accept=True)  # a 'y' writes it like the others
    assert "Guarded Name" in out["names"] + out["phrases"] and "Guarded" not in out.get("flagged", {})
