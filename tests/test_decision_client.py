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
    assert headers["Authorization"] == f"Bearer {KEY}" and "Mozilla" in headers["User-Agent"]
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
    resp = {"model": span, "answers": {"same": 0.32}, "usage": {}}
    res = dc.decide(span, SPAN_STATE, NOUL_Q, "TEST_DECISION_KEY", post=_post_returning(resp, seen))
    assert res.answers == {"same": 0.32} and seen[0][1]["state"] == SPAN_STATE
    with pytest.raises(dc.DecisionError, match="state"):
        dc.decide(span, {"show": "S"}, NOUL_Q, "TEST_DECISION_KEY", post=lambda *a, **k: pytest.fail("no request"))
    with pytest.raises(dc.DecisionError, match="noul"):
        dc.decide(span, SPAN_STATE, CHOICE_Q, "TEST_DECISION_KEY", post=lambda *a, **k: pytest.fail("no request"))


def test_the_default_transport_is_repairs_post_json(monkeypatch):
    seen = []
    monkeypatch.setattr(repair, "_post_json", lambda url, body, headers=None: seen.append(url) or _ok())
    dc.decide(MODEL, {}, CHOICE_Q, "TEST_DECISION_KEY")
    assert seen == [dc.DECISIONS_URL]
