"""Soft stop inside the long per-show glossary steps (mine, acquire, verify).

gen_loop.sh checks the stop flag BEFORE starting each step, but a step already running when
SIGTERM arrives ran to its own end -- longer than the docker stop grace, so the container was
SIGKILLed anyway. Each step now checks common.stop_requested() between units, at points where
everything completed so far is already persisted (or nothing is, and nothing is written).
Written test-first.
"""

import json
import sys

import pytest

import acquire_cache
import glossary_acquire as ga
import glossary_verify as gv
import mine_glossary


@pytest.fixture
def flag(tmp_path, monkeypatch):
    """STOP_FLAG pointing at a file that does not exist yet; call .touch() to raise it."""
    p = tmp_path / "stop.flag"
    monkeypatch.setenv("STOP_FLAG", str(p))
    return p


# --- mine_glossary ------------------------------------------------------------------


def _mine_world(tmp_path, monkeypatch, n_eps=3):
    show = tmp_path / "Some Show"
    show.mkdir()
    for i in range(n_eps):
        (show / f"E0{i}.mkv").write_text("")
    gloss = tmp_path / "gloss"
    gloss.mkdir()
    gpath = gloss / "Some Show.json"
    original = json.dumps({"show": "Some Show", "initial_prompt": "keep", "names": ["Old"], "hard_fixes": {}})
    gpath.write_text(original)
    monkeypatch.setattr(mine_glossary, "GLOSS_DIR", str(gloss))
    monkeypatch.setattr(mine_glossary, "MIN_COUNT", 1)
    monkeypatch.setattr(sys, "argv", ["mine_glossary.py", str(show)])
    return gpath, original


def test_mine_stops_between_episodes_and_leaves_the_glossary_untouched(tmp_path, monkeypatch, flag, capsys):
    gpath, original = _mine_world(tmp_path, monkeypatch)
    seen = []

    def fake_text(video):
        seen.append(video)
        flag.touch()  # SIGTERM lands while episode 1 is being read
        return "I saw Brownbeard come.\nI saw Brownbeard leave.\n"

    monkeypatch.setattr(mine_glossary, "eng_sub_text", fake_text)

    assert mine_glossary.main() is None  # normal return -> exit status 0
    assert len(seen) == 1
    assert gpath.read_text() == original  # nothing half-counted was written
    json.loads(gpath.read_text())
    assert "stop requested: leaving mine after 1 episodes" in capsys.readouterr().out


def test_mine_without_the_flag_reads_every_episode(tmp_path, monkeypatch):
    """GUARD (passes on old code too): no flag, behaviour unchanged."""
    gpath, _ = _mine_world(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(
        mine_glossary, "eng_sub_text", lambda v: seen.append(v) or "I saw Brownbeard come.\nI saw Brownbeard leave.\n"
    )

    mine_glossary.main()

    assert len(seen) == 3
    assert "Brownbeard" in json.loads(gpath.read_text())["names"]


# --- glossary_verify ----------------------------------------------------------------


def _verify_world(tmp_path, monkeypatch):
    gpath = tmp_path / "g.json"
    gpath.write_text(json.dumps({"show": "S", "names": ["A", "B", "C", "D"], "hard_fixes": {}}))
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: ["A", "B", "C", "D"])
    monkeypatch.setattr(gv, "candidates", lambda term, titles, k=gv.TOPK: [term])
    monkeypatch.setattr(gv, "VERIFY_WORKERS", 1)  # serial: "the first unit" is well defined
    return gpath


def test_verify_stops_after_the_first_term_and_persists_only_completed_ones(tmp_path, monkeypatch, flag, capsys):
    gpath = _verify_world(tmp_path, monkeypatch)
    calls = []

    def fake_adjudicate(term, cands, show):
        calls.append(term)
        flag.touch()
        return {"canonical": term, "confidence": "high", "dub_note": ""}

    monkeypatch.setattr(gv, "adjudicate", fake_adjudicate)

    rep = gv.verify(str(gpath))

    assert calls == ["A"]
    g = json.loads(gpath.read_text())  # parses
    assert g["verified"] == ["A"]  # skipped terms stay pending, NOT marked verified
    assert g["names"] == ["A", "B", "C", "D"]
    assert rep["checked"] == 1 and rep["note"] == "stopped"
    assert "stop requested: leaving verify after 1 terms" in capsys.readouterr().out


def test_verify_stopped_before_any_term_writes_nothing(tmp_path, monkeypatch, flag):
    gpath = _verify_world(tmp_path, monkeypatch)
    before = gpath.read_text()
    flag.touch()
    monkeypatch.setattr(gv, "adjudicate", lambda *a: pytest.fail("adjudicated after stop"))

    rep = gv.verify(str(gpath))

    assert gpath.read_text() == before
    assert rep["note"] == "stopped"


def test_verify_without_the_flag_checks_every_term(tmp_path, monkeypatch, flag):
    """GUARD: STOP_FLAG set but file absent -> everything runs as before."""
    gpath = _verify_world(tmp_path, monkeypatch)
    monkeypatch.setattr(gv, "adjudicate", lambda t, c, s: {"canonical": t, "confidence": "high", "dub_note": ""})

    rep = gv.verify(str(gpath))

    assert rep["checked"] == 4 and "note" not in rep
    assert json.loads(gpath.read_text())["verified"] == ["A", "B", "C", "D"]


# --- glossary_acquire ---------------------------------------------------------------


def _pair(variant, canonical):
    return {
        "variant": variant,
        "canonical": canonical,
        "variant_count": 21,
        "canonical_count": 8,
        "score": 0.84,
        "verdict": "flag",
        "reason": "share-too-close",
        "bound": 0.1,
    }


def test_escalate_stops_between_pairs_keeping_the_completed_adjudications(monkeypatch, flag):
    calls = []

    def fake(v, c, cv, cc, s):
        calls.append(v)
        flag.touch()
        return {"same_entity": True, "confidence": "high"}

    monkeypatch.setattr(ga, "adjudicate_merge", fake)
    cache = {}

    with pytest.raises(ga.StopRequested) as e:
        ga.escalate([_pair("Deccan", "Decken"), _pair("Smokey", "Smoker")], {}, "S", cache=cache)

    assert calls == ["Deccan"] and e.value.done == 1
    assert acquire_cache.escalation_for(cache, "Deccan", "Decken")
    assert not acquire_cache.escalation_for(cache, "Smokey", "Smoker")


def test_escalate_without_the_flag_adjudicates_every_pair(monkeypatch, flag):
    """GUARD (passes on old code too)."""
    calls = []
    monkeypatch.setattr(
        ga, "adjudicate_merge", lambda v, c, cv, cc, s: calls.append(v) or {"same_entity": True, "confidence": "high"}
    )

    out = ga.escalate([_pair("Deccan", "Decken"), _pair("Smokey", "Smoker")], {}, "S", cache={})

    assert calls == ["Deccan", "Smokey"] and [p["verdict"] for p in out] == ["apply", "apply"]


def _acquire_world(tmp_path, monkeypatch):
    gp = tmp_path / "S.json"
    gp.write_text(json.dumps({"show": "S"}))
    text = ["Hey Smokey.", "Smokey again.", "Smokey thrice.", "Hey Deccan.", "Deccan again.", "Deccan thrice."]
    text += ["Smoker is here.", "Smoker again.", "Smoker thrice.", "Smoker once more."] * 2
    text += ["Decken is here.", "Decken again.", "Decken thrice.", "Decken once more."] * 2
    (tmp_path / "Ep01.dubtitles.conf.json").write_text(
        json.dumps([{"text": t, "start": i, "end": i + 1} for i, t in enumerate(text * 6)])
    )
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Smoker", "Decken"])
    return gp


def test_acquire_stops_during_escalation_writes_no_glossary_and_keeps_the_cache(tmp_path, monkeypatch, flag, capfd):
    gp = _acquire_world(tmp_path, monkeypatch)
    before = gp.read_text()
    calls = []

    def fake(v, c, cv, cc, s):
        calls.append((v, c))
        flag.touch()
        return {"same_entity": True, "confidence": "high"}

    monkeypatch.setattr(ga, "adjudicate_merge", fake)

    rep = ga.acquire(str(gp), str(tmp_path), apply=True)

    assert len(calls) == 1, calls
    assert rep["note"] == "stopped" and "proposals" not in rep
    assert gp.read_text() == before  # the half-decided run applied nothing
    cache = acquire_cache.load(str(gp))
    assert acquire_cache.escalation_for(cache, *calls[0])  # the finished pair survives
    assert "stop requested: leaving escalate after 1 pairs" in capfd.readouterr().out


def test_acquire_stops_between_tier_b_terms_without_writing(tmp_path, monkeypatch, flag, capfd):
    gp = _acquire_world(tmp_path, monkeypatch)
    before = gp.read_text()
    monkeypatch.setattr(ga, "unmatched", lambda *a, **k: ["Zed", "Yan"])
    calls = []

    def fake(term, cands, show):
        calls.append(term)
        flag.touch()
        return {"canonical": "", "confidence": "none", "dub_note": ""}

    monkeypatch.setattr(ga.glossary_verify, "adjudicate", fake)
    monkeypatch.setattr(ga, "adjudicate_merge", lambda *a: {"same_entity": False, "confidence": "low"})

    rep = ga.acquire(str(gp), str(tmp_path), apply=True)

    assert calls == ["Zed"]
    assert rep["note"] == "stopped"
    assert gp.read_text() == before
    json.loads(gp.read_text())
    assert "stop requested: leaving tier-b after 1 terms" in capfd.readouterr().out


def test_acquire_main_returns_normally_when_stopped(tmp_path, monkeypatch, flag):
    gp = _acquire_world(tmp_path, monkeypatch)
    flag.touch()
    monkeypatch.setattr(ga, "adjudicate_merge", lambda *a: pytest.fail("adjudicated after stop"))
    monkeypatch.setattr(sys, "argv", ["glossary_acquire.py", str(gp), str(tmp_path), "--apply"])

    assert ga.main() is None  # no SystemExit: exit status 0


def test_acquire_without_the_flag_still_proposes_and_applies(tmp_path, monkeypatch, flag):
    """GUARD (passes on old code too): flag unset -> the run completes as before."""
    gp = _acquire_world(tmp_path, monkeypatch)
    monkeypatch.setattr(ga, "adjudicate_merge", lambda *a: {"same_entity": False, "confidence": "low"})

    rep = ga.acquire(str(gp), str(tmp_path), apply=False)

    assert rep["proposed"] > 0 and "note" not in rep
