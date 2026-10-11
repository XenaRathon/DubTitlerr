"""glossary_verify journals each completed adjudication, so an interrupted run resumes without repeating LLM calls."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import adjudication_journal as aj
import glossary_decision as gd
import glossary_verify as gv

ROOT = Path(__file__).resolve().parents[1]
TITLES = ["Zorro", "Nami", "Usopp", "Sanjy", "Robyn"]
TERMS = ["Zoro", "Nami", "Usop", "Sanji", "Robin"]
ANSWERS = dict(zip(TERMS, TITLES))


def reply(prompt):
    term = prompt.split('Term as transcribed/mined: "')[1].split('"')[0]
    return json.dumps({"canonical": ANSWERS[term], "confidence": "high", "dub_note": ""})


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(gv, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    monkeypatch.setattr(gv, "backend_problem", lambda backend=None: "")
    monkeypatch.setattr(gv, "resolve_wiki", lambda *a, **k: "https://example.fandom.com/api.php")
    monkeypatch.setattr(gv, "VERIFY_WORKERS", 1)
    monkeypatch.delenv("VERIFY_NO_JOURNAL", raising=False)
    state = {"calls": [], "titles": list(TITLES), "llm": reply}
    monkeypatch.setattr(gv, "fetch_titles", lambda *a, **k: state["titles"])

    def fake_llm(prompt, **kw):
        state["calls"].append(prompt)
        return state["llm"](prompt)

    monkeypatch.setattr(gv, "llm_chat", fake_llm)
    path = tmp_path / "S.json"

    def go(force=False):
        # Every run starts from the same pending glossary; --force (which bypasses the journal's reads) is exercised explicitly.
        path.write_text(
            json.dumps({"show": "S", "names": list(TERMS), "phrases": [], "wiki": "https://example.fandom.com/api.php"})
        )
        return gv.verify(str(path), force=force)

    go.state, go.path, go.tmp = state, path, tmp_path
    return go


def journal_lines(run):
    files = list((run.tmp / "cache").glob("*.verify.journal.jsonl"))
    return [json.loads(x) for f in files for x in f.read_text().splitlines()]


def test_a_rerun_reuses_every_completed_adjudication_and_gives_identical_output(run):
    first = run()
    n = len(run.state["calls"])
    assert n == len(TERMS)
    glossary_after_first = run.path.read_bytes()
    second = run()  # the same pending glossary again
    assert len(run.state["calls"]) == n, "no model call on the rerun"
    assert second == first and run.path.read_bytes() == glossary_after_first


def test_each_result_is_journaled_as_it_completes(run, monkeypatch):
    seen = []

    def llm(prompt):
        seen.append(len(journal_lines(run)))  # lines already durable when the NEXT call starts
        return reply(prompt)

    run.state["llm"] = llm
    run()
    assert seen == [0, 1, 2, 3, 4], seen


def test_a_changed_candidate_list_model_or_show_is_asked_again(run, monkeypatch):
    run()
    base = len(run.state["calls"])
    run.state["titles"] = TITLES + ["Zorro Jr"]  # only Zoro's candidate list grows; the others' lists are unchanged
    run()
    assert len(run.state["calls"]) == base + 1, "only the term whose candidates changed is asked again"
    after_titles = len(run.state["calls"])
    monkeypatch.setattr(gv, "VERIFY_MODEL", "another-model")
    run()
    assert len(run.state["calls"]) == after_titles + len(TERMS), "a different model re-asks every term"
    # The old-provenance lines were ignored while the run was in flight (not deleted); the clean apply then compacted them away.
    assert {e["prov"]["model"] for e in journal_lines(run)} == {"another-model"}


def test_an_unavailable_answer_is_never_journaled_and_is_retried(run):
    run.state["llm"] = lambda prompt: ""  # the local server is down: llm_chat returns ""
    run()
    assert journal_lines(run) == []
    run.state["llm"] = reply
    run()
    assert len(journal_lines(run)) == len(TERMS)


def test_an_unparseable_reply_is_never_journaled(run):
    run.state["llm"] = lambda prompt: "I could not decide, sorry."
    run()
    assert journal_lines(run) == []


def test_verify_no_journal_neither_reads_nor_writes_it(run, monkeypatch):
    monkeypatch.setenv("VERIFY_NO_JOURNAL", "1")
    run()
    assert journal_lines(run) == []
    monkeypatch.delenv("VERIFY_NO_JOURNAL")
    run()
    n = len(run.state["calls"])
    monkeypatch.setenv("VERIFY_NO_JOURNAL", "1")
    run()
    assert len(run.state["calls"]) == n + len(TERMS), "an existing journal is not consulted either"


def test_a_clean_apply_compacts_the_journal(run):
    run()
    run()
    lines = journal_lines(run)
    assert len(lines) == len(TERMS) and len({e["key"] for e in lines}) == len(TERMS)


def test_a_corrupt_journal_does_not_abort_the_run(run):
    run()
    for f in (run.tmp / "cache").glob("*.verify.journal.jsonl"):
        f.write_bytes(b"\x00\xff not json at all\n{\n")
    before = len(run.state["calls"])
    rep = run()
    assert rep["checked"] == len(TERMS) and len(run.state["calls"]) == before + len(TERMS)


# ---- the decision backend -----------------------------------------------------------------------------------------------------


@pytest.fixture
def decision(run, monkeypatch):
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "decision")
    monkeypatch.setenv("VERIFY_DECISION_MODEL", "inception/mercury-decide:free")
    monkeypatch.setenv("VERIFY_DECISION_TAU", "0.5")
    monkeypatch.setenv("VERIFY_DECISION_FALLBACK", "local")
    monkeypatch.setattr(gv, "begin_run", lambda *a, **k: None)
    monkeypatch.setattr(gv, "end_run", lambda rep, *a, **k: rep)
    calls = []

    def fake(term, titles, show, local):
        calls.append(term)
        return {"canonical": ANSWERS[term], "confidence": "high", "dub_note": ""}

    monkeypatch.setattr(gd, "adjudicate_verify", fake)
    run.decision_calls = calls
    return run


def test_decision_results_are_journaled_with_the_model_and_threshold_and_reused(decision, monkeypatch):
    decision()
    assert len(decision.decision_calls) == len(TERMS)
    prov = journal_lines(decision)[0]["prov"]
    assert prov["backend"] == "decision" and prov["model"] == "inception/mercury-decide:free" and prov["tau"] == 0.5
    decision()
    assert len(decision.decision_calls) == len(TERMS), "reused"
    monkeypatch.setenv("VERIFY_DECISION_TAU", "0.9")
    decision()
    assert len(decision.decision_calls) == 2 * len(TERMS), "a different threshold is a different question"


def test_a_decision_failure_and_a_local_fallback_answer_are_not_journaled(decision, monkeypatch):
    def fake(term, titles, show, local):
        decision.decision_calls.append(term)
        if term == "Zoro":
            return None  # the hosted call failed with fallback none: pending
        if term == "Nami":
            return local()  # the hosted call failed and the LOCAL model answered
        return {"canonical": ANSWERS[term], "confidence": "high", "dub_note": ""}

    monkeypatch.setattr(gd, "adjudicate_verify", fake)
    run_ = decision
    run_()
    keys = {e["key"].split(aj.SEP)[1] for e in journal_lines(run_)}
    assert keys == {"Usop", "Sanji", "Robin"}


# ---- kill and restart ------------------------------------------------------------------------------------------------------

KILL_RUNNER = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
import glossary_verify as gv
cache, gloss, die_after = sys.argv[2], sys.argv[3], int(sys.argv[4])
TITLES = __TITLES__
ANSWERS = __ANSWERS__
gv.CACHE_DIR = cache
gv.VERIFY_BACKEND = "llamacpp"; gv.BACKEND_PROBLEM = ""
gv.backend_problem = lambda backend=None: ""
gv.resolve_wiki = lambda *a, **k: "https://example.fandom.com/api.php"
gv.fetch_titles = lambda *a, **k: TITLES
gv.VERIFY_WORKERS = 1
n = {"calls": 0}
def llm(prompt, **kw):
    if n["calls"] >= die_after >= 0:
        os._exit(9)  # a hard stop: no cleanup, no flush, no cooperative anything
    n["calls"] += 1
    term = prompt.split('Term as transcribed/mined: "')[1].split('"')[0]
    return json.dumps({"canonical": ANSWERS[term], "confidence": "high", "dub_note": ""})
gv.llm_chat = llm
rep = gv.verify(gloss, force=False)
print(json.dumps({"report": rep, "calls": n["calls"]}))
""".replace("__TITLES__", repr(TITLES)).replace("__ANSWERS__", repr(ANSWERS))


def runner(tmp_path, gloss, die_after):
    script = tmp_path / "runner.py"
    script.write_text(KILL_RUNNER)
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    env.pop("VERIFY_NO_JOURNAL", None)
    return subprocess.run(
        [sys.executable, str(script), str(ROOT), str(tmp_path / "cache"), str(gloss), str(die_after)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def fresh_glossary(d):
    d.mkdir(parents=True, exist_ok=True)
    g = d / "S.json"
    g.write_text(json.dumps({"show": "S", "names": list(TERMS), "phrases": [], "wiki": "https://example.fandom.com/api.php"}))
    return g


def test_killed_mid_run_then_restarted_equals_an_uninterrupted_run(tmp_path):
    clean_gloss = fresh_glossary(tmp_path / "clean")
    clean = runner(tmp_path / "clean", clean_gloss, -1)
    assert clean.returncode == 0, clean.stderr
    clean_out = json.loads(clean.stdout.strip().splitlines()[-1])

    gloss = fresh_glossary(tmp_path / "resumed")
    killed = runner(tmp_path / "resumed", gloss, 3)
    assert killed.returncode == 9
    journal = list((tmp_path / "resumed" / "cache").glob("*.verify.journal.jsonl"))
    assert journal and len(journal[0].read_text().splitlines()) == 3, "three completed calls survived the kill"
    resumed = runner(tmp_path / "resumed", gloss, -1)
    assert resumed.returncode == 0, resumed.stderr
    out = json.loads(resumed.stdout.strip().splitlines()[-1])
    assert out["calls"] == len(TERMS) - 3, "only the unfinished terms were asked again"
    assert out["report"] == clean_out["report"]
    assert gloss.read_bytes() == clean_gloss.read_bytes()


# ---- follow-up: --force bypasses the journal's reads --------------------------------------------------------------------


def test_force_asks_the_model_again_and_the_fresh_answers_replace_the_journalled_ones(run):
    run()
    base = len(run.state["calls"])
    old = {e["key"]: e["result"]["canonical"] for e in journal_lines(run)}
    run.state["llm"] = lambda prompt: json.dumps({"canonical": "Zorro", "confidence": "high", "dub_note": ""})
    run(force=True)
    assert len(run.state["calls"]) == base + len(TERMS), "no journal read under --force"
    new = {e["key"]: e["result"]["canonical"] for e in journal_lines(run)}
    assert set(new) == set(old) and set(new.values()) == {"Zorro"} != set(old.values())
    assert len(journal_lines(run)) == len(TERMS), "compaction kept the latest line per key"


def test_force_still_writes_so_a_later_plain_run_reuses_the_forced_answers(run):
    run(force=True)
    n = len(run.state["calls"])
    run()
    assert len(run.state["calls"]) == n


def test_the_cli_help_says_force_bypasses_the_journal(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["glossary_verify", "--help"])
    with pytest.raises(SystemExit):
        gv.main()
    assert "journal" in capsys.readouterr().out


# ---- follow-up: an undecodable reply is unavailable ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        "{canonical: Zoro}",  # braces, not JSON
        "I think {it is Zoro} but not sure",
        '{"canonical": "Zo',  # truncated
        "{not json at all}",
    ],
)
def test_an_undecodable_reply_is_unavailable_never_journaled_and_retried(run, reply):
    run.state["llm"] = lambda prompt: reply
    run()
    assert journal_lines(run) == [], reply
    run.state["llm"] = globals()["reply"]
    run()
    assert len(journal_lines(run)) == len(TERMS)


def test_an_undecodable_reply_gives_the_same_glossary_as_before_the_journal(run, monkeypatch):
    """For the run itself it is still a plain no-match: only the journaling and the 'unavailable' flag differ."""
    monkeypatch.setenv("VERIFY_QUEUE_NO_MATCH", "1")
    run.state["llm"] = lambda prompt: "{canonical: Zoro}"
    run(force=False)
    flagged = json.loads(run.path.read_text()).get("flagged", {})
    assert set(flagged) == set(TERMS) and set(flagged.values()) == {"no-match"}
    adj = gv._adjudicate_llm("Zoro", ["Zorro"], "S", "llamacpp")
    assert adj["unavailable"] is True and adj["confidence"] == "none" and adj["canonical"] == ""
    assert gv.clean_adjudication(adj) == ({"canonical": "", "confidence": "none"}, False)
