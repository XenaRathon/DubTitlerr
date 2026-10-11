"""glossary_acquire journals each completed adjudication (tier C pairs and tier B picks) so an interrupted run resumes."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import adjudication_journal as aj
import glossary_acquire as ga
import glossary_decision as gd
import glossary_verify as gv

ROOT = Path(__file__).resolve().parents[1]
PAIRS = [("Smokey", "Smoker"), ("Brannic", "Brannoc"), ("Tilvash", "Tilvish"), ("Jorvane", "Jorvene"), ("Kelmara", "Kelmira")]
YES = json.dumps({"same_entity": True, "confidence": "high"})


def build_show(d, pairs=PAIRS, extra=()):
    d.mkdir(parents=True, exist_ok=True)
    texts = []
    for v, c in pairs:
        texts += [
            f"Hey {v}.",
            f"{v} again.",
            f"{v} thrice.",
            f"{c} is here.",
            f"{c} again.",
            f"{c} thrice.",
            f"{c} once more.",
        ] * 6
    texts += list(extra)
    (d / "Ep01.dubtitles.conf.json").write_text(json.dumps([{"start": i, "end": i + 1, "text": t} for i, t in enumerate(texts)]))
    gp = d / "S.json"
    gp.write_text(json.dumps({"show": "S"}))
    return gp


@pytest.fixture
def acq(tmp_path, monkeypatch):
    monkeypatch.delenv("ACQUIRE_NO_CACHE", raising=False)
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    monkeypatch.setattr(gv, "backend_problem", lambda backend=None: "")
    monkeypatch.setattr(gv, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda *a, **k: [c for _, c in PAIRS])
    state = {"calls": [], "llm": lambda prompt: YES}

    def fake_llm(prompt, **kw):
        state["calls"].append(prompt)
        return state["llm"](prompt)

    monkeypatch.setattr(ga, "llm_chat", fake_llm)
    gp = build_show(tmp_path / "show")

    def go(apply=False):
        return ga.acquire(str(gp), str(gp.parent), apply=apply)

    go.state, go.gp = state, gp
    go.journal = lambda: (
        [json.loads(x) for x in Path(str(gp)[:-5] + ".acquire.journal.jsonl").read_text().splitlines()]
        if Path(str(gp)[:-5] + ".acquire.journal.jsonl").exists()
        else []
    )
    go.drop_cache = lambda: Path(ga.acquire_cache.path_for(str(gp))).unlink(missing_ok=True)
    return go


def test_each_pair_answer_is_journaled_as_it_completes(acq):
    seen = []
    base = acq.state["llm"]

    def llm(prompt):
        seen.append(len(acq.journal()))
        return base(prompt)

    acq.state["llm"] = llm
    acq()
    assert seen == [0, 1, 2, 3, 4], seen


def test_a_rerun_without_the_end_of_run_cache_reuses_the_journal_and_reports_the_same(acq):
    first = acq()
    n = len(acq.state["calls"])
    assert n == len(PAIRS)
    acq.drop_cache()  # what a kill leaves: the journal, but never the cache that is saved after escalation
    second = acq()
    assert len(acq.state["calls"]) == n, "no model call on the rerun"
    assert second == first, "a resumed dry run reports completely and identically"


def test_a_changed_context_or_model_is_asked_again(acq, monkeypatch):
    acq()
    base = len(acq.state["calls"])
    acq.drop_cache()
    conf = acq.gp.parent / "Ep01.dubtitles.conf.json"
    conf.write_text(conf.read_text().replace("Hey Smokey.", "Hey Smokey, listen."))  # Smokey's context lines change
    acq()
    asked = len(acq.state["calls"]) - base
    assert asked == 1, "only the pair whose context lines changed (Smokey/Smoker) is asked again"
    acq.drop_cache()
    monkeypatch.setattr(gv, "VERIFY_MODEL", "another-model")
    before = len(acq.state["calls"])
    acq()
    assert len(acq.state["calls"]) == before + len(PAIRS), "a different model re-asks every pair"


def test_an_unavailable_answer_is_never_journaled_and_is_retried(acq):
    acq.state["llm"] = lambda prompt: ""
    acq()
    assert acq.journal() == []
    acq.state["llm"] = lambda prompt: YES
    acq()
    assert len(acq.journal()) == len(PAIRS)


def test_acquire_no_cache_neither_reads_nor_writes_the_journal(acq, monkeypatch):
    monkeypatch.setenv("ACQUIRE_NO_CACHE", "1")
    acq()
    assert acq.journal() == []
    monkeypatch.delenv("ACQUIRE_NO_CACHE")
    acq()
    n = len(acq.state["calls"])
    acq.drop_cache()
    monkeypatch.setenv("ACQUIRE_NO_CACHE", "1")
    acq()
    assert len(acq.state["calls"]) == n + len(PAIRS)


def test_an_apply_compacts_the_journal_and_a_dry_run_does_not(acq):
    acq()
    acq.drop_cache()
    acq()  # a second dry run appends nothing new (all reused) and does not rewrite
    mtime = os.stat(str(acq.gp)[:-5] + ".acquire.journal.jsonl").st_mtime_ns
    acq(apply=True)
    assert len(acq.journal()) == len(PAIRS)
    assert os.stat(str(acq.gp)[:-5] + ".acquire.journal.jsonl").st_mtime_ns >= mtime


def test_tier_b_term_picks_are_journaled_and_reused(tmp_path, monkeypatch):
    monkeypatch.delenv("ACQUIRE_NO_CACHE", raising=False)
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"show": "One Pace"}))
    (tmp_path / "Ep01.dubtitles.conf.json").write_text(
        json.dumps(
            [
                {"start": i, "end": i + 1, "text": t}
                for i, t in enumerate(["I saw Kasumi walk.", "I saw Kasumi again.", "I saw Kasumi thrice."] * 3)
            ]
        )
    )
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "backend_problem", lambda backend=None: "")
    monkeypatch.setattr(gv, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda *a, **k: ["Shirahoshi", "Misty"])
    monkeypatch.setattr(gv, "candidates", lambda term, titles, k=6: ["Misty"])
    calls = []
    monkeypatch.setattr(
        gv, "llm_chat", lambda *a, **k: calls.append(1) or json.dumps({"canonical": "Misty", "confidence": "high"})
    )
    monkeypatch.setattr(ga, "llm_chat", gv.llm_chat)
    first = ga.acquire(str(gp), str(tmp_path))
    assert len(calls) == 1 and first["tier_b"]
    journal = [json.loads(x) for x in (tmp_path / "One Pace.acquire.journal.jsonl").read_text().splitlines()]
    assert [e["key"] for e in journal] == [aj.pick_key("Kasumi")]
    second = ga.acquire(str(gp), str(tmp_path))
    assert len(calls) == 1 and second == first


# ---- the decision backend ------------------------------------------------------------------------------------------------------


def test_decision_pair_answers_are_journaled_with_model_and_acquire_tau_and_a_fallback_answer_is_not(acq, monkeypatch):
    monkeypatch.setenv("ACQUIRE_BACKEND", "decision")
    monkeypatch.setenv("VERIFY_DECISION_MODEL", "inception/mercury-decide:free")
    monkeypatch.setenv("ACQUIRE_DECISION_TAU", "0.8")
    monkeypatch.setattr(gv, "backend_problem", lambda backend=None: "")
    monkeypatch.setattr(gv, "begin_run", lambda *a, **k: None)
    monkeypatch.setattr(gv, "end_run", lambda rep, *a, **k: rep)
    seen = []

    def fake(variant, canonical, ctx_v, ctx_c, show, local):
        seen.append(variant)
        if variant == "Smokey":
            return local()  # the hosted call failed; the local model answered
        if variant == "Brannic":
            return {"same_entity": False, "confidence": "none", "unavailable": True}
        return {"same_entity": True, "confidence": "high"}

    monkeypatch.setattr(gd, "adjudicate_pair", fake)
    acq()
    keys = {e["key"].split(aj.SEP)[1] for e in acq.journal()}
    assert keys == {"Tilvash", "Jorvane", "Kelmara"}
    prov = acq.journal()[0]["prov"]
    assert prov["backend"] == "decision" and prov["model"] == "inception/mercury-decide:free" and prov["tau"] == 0.8


# ---- kill and restart ---------------------------------------------------------------------------------------------------

RUNNER = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
import glossary_acquire as ga, glossary_verify as gv
gloss, show_dir, die_after, apply = sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5] == "apply"
TITLES = __TITLES__
gv.VERIFY_BACKEND = "llamacpp"; gv.BACKEND_PROBLEM = ""
gv.backend_problem = lambda backend=None: ""
gv.resolve_wiki = lambda *a, **k: "https://x/api.php"
gv.fetch_titles = lambda *a, **k: TITLES
n = {"calls": 0}
def llm(prompt, **kw):
    if n["calls"] >= die_after >= 0:
        os._exit(9)  # a hard stop: no cleanup, no end-of-run cache save, no cooperative anything
    n["calls"] += 1
    return json.dumps({"same_entity": True, "confidence": "high"})
ga.llm_chat = llm
rep = ga.acquire(gloss, show_dir, apply=apply)
print(json.dumps({"report": rep, "calls": n["calls"]}, sort_keys=True, default=str))
""".replace("__TITLES__", repr([c for _, c in PAIRS]))


def last_json(proc, d):
    """The runner's last stdout line as JSON, with this run's directory masked (the report names stems by absolute path)."""
    return json.loads(proc.stdout.strip().splitlines()[-1].replace(str(d), "<DIR>"))


def run_acquire(d, gloss, die_after, apply):
    script = d / "runner.py"
    script.write_text(RUNNER)
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    env.pop("ACQUIRE_NO_CACHE", None)
    return subprocess.run(
        [sys.executable, str(script), str(ROOT), str(gloss), str(d), str(die_after), "apply" if apply else "dry"],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )


@pytest.mark.parametrize("apply", [False, True])
def test_killed_mid_escalation_then_restarted_equals_an_uninterrupted_run(tmp_path, apply):
    clean_gloss = build_show(tmp_path / "clean")
    clean = run_acquire(clean_gloss.parent, clean_gloss, -1, apply)
    assert clean.returncode == 0, clean.stderr
    clean_out = last_json(clean, clean_gloss.parent)

    gloss = build_show(tmp_path / "resumed")
    killed = run_acquire(gloss.parent, gloss, 3, apply)
    assert killed.returncode == 9
    journal = gloss.parent / "S.acquire.journal.jsonl"
    assert len(journal.read_text().splitlines()) == 3, "three completed pair answers survived the kill"
    assert not Path(ga.acquire_cache.path_for(str(gloss))).exists(), (
        "the end-of-run cache was never written: only the journal carries them"
    )
    resumed = run_acquire(gloss.parent, gloss, -1, apply)
    assert resumed.returncode == 0, resumed.stderr
    out = last_json(resumed, gloss.parent)
    assert out["calls"] == len(PAIRS) - 3, "only the unfinished pairs were asked again"
    assert out["report"] == clean_out["report"]
    assert gloss.read_bytes() == clean_gloss.read_bytes()


def test_the_help_says_how_to_bust_both_stored_answers(monkeypatch, capsys):
    """escalate() consults the older <glossary>.acquire-cache.json BEFORE the journal, so an old cache shadows it."""
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", "--help"])
    with pytest.raises(SystemExit):
        ga.main()
    out = "".join(capsys.readouterr().out.split())  # argparse wraps the epilog, even inside a file name
    assert "acquire-cache.json" in out and "acquire.journal.jsonl" in out and "ACQUIRE_NO_CACHE=1" in out
