"""ACQUIRE_BACKEND: acquire's LLM calls (tier B's per-term pick, tier C's pair merge) choose their backend apart from verify.

Unset, acquire follows VERIFY_BACKEND, except that VERIFY_BACKEND=decision means the LOCAL backend for acquire (the decision model
scored 47% against the local model's 72% on the blind acquire pairs). ACQUIRE_BACKEND=decision opts acquire in;
llamacpp|ollama|openai force that backend. Hosted choices keep verify's refusal rules and egress notice."""

import json

import pytest

import glossary_acquire as ga
import glossary_decision as gd
import glossary_verify as gv

HOSTED_ENV = {
    "TEST_DECISION_KEY": "sk-test-0123456789",  # gitleaks:allow -- test fixture, not a real credential
    "VERIFY_DECISION_KEY_ENV": "TEST_DECISION_KEY",
    "VERIFY_OPENAI_URL": "https://api.example.test/v1/chat/completions",
    "VERIFY_OPENAI_KEY_ENV": "TEST_OPENAI_KEY",
    "TEST_OPENAI_KEY": "sk-test-0123456789",  # gitleaks:allow -- test fixture, not a real credential
    "VERIFY_MODEL": "some-model",
}


@pytest.fixture
def env(monkeypatch):
    for name in ("ACQUIRE_BACKEND", "VERIFY_DECISION_LOCAL_BACKEND", "VERIFY_DECISION_FALLBACK", "REPAIR_BACKEND"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")

    def configure(verify, acquire=None, hosted=True, **extra):
        monkeypatch.setattr(gv, "VERIFY_BACKEND", verify)
        monkeypatch.delenv("ACQUIRE_BACKEND", raising=False)
        if acquire is not None:
            monkeypatch.setenv("ACQUIRE_BACKEND", acquire)
        if hosted:
            for k, v in HOSTED_ENV.items():
                monkeypatch.setenv(k, v)
        for k, v in extra.items():
            monkeypatch.setenv(k, v)

    return configure


MATRIX = [
    # (VERIFY_BACKEND, ACQUIRE_BACKEND, backend acquire uses)
    ("llamacpp", None, "llamacpp"),
    ("ollama", None, "ollama"),
    ("openai", None, "openai"),
    ("decision", None, "ollama"),  # the local backend, resolved like the decision fallback
    ("decision", "decision", "decision"),
    ("decision", "llamacpp", "llamacpp"),
    ("decision", "ollama", "ollama"),
    ("decision", "openai", "openai"),
    ("llamacpp", "decision", "decision"),
    ("ollama", "openai", "openai"),
    ("openai", "ollama", "ollama"),
    ("openai", "decision", "decision"),
]


@pytest.mark.parametrize("verify,acquire,expected", MATRIX)
def test_the_backend_acquire_uses(env, verify, acquire, expected):
    env(verify, acquire)
    assert gv.acquire_backend() == expected
    assert gv.acquire_problem() == ""


def test_decision_verify_resolves_acquire_through_the_local_backend_setting(env):
    env("decision", VERIFY_DECISION_LOCAL_BACKEND="llamacpp")
    assert gv.acquire_backend() == "llamacpp"
    env("decision", REPAIR_BACKEND="llamacpp")  # the same fallback chain as VERIFY_DECISION_FALLBACK=local
    assert gv.acquire_backend() == gv.local_backend()


@pytest.mark.parametrize("verify,acquire,expected", MATRIX)
def test_the_pair_merge_and_the_term_pick_both_use_that_backend(env, monkeypatch, verify, acquire, expected):
    env(verify, acquire)
    seen = []
    same = {"same_entity": True, "confidence": "high"}
    none = {"canonical": "", "confidence": "none"}
    monkeypatch.setattr(ga, "_merge_via_llm", lambda *a: seen.append(("merge-llm", a[-1])) or same)
    monkeypatch.setattr(gd, "adjudicate_pair", lambda *a, **k: seen.append(("merge-decision", None)) or same)
    monkeypatch.setattr(gv, "_adjudicate_llm", lambda t, c, s, backend: seen.append(("pick-llm", backend)) or none)
    monkeypatch.setattr(gd, "adjudicate_verify", lambda *a, **k: seen.append(("pick-decision", None)) or none)
    ga.adjudicate_merge("Zorro", "Zoro", [], [], "S")
    gv.adjudicate("Zorro", ["Zoro"], "S", backend=gv.acquire_backend())
    if expected == "decision":
        assert seen == [("merge-decision", None), ("pick-decision", None)]
    else:
        assert seen == [("merge-llm", expected), ("pick-llm", expected)]


def test_verify_itself_is_unchanged_by_acquire_backend(env, monkeypatch):
    env("decision", "llamacpp")
    seen = []
    none = {"canonical": "", "confidence": "none"}
    monkeypatch.setattr(gd, "adjudicate_verify", lambda *a, **k: seen.append("decision") or none)
    gv.adjudicate("Zorro", ["Zoro"], "S")
    assert seen == ["decision"]


# ---- refusals and the report ---------------------------------------------------------------------------------------------------


def test_a_hosted_acquire_choice_keeps_verifys_refusal_rules(env):
    env("llamacpp", "decision", hosted=False)  # no key configured anywhere
    assert "key" in gv.acquire_problem().lower() or "VERIFY_DECISION" in gv.acquire_problem()
    env("llamacpp", "openai", hosted=False)
    assert "VERIFY_OPENAI_URL" in gv.acquire_problem()


def test_an_unknown_acquire_backend_is_refused_by_name(env):
    env("llamacpp", "bogus")
    assert "ACQUIRE_BACKEND" in gv.acquire_problem() and "bogus" in gv.acquire_problem()


def test_a_misconfigured_decision_verify_does_not_block_a_local_acquire(env):
    env("decision", hosted=False)  # verify would be refused (no key); acquire is local
    assert gv.backend_problem() != ""
    assert gv.acquire_problem() == ""


def test_a_refused_acquire_says_why_and_a_clean_one_names_its_backend(env, tmp_path):
    glossary = tmp_path / "S.json"
    glossary.write_text(json.dumps({"show": "S", "names": []}))
    env("llamacpp", "bogus")
    rep = ga.acquire(str(glossary), str(tmp_path))
    assert rep["note"].startswith("refused:") and "ACQUIRE_BACKEND" in rep["note"]
    env("decision")  # acquire runs local; nothing to harvest in the empty show dir
    rep = ga.acquire(str(glossary), str(tmp_path))
    assert rep["note"] == "nothing harvested" and rep["backend"] == "ollama"
    assert "decision" not in rep, "no decision counters: the decision model was not used"


def test_the_egress_notice_follows_the_acquire_backend(env, capsys):
    env("llamacpp", "openai")
    gv.begin_run("acquire", gv.acquire_backend())
    assert "example.test" in capsys.readouterr().out
    env("openai")  # verify hosted, acquire follows it
    gv.begin_run("acquire", gv.acquire_backend())
    assert "example.test" in capsys.readouterr().out
    env("decision")  # acquire local: nothing leaves the machine, nothing is announced
    gv.begin_run("acquire", gv.acquire_backend())
    assert capsys.readouterr().out == ""
