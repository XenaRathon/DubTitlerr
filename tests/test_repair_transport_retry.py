"""REPAIR_TRANSPORT_RETRIES: the openai repair backend retries a transport error (before any response) and nothing else.
Default 0 = the legacy single attempt. No network: _post_json is a fake."""

import http.client
import json
import socket
import urllib.error

import pytest

import repair

OK = {"choices": [{"message": {"content": "fixed line"}}]}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(repair, "OPENAI_URL", "https://api.example.test/v1/chat/completions")
    monkeypatch.setattr(repair, "OPENAI_KEY_ENV", "TEST_REPAIR_KEY")
    monkeypatch.setenv("TEST_REPAIR_KEY", "sk-test-0123456789")
    monkeypatch.setenv("REPAIR_EXTRA_BODY", "")
    monkeypatch.delenv("REPAIR_OPENAI_RETRIES", raising=False)
    monkeypatch.delenv("REPAIR_TRANSPORT_RETRIES", raising=False)
    sleeps = []
    monkeypatch.setattr(repair, "_sleep", sleeps.append)
    return sleeps


def script(monkeypatch, *outcomes):
    """Each call to _post_json pops the next outcome: an exception instance is raised, anything else is returned."""
    calls = []

    def fake(url, body, timeout=180, headers=None):
        calls.append(1)
        out = outcomes[min(len(calls), len(outcomes)) - 1]
        if isinstance(out, BaseException):
            raise out
        return out

    monkeypatch.setattr(repair, "_post_json", fake)
    return calls


def test_by_default_a_transport_error_is_one_attempt_and_unreachable(env, monkeypatch):
    """GUARD (passes on the old code): legacy behaviour is byte-identical with the variable unset."""
    calls = script(monkeypatch, ConnectionResetError("reset"), OK)
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE
    assert len(calls) == 1 and env == []


def test_a_transport_error_is_retried_and_a_success_counts_as_success(env, monkeypatch):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    calls = script(monkeypatch, ConnectionResetError("reset"), OK)
    before = repair.transport_retries_total()
    assert repair.llm_openai("P", None) == "fixed line"
    assert len(calls) == 2 and repair.transport_retries_total() == before + 1
    assert env == [0.5]  # a short backoff


def test_an_error_that_never_clears_gives_up_after_the_budget(env, monkeypatch, capsys):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    calls = script(monkeypatch, OSError("down"))
    before = repair.transport_retries_total()
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE
    assert len(calls) == 3 and repair.transport_retries_total() == before + 2 and env == [0.5, 1.0]
    assert "OSError" in capsys.readouterr().out


@pytest.mark.parametrize(
    "exc",
    [
        OSError("x"),
        ConnectionResetError("x"),
        ConnectionRefusedError("x"),
        urllib.error.URLError("x"),
        socket.timeout("timed out"),
        http.client.RemoteDisconnected("x"),
        http.client.IncompleteRead(b""),
    ],
)
def test_every_transport_failure_before_a_response_is_retried(env, monkeypatch, exc):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "1")
    calls = script(monkeypatch, exc, OK)
    assert repair.llm_openai("P", None) == "fixed line" and len(calls) == 2


def test_the_request_deadline_is_not_a_transport_error(env, monkeypatch):
    """A watchdog timeout can fire mid-response; it keeps its old meaning (unreachable), no retry."""
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    calls = script(monkeypatch, TimeoutError("request deadline of 300s exceeded"), OK)
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE and len(calls) == 1


@pytest.mark.parametrize("status", [400, 401, 404, 500, 503])
def test_an_http_answer_is_never_a_transport_retry(env, monkeypatch, status):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    monkeypatch.setenv("REPAIR_OPENAI_RETRIES", "0")
    calls = script(monkeypatch, repair._HttpError(status, f"HTTP {status}", None), OK)
    repair.llm_openai("P", None)
    assert len(calls) == 1 and repair.transport_retries_total() >= 0


def test_a_429_keeps_its_own_retry_path_and_adds_no_transport_retries(env, monkeypatch):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    calls = script(monkeypatch, repair._HttpError(429, "HTTP 429", None), OK)
    before = repair.transport_retries_total()
    assert repair.llm_openai("P", None) == "fixed line"
    assert len(calls) == 2 and repair.transport_retries_total() == before and env == [2.0]  # the 429 backoff, not ours


def test_a_parsed_but_unusable_answer_is_not_retried(env, monkeypatch):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    calls = script(monkeypatch, {"choices": []}, OK)  # malformed body: a KeyError/IndexError, not a transport failure
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE and len(calls) == 1
    calls = script(monkeypatch, json.JSONDecodeError("bad", "x", 0), OK)
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE and len(calls) == 1


def test_a_soft_stop_ends_the_retries(env, monkeypatch):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    monkeypatch.setattr(repair, "stop_requested", lambda: True)
    calls = script(monkeypatch, OSError("down"), OK)
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE and len(calls) == 1


def test_the_budget_is_clamped(env, monkeypatch):
    for raw, expect in (("2", 2), ("9", 5), ("-1", 0), ("lots", 0), ("", 0)):
        monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", raw)
        assert repair._transport_retries() == expect, raw


def test_only_the_openai_backend_retries(env, monkeypatch):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    calls = []
    monkeypatch.setattr(repair, "_post_json", lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(OSError("down")))
    monkeypatch.setattr(repair, "LLAMACPP_URL", "http://127.0.0.1:1/v1")
    repair.llm_llamacpp("P", "m")
    assert len(calls) == 1


def test_the_summary_reports_transport_retries_only_when_the_budget_is_set(tmp_path, monkeypatch, env):
    import test_repair

    import glossary

    def run(name):
        sub = tmp_path / name
        sub.mkdir()
        stem = str(sub / "ep")
        conf = stem + repair.CONF_SUFFIX
        segs = [
            {
                "start": float(k * 6),
                "end": float(k * 6 + 6),
                "text": f"garbled line {k}",
                "avg_logprob": -0.6,
                "no_speech_prob": 0.1,
            }
            for k in range(12)
        ]
        test_repair._write_conf(conf, stem + repair.SRT_SUFFIX, segs)
        monkeypatch.setattr(repair, "find_video", lambda s: str(sub / "ep.mkv"))
        monkeypatch.setattr(repair, "glossary_for", lambda video: glossary.load_dict({}))
        monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 80.0, "the official sub")])
        monkeypatch.setattr(repair, "REPAIR_BACKEND", "openai")
        script(monkeypatch, ConnectionResetError("reset"), OK)
        repair.process(conf)
        return json.load(open(stem + ".dubtitles.repair-summary.json"))

    off = run("off")
    assert "transport_retries" not in off and off["unreachable"] == 1  # the legacy single attempt
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    on = run("on")
    assert on["transport_retries"] == 1 and on["unreachable"] == 0 and on["repaired"] > 0
