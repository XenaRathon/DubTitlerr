"""tools/decision_client.py: OpenRouter's alpha decisions API. No network: the transport is faked."""

import json

import pytest

import repair
import tools.decision_client as dc

KEY = "sk-SENTINEL-KEY-12345"
MODEL = "inception/mercury-decide:free"
CHOICE_Q = {
    "pick": {"type": "choice", "instructions": "Which?", "criteria": {"c1": "Zoro", "c2": "Luffy", "none": "no candidate"}}
}
NOUL_Q = {"same": {"type": "noul", "instructions": "Same entity?", "criteria": {"true": "yes", "false": "no"}}}
SPAN_STATE = {"input": [{"role": "user", "content": "term"}], "output": {"role": "assistant", "content": "Zoro"}}


def _ok(choice="c1", model=MODEL):
    return {
        "model": model,
        "answers": {
            "pick": {
                "type": "choice",
                "choice": choice,
                "probabilities": {"c1": 0.9, "c2": 0.05, "none": 0.05},
                "confidence": 0.9,
            }
        },
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("TEST_DECISION_KEY", KEY)


def _post_returning(resp, seen=None):
    def post(url, body, headers=None):
        if seen is not None:
            seen.append((url, body, headers))
        return resp

    return post


def test_request_shape_headers_and_result():
    seen = []
    res = dc.decide(MODEL, {"show": "S", "term": "T"}, CHOICE_Q, "TEST_DECISION_KEY", post=_post_returning(_ok(), seen))
    url, body, headers = seen[0]
    assert url == "https://openrouter.ai/api/alpha/decisions"
    assert body == {"model": MODEL, "state": {"show": "S", "term": "T"}, "questions": CHOICE_Q}
    assert headers["Authorization"] == f"Bearer {KEY}" and headers["User-Agent"] == "DubTitlerr-glossary-bakeoff/1.0"
    assert res.answers["pick"]["choice"] == "c1" and res.usage == {"input_tokens": 10, "output_tokens": 2}
    assert res.model == MODEL and res.latency_s >= 0


def test_the_key_comes_from_the_named_env_var_only(monkeypatch):
    monkeypatch.delenv("TEST_DECISION_KEY")
    with pytest.raises(dc.DecisionError) as e:
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=lambda *a, **k: pytest.fail("no key, no request"))
    assert "TEST_DECISION_KEY" in str(e.value)
    monkeypatch.setenv("TEST_DECISION_KEY", "bad key\nwith newline")
    with pytest.raises(dc.DecisionError) as e:
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=lambda *a, **k: pytest.fail("bad key, no request"))
    assert "bad key" not in str(e.value)
    monkeypatch.setenv("TEST_DECISION_KEY", KEY + "\r")  # CRLF .env: stripped
    seen = []
    dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=_post_returning(_ok(), seen))
    assert seen[0][2]["Authorization"] == f"Bearer {KEY}"


def test_the_key_never_reaches_an_exception_a_log_or_a_traceback(capsys):
    def leaky(url, body, headers=None):
        raise ValueError(f"Invalid header value b'Bearer {KEY}'")  # what http.client does

    with pytest.raises(dc.DecisionError) as e:
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=leaky)
    assert KEY not in str(e.value) and KEY not in repr(e.value)
    assert "ValueError" in str(e.value)
    assert e.value.__cause__ is None and e.value.__context__ is None
    out = capsys.readouterr()
    assert KEY not in out.out + out.err


def test_http_errors_carry_the_status_only(capsys):
    def boom(url, body, headers=None):
        raise repair._HttpError(401, f"HTTP 401: b'bad key {KEY}'")

    with pytest.raises(dc.DecisionHTTPError) as e:
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=boom)
    assert str(e.value) == "HTTP 401" and e.value.status == 401 and KEY not in repr(e.value)


def test_an_unknown_model_is_rejected_before_any_request():
    with pytest.raises(dc.DecisionError, match="allowlist"):
        dc.decide("someone/else", {}, CHOICE_Q, "TEST_DECISION_KEY", post=lambda *a, **k: pytest.fail("no request"))
    assert "typesafe/jev-1.13" in dc.ALLOWED_MODELS and len(dc.ALLOWED_MODELS) == 7


def test_429_then_200_is_retried_and_honours_retry_after():
    calls, slept = [], []

    def post(url, body, headers=None):
        calls.append(1)
        if len(calls) == 1:
            raise repair._HttpError(429, "HTTP 429: x", "7")
        return _ok()

    res = dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=post, sleep=slept.append)
    assert res.answers and len(calls) == 2 and slept == [7.0]


def test_5xx_is_retried_at_most_twice_with_backoff():
    calls, slept = [], []

    def post(url, body, headers=None):
        calls.append(1)
        raise repair._HttpError(503, "HTTP 503: x")

    with pytest.raises(dc.DecisionHTTPError) as e:
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=post, sleep=slept.append)
    assert e.value.status == 503 and len(calls) == 3 and slept == [2.0, 4.0]


def test_the_total_sleep_budget_stops_the_retries():
    calls, slept = [], []

    def post(url, body, headers=None):
        calls.append(1)
        raise repair._HttpError(429, "x", "30")

    with pytest.raises(dc.DecisionHTTPError):
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=post, sleep=slept.append, sleep_budget=40)
    assert slept == [30.0] and len(calls) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_other_client_errors_are_not_retried(status):
    calls = []

    def post(url, body, headers=None):
        calls.append(1)
        raise repair._HttpError(status, "x")

    with pytest.raises(dc.DecisionHTTPError):
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=post, sleep=lambda s: pytest.fail("no sleep"))
    assert len(calls) == 1


def test_transport_errors_are_not_retried():
    calls = []

    def post(url, body, headers=None):
        calls.append(1)
        raise TimeoutError("deadline")

    with pytest.raises(dc.DecisionError, match="TimeoutError"):
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=post, sleep=lambda s: pytest.fail("no sleep"))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "resp",
    [
        None,
        [],
        {"answers": {}},
        {"model": MODEL},
        {"model": MODEL, "answers": {}},
        {"model": MODEL, "answers": {"pick": {"type": "noul"}}},
        {"model": MODEL, "answers": {"pick": {"type": "choice", "choice": "c9"}}},
        {"model": MODEL, "answers": {"pick": {"type": "choice", "choice": "c1", "probabilities": {"c1": "high"}}}},
        {"model": MODEL, "answers": {"pick": {"type": "choice", "choice": "c1", "confidence": "high"}}},
        {"model": 7, "answers": {}},
    ],
)
def test_a_bad_response_shape_raises_and_never_guesses(resp):
    with pytest.raises(dc.DecisionError):
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=_post_returning(resp))


def test_a_non_json_body_is_a_decision_error():
    def post(url, body, headers=None):
        raise json.JSONDecodeError("x", "y", 0)

    with pytest.raises(dc.DecisionError, match="JSONDecodeError"):
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=post)


@pytest.mark.parametrize(
    "questions",
    [
        {},
        {"q": {"type": "essay", "instructions": "x", "criteria": {}}},
        {"q": {"type": "choice", "instructions": "x", "criteria": {"only": "one"}}},
        {"q": {"type": "choice", "instructions": 5, "criteria": {"a": "b", "c": "d"}}},
        {"q": {"type": "noul", "instructions": "x", "criteria": {"true": "yes"}}},
    ],
)
def test_malformed_questions_are_rejected_before_a_request(questions):
    with pytest.raises(dc.DecisionError):
        dc.decide(MODEL, {}, questions, "TEST_DECISION_KEY", post=lambda *a, **k: pytest.fail("no request"))


def test_span_01_lite_needs_its_own_state_and_noul_questions():
    span = "respan/span-01-lite"
    seen = []
    resp = {"model": span, "answers": {"same": {"type": "noul", "noul": 0.32}}, "usage": {}}
    res = dc.decide(span, SPAN_STATE, NOUL_Q, "TEST_DECISION_KEY", post=_post_returning(resp, seen))
    assert res.answers == {"same": {"type": "noul", "noul": 0.32}} and seen[0][1]["state"] == SPAN_STATE
    with pytest.raises(dc.DecisionError, match="state"):
        dc.decide(span, {"show": "S"}, NOUL_Q, "TEST_DECISION_KEY", post=lambda *a, **k: pytest.fail("no request"))
    with pytest.raises(dc.DecisionError, match="noul"):
        dc.decide(span, SPAN_STATE, CHOICE_Q, "TEST_DECISION_KEY", post=lambda *a, **k: pytest.fail("no request"))


def test_the_default_transport_is_repairs_post_json(monkeypatch):
    seen = []
    monkeypatch.setattr(repair, "_post_json", lambda url, body, headers=None: seen.append(url) or _ok())
    dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY")
    assert seen == [dc.DECISIONS_URL]


# --- fail closed: the reviewer's probes (every one of these used to be accepted as a real answer) -------------


def _choice_resp(**over):
    ans = {"type": "choice", "choice": "c1", "probabilities": {"c1": 0.9, "c2": 0.05, "none": 0.05}, "confidence": 0.9}
    ans.update(over)
    return {"model": MODEL, "answers": {"pick": ans}, "usage": {}}


@pytest.mark.parametrize(
    "over",
    [
        {"probabilities": {"c1": 1.0, "c2": 1.0, "none": 1.0}},  # sums to 3
        {"probabilities": {"c1": 0.5, "c9": 0.5}},  # an option that was never offered
        {"probabilities": {"c1": 1.5, "c2": -0.5}},  # outside 0..1
        {"probabilities": {"c1": 0.4, "c2": 0.4}},  # sums to 0.8
        {"probabilities": {"c1": float("nan"), "c2": 0.5}},
        {"confidence": 7},
        {"confidence": -1},
        {"confidence": float("nan")},
        {"confidence": float("inf")},
        {"confidence": True},
        {"choice": ["c1"]},
        {"choice": {"c1": 1}},
        {"choice": 1},
        {"choice": None},
    ],
)
def test_choice_answers_that_do_not_hold_together_are_rejected(over):
    with pytest.raises(dc.DecisionError):
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=_post_returning(_choice_resp(**over)))


def test_a_clean_choice_answer_with_the_probabilities_summing_to_one_is_accepted():
    """GUARD: passes on the old code."""
    res = dc.decide(
        MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=_post_returning(_choice_resp(probabilities={"c1": 0.98, "c2": 0.01}))
    )
    assert res.answers["pick"]["choice"] == "c1"


@pytest.mark.parametrize(
    "answer", [{"error": "rate limited"}, 5, -3, 1.5, float("nan"), "yes", None, True, [0.3], {"probability": 2}]
)
def test_noul_answers_must_be_a_probability(answer):
    resp = {"model": "respan/span-01-lite", "answers": {"same": answer}, "usage": {}}
    with pytest.raises(dc.DecisionError):
        dc.decide("respan/span-01-lite", SPAN_STATE, NOUL_Q, "TEST_DECISION_KEY", post=_post_returning(resp))


def test_the_served_model_must_be_the_requested_one():
    with pytest.raises(dc.DecisionError, match="model"):
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=_post_returning(_ok(model="other/cheap-model")))


def test_a_dated_version_suffix_is_accepted_and_the_served_id_is_kept():
    jev = "typesafe/jev-1.13"
    res = dc.decide(jev, {}, CHOICE_Q, "TEST_DECISION_KEY", post=_post_returning(_ok(model="typesafe/jev-1.13-20260917")))
    assert res.model == "typesafe/jev-1.13-20260917"
    for bad in ("typesafe/jev-1.13-beta", "typesafe/jev-1.130", "typesafe/jev-1.13-"):
        with pytest.raises(dc.DecisionError):
            dc.decide(jev, {}, CHOICE_Q, "TEST_DECISION_KEY", post=_post_returning(_ok(model=bad)))


def test_the_free_tag_is_a_routing_tag_not_part_of_the_identity():
    res = dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=_post_returning(_ok(model="inception/mercury-decide")))
    assert res.model == "inception/mercury-decide"


def test_non_finite_numbers_anywhere_in_the_response_are_rejected():
    resp = _ok()
    resp["usage"] = {"input_tokens": float("inf")}
    with pytest.raises(dc.DecisionError, match="finite"):
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=_post_returning(resp))


def test_the_user_agent_is_the_honest_constant():
    assert dc.USER_AGENT == "DubTitlerr-glossary-bakeoff/1.0"
    seen = []
    dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=_post_returning(_ok(), seen))
    assert seen[0][2]["User-Agent"] == "DubTitlerr-glossary-bakeoff/1.0"


# --- CommandCode's Provider API (the `jev` arm) -------------------------------------------------------------

import http.server  # noqa: E402
import threading  # noqa: E402

CC_MODEL = "typesafe/jev"


def _cc_ok(model=CC_MODEL):
    return {
        "model": model,
        "answers": {
            "pick": {"type": "choice", "choice": "c1", "probabilities": {"c1": 0.9, "c2": 0.05, "none": 0.05}, "confidence": 0.9}
        },
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }  # no id / provider / usage.cost: that is what CommandCode's 200 lacks


def test_commandcode_endpoint_constant_is_the_verified_one():
    assert dc.COMMANDCODE_URL == "https://api.commandcode.ai/provider/v1/systemone"  # .../v1/v1/systemone is a 404
    assert dc.COMMANDCODE_MODELS == frozenset({"typesafe/jev"})


def test_the_commandcode_provider_defaults_url_and_accepts_jev(monkeypatch):
    monkeypatch.setenv("TEST_CC_KEY", KEY)
    seen = []
    res = dc.decide(CC_MODEL, {}, CHOICE_Q, "TEST_CC_KEY", provider="commandcode", post=_post_returning(_cc_ok(), seen))
    assert seen[0][0] == "https://api.commandcode.ai/provider/v1/systemone" and res.model == CC_MODEL
    assert seen[0][2]["User-Agent"] == "DubTitlerr-glossary-bakeoff/1.0" and seen[0][2]["Authorization"] == f"Bearer {KEY}"


def test_the_two_providers_have_disjoint_model_ids():
    post = lambda *a, **k: pytest.fail("no request")  # noqa: E731
    with pytest.raises(dc.DecisionError, match="allowlist"):
        dc.decide(CC_MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=post)  # typesafe/jev is CommandCode-only
    with pytest.raises(dc.DecisionError, match="allowlist"):
        dc.decide("typesafe/jev-1.13", {}, CHOICE_Q, "TEST_DECISION_KEY", provider="commandcode", post=post)  # OpenRouter-only
    with pytest.raises(dc.DecisionError, match="allowlist"):
        dc.decide("upstage/solar-decide-flash", {}, CHOICE_Q, "TEST_DECISION_KEY", provider="commandcode", post=post)
    with pytest.raises(dc.DecisionError, match="provider"):
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", provider="elsewhere", post=post)


def test_openrouter_is_still_the_default_provider_and_url():
    """GUARD: passes on the old code (every existing arm stays byte-identical)."""
    seen = []
    dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=_post_returning(_ok(), seen))
    assert seen[0][0] == "https://openrouter.ai/api/alpha/decisions"


class _FakeCC:
    """A 127.0.0.1 server standing in for CommandCode: records what it receives."""

    def __init__(self, status=200, body=None, retry_after=None):
        outer = self
        self.requests = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                outer.requests.append(
                    {
                        "path": self.path,
                        "auth": self.headers.get("Authorization"),
                        "ua": self.headers.get("User-Agent"),
                        "body": json.loads(self.rfile.read(length)),
                    }  # fmt: skip
                )
                payload = json.dumps(body if body is not None else _cc_ok()).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                if retry_after is not None:
                    self.send_header("Retry-After", str(retry_after))
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}/provider/v1/systemone"

    def close(self):
        self.srv.shutdown()


def test_a_fake_commandcode_server_sees_the_right_path_bearer_agent_and_body(monkeypatch):
    monkeypatch.setenv("COMMANDCODE_API_KEY", KEY)
    cc = _FakeCC()
    try:
        res = dc.decide(CC_MODEL, {"show": "S"}, CHOICE_Q, "COMMANDCODE_API_KEY", provider="commandcode", url=cc.url)
    finally:
        cc.close()
    r = cc.requests[0]
    assert r["path"] == "/provider/v1/systemone" and r["auth"] == f"Bearer {KEY}" and r["ua"] == "DubTitlerr-glossary-bakeoff/1.0"
    assert r["body"] == {"model": CC_MODEL, "state": {"show": "S"}, "questions": CHOICE_Q}
    assert (
        res.answers["pick"]["choice"] == "c1" and res.usage == {"input_tokens": 10, "output_tokens": 2} and res.model == CC_MODEL
    )


def test_a_commandcode_429_with_a_quota_message_is_a_status_only_error_and_never_leaks_the_key(monkeypatch):
    monkeypatch.setenv("COMMANDCODE_API_KEY", KEY)
    slept = []
    cc = _FakeCC(
        status=429, body={"error": f"daily request cap reached for key {KEY}", "plan": "credits exhausted"}, retry_after=1
    )
    try:
        with pytest.raises(dc.DecisionHTTPError) as e:
            dc.decide(CC_MODEL, {}, CHOICE_Q, "COMMANDCODE_API_KEY", provider="commandcode", url=cc.url, sleep=slept.append)
    finally:
        cc.close()
    assert str(e.value) == "HTTP 429" and KEY not in repr(e.value) and "cap" not in str(e.value)
    assert len(cc.requests) == 3 and slept == [1.0, 1.0]  # retried twice like any 429, then gave up


# --- round 2d: self-consistent answers, strict model ids, provider hosts ---------------------------------------------


def test_a_choice_that_contradicts_its_own_probabilities_is_rejected():
    over = {"choice": "c1", "probabilities": {"c1": 0.1, "c2": 0.8, "none": 0.1}}
    with pytest.raises(dc.DecisionError, match="probabilit"):
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=_post_returning(_choice_resp(**over)))
    over = {"choice": "c1", "probabilities": {"c2": 0.9, "none": 0.1}}  # the picked option is not even listed
    with pytest.raises(dc.DecisionError):
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=_post_returning(_choice_resp(**over)))


def test_a_tie_for_the_top_probability_is_consistent():
    over = {"choice": "c2", "probabilities": {"c1": 0.45, "c2": 0.45, "none": 0.1}}
    assert (
        dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", post=_post_returning(_choice_resp(**over))).answers["pick"]["choice"]
        == "c2"
    )


@pytest.mark.parametrize(
    "served", ["typesafe/jev-2", "typesafe/jev-20260917x", "typesafe/jev-2026091", "typesafe/jev-202609171", "typesafe/jev-"]
)
def test_only_an_eight_digit_date_suffix_is_accepted(served):
    with pytest.raises(dc.DecisionError, match="model"):
        dc.decide(CC_MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", provider="commandcode", post=_post_returning(_cc_ok(model=served)))


def test_an_eight_digit_dated_suffix_is_accepted():
    res = dc.decide(
        CC_MODEL,
        {},
        CHOICE_Q,
        "TEST_DECISION_KEY",
        provider="commandcode",
        post=_post_returning(_cc_ok(model="typesafe/jev-20260917")),
    )
    assert res.model == "typesafe/jev-20260917"


@pytest.mark.parametrize(
    "provider,model,url",
    [
        (
            "commandcode",
            "typesafe/jev",
            "https://openrouter.ai/api/alpha/decisions",
        ),  # a CommandCode key must never reach OpenRouter
        ("openrouter", MODEL, "https://api.commandcode.ai/provider/v1/systemone"),  # ...nor an OpenRouter key CommandCode
        ("openrouter", MODEL, "https://evil.example/api/alpha/decisions"),
        ("commandcode", "typesafe/jev", "https://api.commandcode.ai.evil.example/provider/v1/systemone"),
        ("openrouter", MODEL, "http://user@evil.example/x"),
    ],
)
def test_the_request_host_must_be_the_providers_own(provider, model, url):
    with pytest.raises(dc.DecisionError, match="host"):
        dc.decide(
            model, {}, CHOICE_Q, "TEST_DECISION_KEY", provider=provider, url=url, post=lambda *a, **k: pytest.fail("no request")
        )


@pytest.mark.parametrize("url", ["http://127.0.0.1:9999/x", "http://localhost:9999/x"])
def test_loopback_is_allowed_for_tests(url):
    seen = []
    dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY", url=url, post=_post_returning(_ok(), seen))
    assert seen[0][0] == url


def test_the_default_hosts_are_accepted():
    """GUARD: passes on the old code."""
    for provider, model, resp in (("openrouter", MODEL, _ok()), ("commandcode", "typesafe/jev", _cc_ok())):
        assert dc.decide(model, {}, CHOICE_Q, "TEST_DECISION_KEY", provider=provider, post=_post_returning(resp)).answers


# --- the LIVE noul answer shape (captured 2026-10-08): {"type": "noul", "noul": <float in 0..1>} ----------------------

QNOUL = {"q": {"type": "noul", "instructions": "Same entity?", "criteria": {"true": "yes", "false": "no"}}}
REAL_NOUL = [
    # (requested model, provider, served model echoed by the server, the answer as captured)
    (
        "inception/mercury-decide:free",
        "openrouter",
        "inception/mercury-decide-20260930",
        {"type": "noul", "noul": 0.9669140186318742},
    ),
    ("respan/span-01-lite", "openrouter", "respan/span-01-lite-20260925", {"type": "noul", "noul": 0.11070899}),
    ("typesafe/jev", "commandcode", "typesafe/jev", {"type": "noul", "noul": 0.79}),
]


def _state_for(model):
    return SPAN_STATE if model.startswith("respan/") else {"show": "S", "term": "T"}


@pytest.mark.parametrize("model,provider,served,answer", REAL_NOUL)
def test_the_real_captured_noul_answers_are_accepted_with_their_dated_served_ids(model, provider, served, answer):
    resp = {"model": served, "answers": {"q": answer}, "usage": {"input_tokens": 12, "output_tokens": 1}}
    res = dc.decide(model, _state_for(model), QNOUL, "TEST_DECISION_KEY", provider=provider, post=_post_returning(resp))
    assert res.answers["q"]["noul"] == answer["noul"] and res.model == served


@pytest.mark.parametrize(
    "answer",
    [
        {"type": "noul"},  # no `noul` field
        {"type": "noul", "noul": "0.9"},
        {"type": "noul", "noul": None},
        {"type": "noul", "noul": True},
        {"type": "noul", "noul": 1.5},
        {"type": "noul", "noul": -0.1},
        {"type": "noul", "noul": float("nan")},
        {"type": "noul", "noul": float("inf")},
        {"type": "noul", "probability": 0.9},  # the old assumed field is not the live one
        {"type": "choice", "noul": 0.9},
        {"noul": 0.9},  # no type
        0.9,  # the bare-number form is gone
        [0.9],
        "yes",
        None,
    ],
)
def test_a_noul_answer_must_be_the_live_shape(answer):
    resp = {"model": "respan/span-01-lite-20260925", "answers": {"q": answer}, "usage": {}}
    with pytest.raises(dc.DecisionError):
        dc.decide("respan/span-01-lite", SPAN_STATE, QNOUL, "TEST_DECISION_KEY", post=_post_returning(resp))


def test_extra_fields_in_a_noul_answer_do_not_make_it_invalid():
    resp = {"model": "respan/span-01-lite-20260925", "answers": {"q": {"type": "noul", "noul": 0.2, "trace": "x"}}, "usage": {}}
    assert (
        dc.decide("respan/span-01-lite", SPAN_STATE, QNOUL, "TEST_DECISION_KEY", post=_post_returning(resp)).answers["q"]["noul"]
        == 0.2
    )


def test_score_answers_keep_their_previous_strict_rule():
    """GUARD: passes on the old code. The `score` shape was not captured live, so it is not widened."""
    q = {"s": {"type": "score", "instructions": "How well?", "criteria": {"a": "x", "b": "y"}}}
    ok = {"model": MODEL, "answers": {"s": 0.5}, "usage": {}}
    assert dc.decide(MODEL, {}, q, "TEST_DECISION_KEY", post=_post_returning(ok)).answers["s"] == 0.5
    bad = {"model": MODEL, "answers": {"s": {"type": "noul", "noul": 0.5}}, "usage": {}}
    with pytest.raises(dc.DecisionError):
        dc.decide(MODEL, {}, q, "TEST_DECISION_KEY", post=_post_returning(bad))
