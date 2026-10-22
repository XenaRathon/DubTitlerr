"""The decision backend of the glossary stages (glossary_decision + glossary_verify / glossary_acquire wiring).

Synthetic only: a fake 127.0.0.1 decisions endpoint stands in for the provider."""

import json

import pytest
from fake_servers import FakeServer

import acquire_cache
import glossary_acquire as ga
import glossary_decision as gd
import glossary_verify as gv

KEY = "sk-or-SECRET-key-0123456789"  # gitleaks:allow -- test fixture, not a real credential
MODEL = "inception/mercury-decide:free"
TITLES = ["Roronoa Zoro", "Zorro"]


def choice_answer(choice, confidence=None, probabilities=None):
    a = {"type": "choice", "choice": choice}
    if confidence is not None:
        a["confidence"] = confidence
    if probabilities is not None:
        a["probabilities"] = probabilities
    return a


def reply_with(answer_for, served=MODEL):
    """Fake endpoint reply: answers every question with ``answer_for(question_id, request_body)``."""

    def reply(req):
        body = req["body"]
        return 200, {
            "model": served,
            "answers": {q: answer_for(q, body) for q in body["questions"]},
            "usage": {"input_tokens": 5},
        }

    return reply


@pytest.fixture
def decision(monkeypatch):
    """A decision backend pointed at a fake server; ``make(answer_for)`` (re)starts it. Counters start at zero."""
    servers = []

    def make(answer_for, status=200, served=MODEL):
        srv = FakeServer(
            reply_with(answer_for, served) if status == 200 else (lambda req: (status, {"error": f"echo {req['auth']}"}))
        )
        servers.append(srv)
        monkeypatch.setenv("VERIFY_DECISION_URL", srv.base + "/api/alpha/decisions")
        return srv

    monkeypatch.setenv("TEST_DECISION_KEY", KEY)
    monkeypatch.setenv("VERIFY_DECISION_KEY_ENV", "TEST_DECISION_KEY")
    for name in ("VERIFY_DECISION_MODEL", "VERIFY_DECISION_TAU", "ACQUIRE_DECISION_TAU", "VERIFY_DECISION_FALLBACK"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "decision")
    monkeypatch.setenv("ACQUIRE_BACKEND", "decision")  # acquire is local by default under decision verify; these tests opt in
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    monkeypatch.setattr(gv, "llm_chat", lambda *a, **k: pytest.fail("the local model must not be used"))
    monkeypatch.setattr(ga, "llm_chat", lambda *a, **k: pytest.fail("the local model must not be used"))
    gd.reset()
    yield make
    for s in servers:
        s.close()


# ---- framing v1 is pinned ---------------------------------------------------------------------------------------------------


def test_the_verify_question_is_the_v1_framing_word_for_word():
    state, questions, options = gd.verify_question("One Piece", "Zoro", TITLES)
    assert state == {"show": "One Piece", "term": "Zoro"}
    assert options == {"c1": "Roronoa Zoro", "c2": "Zorro"}
    assert questions == {
        "pick": {
            "type": "choice",
            "instructions": (
                'A term was mined from the English dub of "One Piece". Pick the candidate wiki page that is the '
                'SAME named entity as the term "Zoro". Choose "none" if no candidate is the same entity.'
            ),
            "criteria": {"c1": "Roronoa Zoro", "c2": "Zorro", "none": "no candidate is the same named entity"},
        }
    }


def test_the_acquire_question_is_the_v1_framing_word_for_word():
    state, questions = gd.acquire_question("One Piece", "Zorro", "Zoro", ["q1"], ["q2"])
    assert state == {"show": "One Piece", "spelling_a": "Zorro", "spelling_b": "Zoro", "quotes_a": ["q1"], "quotes_b": ["q2"]}
    assert questions == {
        "same": {
            "type": "noul",
            "instructions": (
                'Two spellings appear in the English dub of "One Piece": "Zorro" and "Zoro". Are they the SAME name '
                "mis-transcribed (true), or two different legitimate forms such as a nickname, a title or a separate "
                "character (false)?"
            ),
            "criteria": {"true": "the same name, mis-transcribed", "false": "two different forms"},
        }
    }


def test_the_harness_and_production_build_the_same_requests(decision, monkeypatch):
    """ONE implementation: the bake-off's decision arm sends exactly what production sends."""
    import tools.glossary_bakeoff as gb

    assert gb.NONE_OPTION is gd.NONE_OPTION
    srv = decision(lambda q, b: choice_answer("c1", 0.9))
    gv.adjudicate("Zoro", TITLES, "One Piece")
    arm = gb.resolve_arm("mercury-decide")
    item = {"stage": "verify", "term": "Zoro", "show": "One Piece", "candidates": [{"title": t} for t in TITLES]}
    monkeypatch.setenv("GLOSSARY_BAKEOFF_MERCURY_DECIDE_URL", srv.base + "/api/alpha/decisions")
    monkeypatch.setenv(arm.key_env, KEY)
    gb._verify_decision(arm, item, TITLES)
    prod, harness = srv.requests[0]["body"], srv.requests[1]["body"]
    assert prod["state"] == harness["state"] and prod["questions"] == harness["questions"] and prod["model"] == harness["model"]


# ---- the verify mapping --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer,canonical,confidence",
    [
        (choice_answer("c1", 0.9), "Roronoa Zoro", "high"),
        (choice_answer("c1", 0.5), "Roronoa Zoro", "high"),  # >= tau
        (choice_answer("c1", 0.4999), "Roronoa Zoro", "low"),
        (choice_answer("c2", 0.2), "Zorro", "low"),
        (choice_answer("none", 0.99), "", "none"),  # a none pick is never high, whatever its confidence
        (choice_answer("c1", None, {"c1": 0.8, "c2": 0.1, "none": 0.1}), "Roronoa Zoro", "high"),  # the pick's own probability
        (choice_answer("c1", None, {"c1": 0.4, "c2": 0.3, "none": 0.3}), "Roronoa Zoro", "low"),
        (choice_answer("c1"), "Roronoa Zoro", "low"),  # no number at all: never high
    ],
)
def test_a_decision_pick_maps_to_the_adjudication_shape(decision, answer, canonical, confidence):
    decision(lambda q, b: answer)
    out = gv.adjudicate("Zoro", TITLES, "One Piece")
    assert out == {"canonical": canonical, "confidence": confidence, "dub_note": ""}
    assert gd.counters()["ok"] == 1


def test_tau_is_configurable(decision, monkeypatch):
    decision(lambda q, b: choice_answer("c1", 0.9))
    monkeypatch.setenv("VERIFY_DECISION_TAU", "0.95")
    assert gv.adjudicate("Zoro", TITLES, "S")["confidence"] == "low"
    monkeypatch.setenv("VERIFY_DECISION_TAU", "0.9")
    assert gv.adjudicate("Zoro", TITLES, "S")["confidence"] == "high"


def test_no_candidates_means_no_call(decision):
    srv = decision(lambda q, b: choice_answer("c1", 0.9))
    assert gv.adjudicate("Zoro", [], "S") == {"canonical": "", "confidence": "none", "dub_note": ""}
    assert srv.requests == [] and gd.counters()["calls"] == 0


# ---- the acquire mapping -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "noul,same,confidence",
    [
        (0.95, True, "high"),
        (0.8, True, "high"),  # max(p, 1-p) >= 0.8
        (0.79, True, "low"),
        (0.5, True, "low"),  # p >= 0.5 is "same", at the lowest confidence
        (0.4999, False, "low"),
        (0.2, False, "high"),
        (0.21, False, "low"),
        (0.0, False, "high"),
    ],
)
def test_a_noul_answer_maps_to_the_merge_shape(decision, noul, same, confidence):
    decision(lambda q, b: {"type": "noul", "noul": noul})
    out = ga.adjudicate_merge("Zorro", "Zoro", ["l1"], ["l2"], "S")
    assert out == {"same_entity": same, "confidence": confidence}


def test_acquire_tau_is_configurable(decision, monkeypatch):
    decision(lambda q, b: {"type": "noul", "noul": 0.9})
    monkeypatch.setenv("ACQUIRE_DECISION_TAU", "0.95")
    assert ga.adjudicate_merge("a", "b", [], [], "S")["confidence"] == "low"


# ---- end to end through apply_results / escalate -------------------------------------------------


def test_a_high_expansion_pick_is_written_exactly_like_a_text_arms(decision):
    decision(lambda q, b: choice_answer("c1", 0.9))
    adj = gv.adjudicate("Zoro", TITLES, "One Piece")
    g = {"show": "One Piece", "names": ["Zoro"], "phrases": [], "hard_fixes": {}}
    text_adj = {"canonical": "Roronoa Zoro", "confidence": "high", "dub_note": ""}
    assert gv.apply_results(g, {"Zoro": adj}) == gv.apply_results(g, {"Zoro": text_adj})
    assert (
        "Roronoa Zoro" in gv.apply_results(g, {"Zoro": adj})["phrases"] and "Zoro" in gv.apply_results(g, {"Zoro": adj})["names"]
    )


def test_a_high_respelling_pick_is_flagged_not_written(decision):
    decision(lambda q, b: choice_answer("c2", 0.9))
    adj = gv.adjudicate("Zoro", TITLES, "One Piece")
    new = gv.apply_results({"show": "S", "names": ["Zoro"], "phrases": [], "hard_fixes": {}}, {"Zoro": adj})
    assert new["names"] == ["Zoro"] and new["flagged"]["Zoro"] == {"reason": "respelling-needs-review", "canonical": "Zorro"}


def test_low_and_none_picks_are_flagged(decision, monkeypatch):
    monkeypatch.setenv("VERIFY_QUEUE_NO_MATCH", "1")  # the queue is off by default since phase 27
    new = None
    for ans, reason in ((choice_answer("c1", 0.2), "low-confidence"), (choice_answer("none", 0.9), "no-match")):
        decision(lambda q, b, a=ans: a)
        adj = gv.adjudicate("Zoro", TITLES, "S")
        new = gv.apply_results({"show": "S", "names": ["Zoro"], "phrases": [], "hard_fixes": {}}, {"Zoro": adj})
        flag = new["flagged"]["Zoro"]
        assert (flag["reason"] if isinstance(flag, dict) else flag) == reason


PROP = {
    "variant": "Deccan", "canonical": "Decken", "variant_count": 21, "canonical_count": 8, "score": 0.844,
    "verdict": "flag", "reason": "share-too-close", "bound": 0.147,
}  # fmt: skip


@pytest.mark.parametrize(
    "noul,verdict,reason",
    [(0.95, "apply", "context-merged"), (0.02, "known", "context-distinct"), (0.6, "flag", "share-too-close")],
)
def test_escalate_over_the_decision_backend(decision, noul, verdict, reason):
    decision(lambda q, b: {"type": "noul", "noul": noul})
    out = ga.escalate([dict(PROP)], {"Deccan": ["l1"], "Decken": ["l2"]}, "S", cache={})
    assert (out[0]["verdict"], out[0]["reason"]) == (verdict, reason)


def test_the_request_carries_the_quotes_and_the_key_only_in_the_header(decision):
    srv = decision(lambda q, b: {"type": "noul", "noul": 0.9})
    ga.adjudicate_merge("Deccan", "Decken", ["he said Deccan"], ["he said Decken"], "S")
    req = srv.requests[0]
    assert req["body"]["state"]["quotes_a"] == ["he said Deccan"] and req["auth"] == f"Bearer {KEY}"
    assert KEY not in json.dumps(req["body"])


# ---- failures: fallback none / local, and the counters ------------------------------------------------------------------------


def test_fallback_none_leaves_a_term_pending_not_verified_not_flagged(decision, tmp_path, monkeypatch, capsys):
    decision(lambda q, b: None, status=500)
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: TITLES)
    path = tmp_path / "g.json"
    before = {"show": "S", "names": ["Zoro"], "phrases": [], "hard_fixes": {}, "initial_prompt": "P"}
    path.write_text(json.dumps(before))
    rep = gv.verify(str(path))
    assert json.loads(path.read_text()) == before  # nothing verified, nothing flagged, nothing written
    assert rep["pending"] == 1 and rep["checked"] == 0 and rep.get("note") != "stopped"
    assert rep["decision"] == {"calls": 1, "ok": 0, "failures": 1, "fallbacks": 0, "pending": 1}
    shown = capsys.readouterr().out
    assert "decision backend:" in shown and "failures=1" in shown and "pending=1" in shown
    assert KEY not in shown and "echo" not in shown


def test_fallback_none_for_a_pair_is_unavailable_and_never_cached(decision):
    decision(lambda q, b: None, status=500)
    out = ga.adjudicate_merge("Deccan", "Decken", ["l1"], ["l2"], "S")
    assert out == {"same_entity": False, "confidence": "none", "unavailable": True}
    cache = {}
    ga.escalate([dict(PROP)], {}, "S", cache=cache)
    assert acquire_cache.escalation_for(cache, "Deccan", "Decken") in (None, {}, False)


def test_fallback_local_uses_the_local_model_and_says_so(decision, monkeypatch, capsys):
    decision(lambda q, b: None, status=500)
    monkeypatch.setenv("VERIFY_DECISION_FALLBACK", "local")
    seen = []
    monkeypatch.setattr(
        gv,
        "llm_chat",
        lambda prompt, **kw: seen.append(kw) or '{"canonical": "Roronoa Zoro", "confidence": "high", "dub_note": ""}',
    )
    out = gv.adjudicate("Zoro", TITLES, "S")
    # The fallback's answer is marked so the journal never remembers it as the decision model's.
    assert out == {"canonical": "Roronoa Zoro", "confidence": "high", "dub_note": "", "fallback": True}
    assert seen[0]["backend"] in gv.LEGACY_BACKENDS and "openai_url" not in seen[0]
    assert gd.counters() == {"calls": 1, "ok": 0, "failures": 1, "fallbacks": 1, "pending": 0}
    assert "falling back to the local model" in capsys.readouterr().out


def test_fallback_local_for_a_pair(decision, monkeypatch):
    decision(lambda q, b: None, status=500)
    monkeypatch.setenv("VERIFY_DECISION_FALLBACK", "local")
    monkeypatch.setattr(ga, "llm_chat", lambda prompt, **kw: '{"same_entity": true, "confidence": "high"}')
    # marked as a fallback so the journal never remembers it as the decision model's answer
    assert ga.adjudicate_merge("a", "b", [], [], "S") == {"same_entity": True, "confidence": "high", "fallback": True}
    assert gd.counters()["fallbacks"] == 1


def test_a_response_that_fails_validation_is_a_failure_not_a_pick(decision):
    decision(lambda q, b: choice_answer("c9", 0.9))  # an option that was never offered
    assert gv.adjudicate("Zoro", TITLES, "S") is None
    assert gd.counters()["failures"] == 1


def test_a_different_served_model_is_a_failure(decision):
    decision(lambda q, b: choice_answer("c1", 0.9), served="some/other-model")
    assert gv.adjudicate("Zoro", TITLES, "S") is None


def test_counters_are_per_run_and_the_summary_is_one_line(decision, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VERIFY_NO_JOURNAL", "1")  # this test counts provider calls per run; a journal would answer the rerun
    decision(lambda q, b: choice_answer("c1", 0.9))
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: TITLES)
    path = tmp_path / "g.json"
    path.write_text(json.dumps({"show": "S", "names": ["Zoro", "Zoroo"], "phrases": [], "hard_fixes": {}, "initial_prompt": "P"}))
    rep = gv.verify(str(path))
    assert rep["decision"] == {"calls": 2, "ok": 2, "failures": 0, "fallbacks": 0, "pending": 0}
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("decision backend:")]
    assert len(lines) == 1 and MODEL in lines[0] and "calls=2" in lines[0]
    path.write_text(json.dumps({"show": "S", "names": ["Zoro"], "phrases": [], "hard_fixes": {}, "initial_prompt": "P"}))
    assert gv.verify(str(path))["decision"]["calls"] == 1  # reset at the start of each run


def test_acquire_reports_the_counters_too(decision, tmp_path, monkeypatch):
    decision(lambda q, b: {"type": "noul", "noul": 0.9})
    path = tmp_path / "S.json"
    path.write_text('{"show": "S", "names": [], "phrases": []}')
    monkeypatch.setattr(ga, "harvest_candidates", lambda d: ({}, set(), []))
    rep = ga.acquire(str(path), str(tmp_path))
    assert rep["note"] == "nothing harvested" and rep["decision"] == {
        "calls": 0,
        "ok": 0,
        "failures": 0,
        "fallbacks": 0,
        "pending": 0,
    }


def test_a_legacy_backend_prints_and_reports_nothing_extra(tmp_path, monkeypatch, capsys):
    """GUARD: with a legacy backend the report has no decision key and no summary line is printed."""
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: TITLES)
    monkeypatch.setattr(gv, "llm_chat", lambda *a, **k: '{"canonical": "Roronoa Zoro", "confidence": "high", "dub_note": ""}')
    path = tmp_path / "g.json"
    path.write_text(json.dumps({"show": "S", "names": ["Zoro"], "phrases": [], "hard_fixes": {}, "initial_prompt": "P"}))
    monkeypatch.setenv("VERIFY_QUEUE_NO_MATCH", "1")  # the default (0) adds a no_match count; the common-word guard a block
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "0")
    rep = gv.verify(str(path))
    assert set(rep) == {"show", "wiki", "checked", "applied", "escalated", "flagged"}
    out = capsys.readouterr().out
    assert "decision backend" not in out and "sends" not in out


# ---- privacy, spend visibility, key hygiene -----------------------------------------------------------------------------------


def test_the_start_of_a_run_says_which_fields_go_to_which_host(decision, tmp_path, monkeypatch, capsys):
    decision(lambda q, b: choice_answer("c1", 0.9))
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: TITLES)
    path = tmp_path / "g.json"
    path.write_text(json.dumps({"show": "S", "names": ["Zoro"], "phrases": [], "hard_fixes": {}, "initial_prompt": "P"}))
    gv.verify(str(path))
    first = capsys.readouterr().out.splitlines()[0]
    assert "127.0.0.1" in first and "term" in first and "candidate" in first and MODEL in first
    assert KEY not in first and "/api/alpha" not in first and "?" not in first  # the host only, never a path or query


def test_the_acquire_banner_names_the_transcript_lines(decision, capsys):
    gd.announce("acquire")
    assert "transcript" in capsys.readouterr().out


def test_the_openai_text_backend_gets_a_banner_naming_its_host(monkeypatch, capsys):
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "openai")
    monkeypatch.setenv("VERIFY_OPENAI_URL", "https://api.example.com/v1/chat/completions?token=sekrit")
    gv.announce("verify")
    shown = capsys.readouterr().out
    assert "api.example.com" in shown and "sekrit" not in shown and "/v1" not in shown


def test_the_key_appears_in_no_log_row_or_report(decision, tmp_path, monkeypatch, capsys):
    decision(lambda q, b: None, status=500)
    monkeypatch.setenv("VERIFY_DECISION_FALLBACK", "none")
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: TITLES)
    path = tmp_path / "g.json"
    path.write_text(json.dumps({"show": "S", "names": ["Zoro"], "phrases": [], "hard_fixes": {}, "initial_prompt": "P"}))
    rep = gv.verify(str(path))
    ga.adjudicate_merge("a", "b", [], [], "S")
    assert KEY not in capsys.readouterr().out and KEY not in json.dumps(rep) and KEY not in path.read_text()


# ---- configuration -----------------------------------------------------------------------------------------------------------


def test_defaults_follow_the_models_provider(monkeypatch):
    for name in ("VERIFY_DECISION_MODEL", "VERIFY_DECISION_URL", "VERIFY_DECISION_KEY_ENV", "VERIFY_DECISION_TAU"):
        monkeypatch.delenv(name, raising=False)
    s = gd.settings()
    assert (s.model, s.provider, s.key_env, s.tau, s.acquire_tau, s.fallback) == (
        MODEL,
        "openrouter",
        "OPENROUTER_JEV_API_KEY",
        0.5,
        0.8,
        "none",
    )
    monkeypatch.setenv("VERIFY_DECISION_MODEL", "typesafe/jev")
    s = gd.settings()
    assert (s.provider, s.key_env) == ("commandcode", "COMMANDCODE_API_KEY")


@pytest.mark.parametrize(
    "env,mention",
    [
        ({"VERIFY_DECISION_MODEL": "made/up-model"}, "allowlist"),
        ({"VERIFY_DECISION_MODEL": "respan/span-01-lite"}, "Span"),
        ({"VERIFY_DECISION_TAU": "high"}, "VERIFY_DECISION_TAU"),
        ({"VERIFY_DECISION_TAU": "1.5"}, "VERIFY_DECISION_TAU"),
        ({"VERIFY_DECISION_TAU": "nan"}, "VERIFY_DECISION_TAU"),
        ({"ACQUIRE_DECISION_TAU": "0.3"}, "ACQUIRE_DECISION_TAU"),
        ({"VERIFY_DECISION_FALLBACK": "maybe"}, "VERIFY_DECISION_FALLBACK"),
        ({"VERIFY_DECISION_URL": "https://evil.example.com/x"}, "host"),
        ({"VERIFY_DECISION_URL": "http://openrouter.ai/api/alpha/decisions"}, "https"),
        ({"VERIFY_DECISION_KEY_ENV": "NO_SUCH_KEY_VAR"}, "NO_SUCH_KEY_VAR"),
    ],
)
def test_the_decision_preflight_names_what_is_wrong(decision, monkeypatch, env, mention):
    decision(lambda q, b: choice_answer("c1", 0.9))
    assert gv.backend_problem() == ""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    problem = gv.backend_problem()
    assert mention in problem and KEY not in problem


def test_the_preflight_makes_no_request(decision):
    srv = decision(lambda q, b: choice_answer("c1", 0.9))
    assert gv.backend_problem() == "" and srv.requests == []


def test_verify_refuses_a_misconfigured_decision_backend_before_any_work(decision, tmp_path, monkeypatch):
    decision(lambda q, b: choice_answer("c1", 0.9))
    monkeypatch.setenv("VERIFY_DECISION_MODEL", "made/up-model")
    monkeypatch.setattr(gv, "resolve_wiki", lambda *a, **k: pytest.fail("the wiki must not be touched"))
    path = tmp_path / "g.json"
    path.write_text(json.dumps({"show": "S", "names": ["Zoro"], "phrases": []}))
    assert gv.verify(str(path))["note"].startswith("refused:")


def test_a_local_fallback_needs_a_legacy_local_backend(decision, monkeypatch):
    decision(lambda q, b: choice_answer("c1", 0.9))
    monkeypatch.setenv("VERIFY_DECISION_FALLBACK", "local")
    monkeypatch.setenv("VERIFY_DECISION_LOCAL_BACKEND", "openai")
    assert "VERIFY_DECISION_LOCAL_BACKEND" in gv.backend_problem()
    monkeypatch.setenv("VERIFY_DECISION_LOCAL_BACKEND", "llamacpp")
    assert gv.backend_problem() == ""


# ---- the soft stop -------------------------------------------------------------------------------


def test_the_soft_stop_is_honoured_between_terms_on_the_decision_backend(decision, tmp_path, monkeypatch):
    srv = decision(lambda q, b: choice_answer("c1", 0.9))
    monkeypatch.setattr(gv, "stop_requested", lambda: True)
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: TITLES)
    path = tmp_path / "g.json"
    path.write_text(json.dumps({"show": "S", "names": ["Zoro"], "phrases": []}))
    rep = gv.verify(str(path))
    assert rep["note"] == "stopped" and srv.requests == []


def test_escalate_still_stops_before_a_fresh_decision_call(decision, monkeypatch):
    srv = decision(lambda q, b: {"type": "noul", "noul": 0.9})
    monkeypatch.setattr(ga, "stop_requested", lambda: True)
    with pytest.raises(ga.StopRequested):
        ga.escalate([dict(PROP)], {}, "S", cache={})
    assert srv.requests == []


def test_acquire_tier_b_treats_a_pending_term_as_no_entry_not_an_error(tmp_path, monkeypatch, capsys):
    from test_glossary_acquire import _write_conf

    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"show": "One Pace"}))
    _write_conf(tmp_path, "Ep01", ["I saw Kasumi walk.", "I saw Kasumi again.", "I saw Kasumi thrice."] * 3)
    monkeypatch.setattr(gv, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda *a, **k: ["Shirahoshi", "Misty"])
    monkeypatch.setattr(gv, "adjudicate", lambda *a, **k: None)  # decision call failed, VERIFY_DECISION_FALLBACK=none
    monkeypatch.setattr(gv, "backend_problem", lambda: "")
    rep = ga.acquire(str(gp), str(tmp_path), apply=False)
    assert rep["tier_b"] == {} and "adjudicate failed" not in capsys.readouterr().out


# ---- phase 7: the run-level breaker, workers and retries -----------------------------------------------------------


def _names_glossary(tmp_path, n):
    path = tmp_path / "g.json"
    path.write_text(
        json.dumps(
            {
                "show": "S",
                "wiki": "https://x.fandom.com/api.php",
                "names": [f"Zoro{k}" for k in range(n)],
                "phrases": [],
                "hard_fixes": {},
            }
        )
    )
    return path


@pytest.fixture
def wiki(monkeypatch):
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: TITLES)
    monkeypatch.setattr(gv, "candidates", lambda term, titles, k=gv.TOPK: list(TITLES))


def test_the_breaker_stops_calling_the_provider_after_five_failed_terms(decision, wiki, tmp_path, capsys):
    srv = decision(None, status=500)
    rep = gv.verify(str(_names_glossary(tmp_path, 8)))
    shown = capsys.readouterr().out
    assert len(srv.requests) == 5  # one request per failed term (retries default to 0), then nothing
    assert rep["pending"] == 8 and rep["checked"] == 0
    assert rep["decision"] == {"calls": 5, "ok": 0, "failures": 5, "fallbacks": 0, "pending": 8, "breaker_tripped_after": 5}
    assert shown.count("breaker tripped") == 2  # the one-time log line, and the summary line
    assert shown.count("decision breaker tripped after 5 consecutive failures") == 1
    assert "breaker tripped after 5 failures" in [ln for ln in shown.splitlines() if ln.startswith("decision backend:")][0]
    assert KEY not in shown


def test_a_success_resets_the_streak(decision, wiki, tmp_path):
    answers = iter([False] * 4 + [True] + [False] * 4 + [True])
    srv = FakeServer(
        lambda req: (
            (500, {"error": "x"})
            if not next(answers)
            else (200, {"model": MODEL, "answers": {"pick": choice_answer("c1", 0.9)}, "usage": {}})
        )
    )
    import os

    os.environ["VERIFY_DECISION_URL"] = srv.base + "/api/alpha/decisions"
    try:
        rep = gv.verify(str(_names_glossary(tmp_path, 10)))
    finally:
        srv.close()
    assert "breaker_tripped_after" not in rep["decision"] and rep["decision"]["calls"] == 10
    assert rep["decision"]["ok"] == 2 and rep["decision"]["failures"] == 8


def test_the_breaker_is_configurable_and_zero_turns_it_off(decision, wiki, tmp_path, monkeypatch):
    srv = decision(None, status=500)
    monkeypatch.setenv("VERIFY_DECISION_BREAKER", "0")
    rep = gv.verify(str(_names_glossary(tmp_path, 8)))
    assert len(srv.requests) == 8 and "breaker_tripped_after" not in rep["decision"]
    monkeypatch.setenv("VERIFY_DECISION_BREAKER", "2")
    srv.requests.clear()
    gv.verify(str(_names_glossary(tmp_path, 8)))
    assert len(srv.requests) == 2


def test_after_the_breaker_trips_a_local_fallback_answers_locally_without_calling_the_provider(
    decision, wiki, tmp_path, monkeypatch
):
    srv = decision(None, status=500)
    monkeypatch.setenv("VERIFY_DECISION_FALLBACK", "local")
    local = []
    monkeypatch.setattr(
        gv,
        "llm_chat",
        lambda prompt, **kw: local.append(1) or '{"canonical": "Roronoa Zoro", "confidence": "low", "dub_note": ""}',
    )
    rep = gv.verify(str(_names_glossary(tmp_path, 8)))
    assert len(srv.requests) == 5 and len(local) == 8 and "pending" not in rep
    assert rep["decision"] == {"calls": 5, "ok": 0, "failures": 5, "fallbacks": 8, "pending": 0, "breaker_tripped_after": 5}


def test_a_tripped_breaker_leaves_pairs_unavailable_and_uncached(decision, monkeypatch):
    srv = decision(None, status=500)
    monkeypatch.setenv("VERIFY_DECISION_BREAKER", "2")
    outs = [ga.adjudicate_merge(f"a{k}", "b", [], [], "S") for k in range(5)]
    assert all(o == {"same_entity": False, "confidence": "none", "unavailable": True} for o in outs) and len(srv.requests) == 2


def test_the_breaker_is_per_run(decision, wiki, tmp_path):
    srv = decision(None, status=500)
    gv.verify(str(_names_glossary(tmp_path, 8)))
    srv.requests.clear()
    gv.verify(str(_names_glossary(tmp_path, 8)))
    assert len(srv.requests) == 5  # begin_run reset the breaker


def test_the_breaker_counters_hold_under_concurrent_failures(decision, monkeypatch):
    import concurrent.futures

    srv = decision(None, status=500)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda k: gv.adjudicate(f"Zoro{k}", TITLES, "S"), range(40)))
    c = gd.counters()
    assert 5 <= c["calls"] <= 5 + 7  # at most the calls already in flight when the breaker trips
    assert c["failures"] == c["calls"] and c["pending"] == 40 and c["breaker_tripped_after"] >= 5
    assert len(srv.requests) == c["calls"]


def test_retries_default_to_zero_for_the_stage_and_are_configurable(decision, monkeypatch):
    import decision_client

    srv = decision(None, status=500)
    monkeypatch.setattr(decision_client.time, "sleep", lambda s: None)
    monkeypatch.setenv("VERIFY_DECISION_BREAKER", "0")
    gv.adjudicate("Zoro", TITLES, "S")
    assert len(srv.requests) == 1
    monkeypatch.setenv("VERIFY_DECISION_RETRIES", "2")
    gv.adjudicate("Zoro", TITLES, "S")
    assert len(srv.requests) == 1 + 3


def test_the_harness_keeps_the_decision_clients_own_retries():
    """GUARD: the bake-off calls decide() without `retries`, so it keeps the client's default of 2."""
    import inspect

    import decision_client

    assert inspect.signature(decision_client.decide).parameters["retries"].default == decision_client.MAX_RETRIES == 2


def _tracked_adjudicate(monkeypatch):
    import threading
    import time

    state = {"now": 0, "max": 0}
    lock = threading.Lock()

    def fake(term, cands, show):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return {"canonical": term, "confidence": "low", "dub_note": ""}

    monkeypatch.setattr(gv, "adjudicate", fake)
    return state


def test_the_decision_backend_runs_one_worker_by_default(decision, wiki, tmp_path, monkeypatch):
    state = _tracked_adjudicate(monkeypatch)
    gv.verify(str(_names_glossary(tmp_path, 6)))
    assert state["max"] == 1  # VERIFY_WORKERS (4) is for the local server, not for a metered provider


def test_verify_decision_workers_sets_the_concurrency(decision, wiki, tmp_path, monkeypatch):
    state = _tracked_adjudicate(monkeypatch)
    monkeypatch.setenv("VERIFY_DECISION_WORKERS", "3")
    gv.verify(str(_names_glossary(tmp_path, 9)))
    assert state["max"] == 3


def test_a_legacy_backend_keeps_verify_workers(decision, wiki, tmp_path, monkeypatch):
    """GUARD: the local backends keep VERIFY_WORKERS (4) exactly as before."""
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    state = _tracked_adjudicate(monkeypatch)
    gv.verify(str(_names_glossary(tmp_path, 8)))
    assert state["max"] == gv.VERIFY_WORKERS == 4


@pytest.mark.parametrize(
    "env",
    [
        {"VERIFY_DECISION_BREAKER": "-1"},
        {"VERIFY_DECISION_BREAKER": "many"},
        {"VERIFY_DECISION_WORKERS": "0"},
        {"VERIFY_DECISION_WORKERS": "x"},
        {"VERIFY_DECISION_RETRIES": "-1"},
        {"VERIFY_DECISION_RETRIES": "9"},
    ],
)
def test_the_new_decision_settings_are_validated(decision, monkeypatch, env):
    decision(lambda q, b: choice_answer("c1", 0.9))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert next(iter(env)) in gv.backend_problem()


def test_the_new_decision_defaults(monkeypatch):
    for name in ("VERIFY_DECISION_BREAKER", "VERIFY_DECISION_WORKERS", "VERIFY_DECISION_RETRIES"):
        monkeypatch.delenv(name, raising=False)
    s = gd.settings()
    assert (s.breaker, s.workers, s.retries) == (5, 1, 0)
