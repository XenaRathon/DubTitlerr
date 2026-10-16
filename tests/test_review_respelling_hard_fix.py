"""Phase 29 F6: a human-approved respelling that the whole-word guard flagged must become a deterministic correction.

Sol's probe: Usop -> Usopp is an `is_expansion` substring match, so VERIFY_WRITE_WHOLE_WORD flags it 'respelling-needs-review';
the old review path then re-classified it as an expansion, appended Usopp to names, cleared the flag and recorded the term as
approved, but wrote no hard fix, so the runtime still left 'Usop' exactly as spoken."""

import json
import sys

import glossary
import glossary_acquire as ga
import glossary_verify as gv


def flagged(term, canon, **env):
    return gv.apply_results({"show": "S", "names": [term], "phrases": []}, {term: {"canonical": canon, "confidence": "high"}})


def test_accepting_a_whole_word_blocked_respelling_writes_a_hard_fix_that_corrects_text():
    g = flagged("Usop", "Usopp")
    assert g["flagged"]["Usop"]["reason"] == "respelling-needs-review"
    approved = ga.record_decision(g, "Usop", accept=True)
    assert approved["hard_fixes"] == {"Usop": "Usopp"}
    assert "flagged" not in approved and approved["acquired"]["Usop"]["reason"] == "human-approved"
    assert glossary.correct("Usop is here.", glossary.load_dict(approved))[0] == "Usopp is here."


def test_the_same_through_the_review_cli(tmp_path, monkeypatch):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(flagged("Usop", "Usopp")))
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review", "--apply"])
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    ga.main()
    assert glossary.correct("Usop is here.", glossary.load(str(path)))[0] == "Usopp is here."


def test_a_genuine_multi_token_expansion_stays_additive():
    g = flagged("D", "Monkey D. Luffy")  # fewer than two letters: held back by the whole-word guard, but a longer form
    assert g["flagged"]["D"]["reason"] == "respelling-needs-review"
    approved = ga.record_decision(g, "D", accept=True)
    assert "hard_fixes" not in approved and "Monkey D. Luffy" in approved["phrases"] and "D" in approved["names"]


def test_other_write_blocked_reasons_stay_additive(monkeypatch):
    monkeypatch.setattr(glossary, "is_ordinary_word", lambda t: t.lower() == "drake")
    g = flagged("Drake", "X Drake")
    assert g["flagged"]["Drake"]["reason"] == "common-word"
    approved = ga.record_decision(g, "Drake", accept=True)
    assert "hard_fixes" not in approved and "X Drake" in approved["phrases"]


def test_a_reject_is_unchanged():
    g = flagged("Usop", "Usopp")
    rejected = ga.record_decision(g, "Usop", accept=False)
    assert "hard_fixes" not in rejected and rejected["known"] == ["Usop"]
