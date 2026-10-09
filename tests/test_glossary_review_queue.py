"""The glossary review queue: a 'no match' has nothing to decide, so it can be left out of the queue (VERIFY_QUEUE_NO_MATCH=0) and
collapsed in the CLI. Synthetic data only."""

import json

import glossary_acquire as ga
import glossary_verify as gv

NO_MATCH = {"canonical": "", "confidence": "none", "dub_note": ""}
LOW = {"canonical": "Zorro", "confidence": "low", "dub_note": ""}
HIGH_EXP = {"canonical": "Roronoa Zoro", "confidence": "high", "dub_note": ""}
HIGH_RESP = {"canonical": "Zorro", "confidence": "high", "dub_note": ""}


def base(**extra):
    return {"show": "S", "names": ["Zoro"], "phrases": [], "hard_fixes": {}, **extra}


RESULTS = {"Nobody": NO_MATCH, "Lowly": LOW, "Zoro": HIGH_RESP}


# ---- apply_results --------------------------------------- ----


def test_by_default_a_no_match_is_queued_as_before(monkeypatch):
    """GUARD (passes on the old code): legacy behaviour is byte-identical with the variable unset or '1'."""
    for value in (None, "1"):
        if value is None:
            monkeypatch.delenv("VERIFY_QUEUE_NO_MATCH", raising=False)
        else:
            monkeypatch.setenv("VERIFY_QUEUE_NO_MATCH", value)
        out = gv.apply_results(base(names=["Zoro", "Nobody", "Lowly"]), RESULTS)
        assert out["flagged"]["Nobody"] == "no-match" and out["flagged"]["Lowly"] == "low-confidence"
        assert out["verified"] == ["Lowly", "Nobody", "Zoro"]


def test_with_the_queue_off_a_no_match_is_verified_but_not_flagged(monkeypatch):
    monkeypatch.setenv("VERIFY_QUEUE_NO_MATCH", "0")
    out = gv.apply_results(base(names=["Zoro", "Nobody", "Lowly"]), RESULTS)
    assert "Nobody" in out["verified"] and "Nobody" not in out["flagged"]
    assert out["flagged"]["Lowly"] == "low-confidence"  # a candidate to accept or reject: still a decision
    assert out["flagged"]["Zoro"]["reason"] == "respelling-needs-review"


def test_with_the_queue_off_and_only_no_matches_there_is_no_flagged_key(monkeypatch):
    monkeypatch.setenv("VERIFY_QUEUE_NO_MATCH", "0")
    out = gv.apply_results(base(names=["Nobody"]), {"Nobody": NO_MATCH})
    assert "flagged" not in out and out["verified"] == ["Nobody"]


def test_a_none_confidence_with_a_canonical_is_a_no_match_too(monkeypatch):
    """The legacy rule: only 'low' with a canonical is low-confidence; 'none' with a stray canonical is no-match."""
    monkeypatch.setenv("VERIFY_QUEUE_NO_MATCH", "0")
    out = gv.apply_results(base(names=["Nobody"]), {"Nobody": {"canonical": "Somebody", "confidence": "none"}})
    assert "flagged" not in out


def test_a_term_that_is_already_correct_is_never_a_no_match(monkeypatch):
    monkeypatch.setenv("VERIFY_QUEUE_NO_MATCH", "0")
    out = gv.apply_results(base(names=["Zoro"]), {"Zoro": {"canonical": "Zoro", "confidence": "high"}})
    assert "flagged" not in out


def test_legacy_stored_no_match_flags_are_left_alone(monkeypatch):
    monkeypatch.setenv("VERIFY_QUEUE_NO_MATCH", "0")
    out = gv.apply_results(base(names=["Old", "New"], flagged={"Old": "no-match"}), {"New": NO_MATCH})
    assert out["flagged"] == {"Old": "no-match"}


def _verify(tmp_path, monkeypatch):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(base(names=["Nobody", "Lowly", "Zoro"], wiki="https://x.fandom.com/api.php")))
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: ["Zorro"])
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    monkeypatch.setattr(gv, "adjudicate", lambda term, cands, show: RESULTS[term])
    return gv.verify(str(path))


def test_the_report_counts_no_matches_only_when_the_queue_is_off(tmp_path, monkeypatch):
    monkeypatch.delenv("VERIFY_QUEUE_NO_MATCH", raising=False)
    assert "no_match" not in _verify(tmp_path, monkeypatch)  # default report shape unchanged
    monkeypatch.setenv("VERIFY_QUEUE_NO_MATCH", "0")
    rep = _verify(tmp_path, monkeypatch)
    assert rep["no_match"] == 1 and rep["flagged"] == 2  # Nobody not queued; Lowly and Zoro are


# ---- review_items / review_groups / the CLI -------------- ----


def queue():
    return {
        "show": "S",
        "flagged": {
            "Aaa": "no-match",
            "Bbb": "no-match",
            "Low": "low-confidence",
            "Resp": {"reason": "respelling-needs-review", "canonical": "Respelled"},
            "Word": {"reason": "common-word", "canonical": "Word Long"},
            "Arc": {"reason": "not-in-arc-pages", "canonical": "Arc Long"},
            "Poss": {"reason": "possessive_floor_crossing", "canonical": "Poss"},
            "Odd": {"reason": "share-too-close", "canonical": "Odder"},
        },
    }


def test_review_items_still_lists_everything_sorted_by_term():
    """GUARD: the existing function keeps its contract; the grouping is a separate view."""
    assert [i["term"] for i in ga.review_items(queue())] == sorted(queue()["flagged"])


def test_decision_carrying_reasons_come_first_and_no_matches_are_collapsed():
    decisions, no_match = ga.review_groups(queue())
    assert [i["reason"] for i in decisions] == [
        "respelling-needs-review",
        "common-word",
        "not-in-arc-pages",
        "low-confidence",
        "possessive_floor_crossing",
        "share-too-close",
    ]
    assert [i["term"] for i in no_match] == ["Aaa", "Bbb"]
    assert len(decisions) + len(no_match) == len(ga.review_items(queue()))


def test_the_cli_walks_the_decisions_and_summarises_the_no_matches(tmp_path, monkeypatch, capsys):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(queue()))
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or "n")
    monkeypatch.setattr("sys.argv", ["glossary_acquire", str(path), str(tmp_path), "--review"])
    ga.main()
    shown = capsys.readouterr().out
    assert len(asked) == 6  # the six decision items; the two no-matches are not asked
    assert "2 no-match terms" in shown and "--review --all" in shown
    assert shown.index("Respelled") < shown.index("Word Long") < shown.index("Odder")


def test_review_all_walks_the_no_matches_last(tmp_path, monkeypatch, capsys):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(queue()))
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or "n")
    monkeypatch.setattr("sys.argv", ["glossary_acquire", str(path), str(tmp_path), "--review", "--all"])
    ga.main()
    shown = capsys.readouterr().out
    assert len(asked) == 8 and shown.index("Odder") < shown.index("Aaa") < shown.index("Bbb")
    assert "no-match terms" not in shown.replace("Aaa", "")  # nothing collapsed when everything is listed


def test_a_queue_with_no_no_matches_prints_no_summary(tmp_path, monkeypatch, capsys):
    path = tmp_path / "g.json"
    g = queue()
    g["flagged"] = {k: v for k, v in g["flagged"].items() if v != "no-match"}
    path.write_text(json.dumps(g))
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    monkeypatch.setattr("sys.argv", ["glossary_acquire", str(path), str(tmp_path), "--review"])
    ga.main()
    assert "no-match terms" not in capsys.readouterr().out


def test_an_answered_decision_is_recorded_and_the_summary_count_follows(tmp_path, monkeypatch, capsys):
    """y on the respelling-style entry is recorded exactly as before (record_decision), written with --apply."""
    path = tmp_path / "g.json"
    path.write_text(json.dumps(queue()))
    answers = iter(["y"] + ["n"] * 10)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr("sys.argv", ["glossary_acquire", str(path), str(tmp_path), "--review", "--apply"])
    ga.main()
    saved = json.loads(path.read_text())
    assert "Resp" not in saved["flagged"] and "Aaa" in saved["flagged"]


def test_low_confidence_without_a_candidate_is_a_no_match(monkeypatch):
    """Legacy rule: 'low-confidence' needs a canonical; a 'low' with none is a 'no-match'."""
    adj = {"canonical": "", "confidence": "low"}
    monkeypatch.delenv("VERIFY_QUEUE_NO_MATCH", raising=False)
    assert gv.apply_results(base(names=["X"]), {"X": adj})["flagged"]["X"] == "no-match"
    monkeypatch.setenv("VERIFY_QUEUE_NO_MATCH", "0")
    assert "flagged" not in gv.apply_results(base(names=["X"]), {"X": adj})
