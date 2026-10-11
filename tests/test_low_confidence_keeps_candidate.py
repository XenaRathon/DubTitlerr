"""Phase 29 F7: a low-confidence flag keeps the candidate the reviewer is asked to judge.

Sol's probe: Raftel -> {"canonical": "Laugh Tale", "confidence": "low"} was stored as the bare string "low-confidence". Review
showed "(no canonical)" and asked "mark this spelling correct as-is?", so the offered correction could never be approved."""

import json
import sys

import glossary_acquire as ga
import glossary_verify as gv


def verified():
    adj = {"canonical": "Laugh Tale", "confidence": "low"}
    return gv.apply_results({"show": "S", "names": ["Raftel"], "phrases": []}, {"Raftel": adj})


def test_the_flag_carries_the_candidate():
    assert verified()["flagged"]["Raftel"] == {"reason": "low-confidence", "canonical": "Laugh Tale"}


def test_review_shows_the_candidate_and_asks_to_accept_it(tmp_path, monkeypatch, capsys):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(verified()))
    asked = []
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review", "--apply"])
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or "n")
    ga.main()
    assert "Laugh Tale" in capsys.readouterr().out and asked == ["  accept this fix? [y/N/q] "]
    saved = json.loads(path.read_text())
    assert saved["known"] == ["Raftel"] and "flagged" not in saved, "n rejects the fix: the spelling is marked correct"


def test_accepting_a_same_length_candidate_writes_the_hard_fix():
    adj = {"canonical": "Ratel", "confidence": "low"}
    g = gv.apply_results({"show": "S", "names": ["Raftel"], "phrases": []}, {"Raftel": adj})
    approved = ga.record_decision(g, "Raftel", accept=True)
    assert approved["hard_fixes"] == {"Raftel": "Ratel"} and "flagged" not in approved


def test_an_accepted_longer_candidate_is_still_refused_pending_a_write_policy():
    """Sol: accepted multiword candidates need a deliberate review/write policy. Unchanged here: refused, evidence kept."""
    approved = ga.record_decision(verified(), "Raftel", accept=True)
    assert approved["flagged"]["Raftel"]["reason"] == "unsafe-canonical-rejected" and "hard_fixes" not in approved


def test_a_stored_bare_string_still_loads_as_a_candidate_less_item():
    g = {"show": "S", "names": ["Raftel"], "flagged": {"Raftel": "low-confidence"}}
    (item,) = ga.review_items(g)
    assert item["reason"] == "low-confidence" and item["canonical"] == ""
    decisions, no_match = ga.review_groups(g)
    assert [i["term"] for i in decisions] == ["Raftel"] and no_match == []


def test_no_candidate_still_flags_no_match_as_before(monkeypatch):
    monkeypatch.setenv("VERIFY_QUEUE_NO_MATCH", "1")
    out = gv.apply_results({"show": "S", "names": ["X"], "phrases": []}, {"X": {"canonical": "", "confidence": "low"}})
    assert out["flagged"]["X"] == "no-match"
