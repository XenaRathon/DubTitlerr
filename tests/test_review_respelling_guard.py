"""Phase 29 follow-up: an approved same-length respelling is a hard fix ONLY when the term is not an ordinary English word.

Reviewer repro: Burn -> Coburn, Sun -> Sunny, Brook -> Brooke, Robin -> Robins and D -> Do all reach respelling-needs-review (they
are substring matches that the whole-word guard flags before the common-word guard sees them), and a 'y' then rewrote every
"burn", "sun", ... in the show. The check is the production one (glossary.is_ordinary_word), not a letter count, so real short
names (Kid, Law, Gin) are unaffected."""

import json
import sys

import pytest

import glossary
import glossary_acquire as ga
import glossary_verify as gv

ORDINARY = {"burn", "sun", "brook", "robin", "d", "do"}


@pytest.fixture
def wordlist(monkeypatch):
    monkeypatch.setattr(glossary, "_ORDINARY", set(ORDINARY))
    monkeypatch.setattr(glossary, "_ORDINARY_STATUS", "ok")


def flagged(term, canon):
    g = gv.apply_results({"show": "S", "names": [term], "phrases": []}, {term: {"canonical": canon, "confidence": "high"}})
    assert g["flagged"][term]["reason"] == "respelling-needs-review"
    return g


@pytest.mark.parametrize(
    "term,canon", [("Burn", "Coburn"), ("Sun", "Sunny"), ("Brook", "Brooke"), ("Robin", "Robins"), ("D", "Do")]
)
def test_an_ordinary_word_stays_additive_and_says_why(wordlist, capsys, term, canon):
    approved = ga.record_decision(flagged(term, canon), term, accept=True)
    assert "hard_fixes" not in approved
    assert canon in approved["names"] and term in approved["names"] and "flagged" not in approved
    assert approved["acquired"][term]["reason"] == "human-approved"
    assert glossary.correct(f"{term} said {term.lower()} it", glossary.load_dict(approved))[0].count(canon) == 0
    out = capsys.readouterr().out
    assert out.count("ordinary English word") == 1 and term in out


@pytest.mark.parametrize("term,canon", [("Usop", "Usopp"), ("Kid", "Kidd"), ("Law", "Lawe")])
def test_a_name_that_is_not_an_english_word_is_still_a_hard_fix(wordlist, term, canon):
    approved = ga.record_decision(flagged(term, canon), term, accept=True)
    assert approved["hard_fixes"] == {term: canon}


def test_a_case_only_respelling_is_still_a_hard_fix(wordlist):
    g = {"show": "S", "names": ["luffy"], "flagged": {"luffy": {"reason": "respelling-needs-review", "canonical": "Luffy"}}}
    assert ga.record_decision(g, "luffy", accept=True)["hard_fixes"] == {"luffy": "Luffy"}


def test_a_non_expansion_respelling_is_unchanged_whatever_the_word(wordlist):
    g = {"show": "S", "names": ["Sun"], "flagged": {"Sun": {"reason": "respelling-needs-review", "canonical": "Son"}}}
    assert ga.record_decision(g, "Sun", accept=True)["hard_fixes"] == {"Sun": "Son"}  # not an expansion: the old rule, as before


def run_review(monkeypatch, tmp_path, glossary_doc):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(glossary_doc))
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review"])
    monkeypatch.setattr("builtins.input", lambda *a: "q")
    ga.main()


def test_the_prompt_states_the_consequence_of_y(wordlist, tmp_path, monkeypatch, capsys):
    run_review(monkeypatch, tmp_path, flagged("Usop", "Usopp"))
    assert 'y rewrites every "Usop" in this show' in capsys.readouterr().out
    run_review(monkeypatch, tmp_path, flagged("Burn", "Coburn"))
    out = capsys.readouterr().out
    assert "y adds it as a name only" in out and "rewrites every" not in out


def test_the_prompt_text_itself_is_unchanged(wordlist, tmp_path, monkeypatch):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(flagged("Usop", "Usopp")))
    asked = []
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review"])
    monkeypatch.setattr("builtins.input", lambda p="": asked.append(p) or "q")
    ga.main()
    assert asked == ["  accept this fix? [y/N/q] "]
