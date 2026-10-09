#!/usr/bin/env python3
"""Client for OpenRouter's alpha decisions API (phase 2 of the glossary-stage bake-off).

  POST https://openrouter.ai/api/alpha/decisions     {model, state, questions}

`questions` is a record keyed by question id; each is {type: choice|noul|score, instructions, criteria}.
A choice answer is {"type": "choice", "choice": "<option>", "probabilities": {...}, "confidence": 0..1}.

Rules this client keeps, because the callers are experiments that must never turn a failure into a pick:
  * the API key is read from the env var NAMED by ``key_env`` and appears nowhere else: not in an exception
    message, a log line, argv, or any file. Nothing built from a raised exception's text is ever surfaced
    (http.client quotes header values); only the exception CLASS name and, for HTTP, the status code.
  * the response shape is validated; anything unexpected raises DecisionError. There is no fallback pick.
  * only 429 and 5xx are retried (at most 2 retries, Retry-After honoured and capped, with a total sleep
    budget); every other failure is raised at once.
  * the model id must be in ALLOWED_MODELS, checked before any request.
  * the transport is ``repair._post_json``, which already carries the per-request wall-clock deadline.

Two providers share this request/answer shape: OpenRouter (default, DECISIONS_URL, its model ids in ALLOWED_MODELS) and
CommandCode's Provider API (provider="commandcode", COMMANDCODE_URL, model typesafe/jev). Each id is valid only for its
own provider; the URL and the key variable are chosen per call. The `jev` arm of the glossary bake-off uses CommandCode.

Span-01 Lite is the odd one: its state must be {"input": [{role, content}...], "output": {role, content}} and it
accepts only `noul` questions with plain-string instructions and {"true": str, "false": str} criteria."""

from __future__ import annotations

import math
import os
import re
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, ".")
import repair  # noqa: E402

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
USER_AGENT = "DubTitlerr-glossary-bakeoff/1.0"  # an honest UA; OpenRouter accepts it
ALLOWED_MODELS = frozenset(
    {
        "inception/mercury-decide:free",
        "respan/span-01-lite",
        "respan/span-01-lite:free",
        "upstage/solar-decide-flash",
        "perplexity/pplx-decider-v1.1-27b",
        "openai/gpt-6-luna-decisions",
        "typesafe/jev-1.13",
    }
)
# CommandCode's Provider API serves the same request/answer shape at its own endpoint, under its own model ids. The two
# id sets are disjoint on purpose: an id is valid only for the provider it belongs to (typesafe/jev-1.13 is OpenRouter's,
# typesafe/jev is CommandCode's), so a stray arm cannot send a model to the wrong place or key.
COMMANDCODE_URL = "https://api.commandcode.ai/provider/v1/systemone"  # not .../v1/v1/systemone: that is a 404
COMMANDCODE_MODELS = frozenset({"typesafe/jev"})
PROVIDERS = {"openrouter": (DECISIONS_URL, ALLOWED_MODELS), "commandcode": (COMMANDCODE_URL, COMMANDCODE_MODELS)}
SPAN_MODELS = frozenset({"respan/span-01-lite", "respan/span-01-lite:free"})
QUESTION_TYPES = ("choice", "noul", "score")
MAX_RETRIES = 2
SLEEP_BUDGET_S = 60.0


class DecisionError(Exception):
    """Anything that is not a clean, validated answer. The message never contains the key."""


class DecisionHTTPError(DecisionError):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status = status


@dataclass(frozen=True)
class DecisionResult:
    answers: dict
    usage: dict
    latency_s: float
    model: str
    raw: dict = field(default_factory=dict, repr=False)


def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _check_question(model, qid, q):
    if not isinstance(qid, str) or not qid:
        raise DecisionError("question ids must be non-empty strings")
    if not isinstance(q, dict) or q.get("type") not in QUESTION_TYPES:
        raise DecisionError(f"question {qid!r}: type must be one of {QUESTION_TYPES}")
    if not isinstance(q.get("instructions"), str):
        raise DecisionError(f"question {qid!r}: instructions must be a string")
    crit = q.get("criteria")
    if q["type"] == "choice":
        if (
            not isinstance(crit, dict)
            or len(crit) < 2
            or not all(isinstance(k, str) and isinstance(v, str) for k, v in crit.items())
        ):
            raise DecisionError(f"question {qid!r}: choice criteria must map at least two option ids to descriptions")
    elif q["type"] == "noul":
        if not isinstance(crit, dict) or set(crit) != {"true", "false"} or not all(isinstance(v, str) for v in crit.values()):
            raise DecisionError(f"question {qid!r}: noul criteria must be {{'true': str, 'false': str}}")
    if model in SPAN_MODELS and q["type"] != "noul":
        raise DecisionError(f"{model} accepts only noul questions")


def _check_state(model, state):
    if model in SPAN_MODELS:
        ok = (
            isinstance(state, dict)
            and isinstance(state.get("input"), list)
            and state["input"]
            and all(
                isinstance(m, dict) and isinstance(m.get("role"), str) and isinstance(m.get("content"), str)
                for m in state["input"]
            )
            and isinstance(state.get("output"), dict)
            and isinstance(state["output"].get("role"), str)
            and isinstance(state["output"].get("content"), str)
        )
        if not ok:
            raise DecisionError(f"{model} needs state {{'input': [{{role, content}}...], 'output': {{role, content}}}}")
    elif not isinstance(state, dict):
        raise DecisionError("state must be an object")


def _is_prob(x):
    return _is_number(x) and math.isfinite(x) and 0 <= x <= 1


def _find_nonfinite(obj):
    if isinstance(obj, float):
        return not math.isfinite(obj)
    if isinstance(obj, dict):
        return any(_find_nonfinite(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_find_nonfinite(v) for v in obj)
    return False


def _same_model(requested, served):
    """The served id is the requested one, ignoring case and a ':free' routing tag, or that id plus a dated suffix
    ('-' and digits only, e.g. typesafe/jev-1.13-20260917)."""

    def norm(m):
        m = m.strip().casefold()
        return m[: -len(":free")] if m.endswith(":free") else m

    req, got = norm(requested), norm(served)
    return got == req or re.fullmatch(re.escape(req) + r"-\d+", got) is not None


def validate_response(model, questions, resp):
    """The parsed response, or DecisionError (fail closed: nothing here is ever repaired or guessed).
    Returns (answers, usage, served_model)."""
    if not isinstance(resp, dict):
        raise DecisionError("bad response: not an object")
    if _find_nonfinite(resp):
        raise DecisionError("bad response: contains a non-finite number (NaN or Infinity)")
    served = resp.get("model")
    if not isinstance(served, str) or not served:
        raise DecisionError("bad response: no model echoed")
    if not _same_model(model, served):
        raise DecisionError("bad response: served by a different model than requested")
    answers = resp.get("answers")
    if not isinstance(answers, dict):
        raise DecisionError("bad response: no answers object")
    for qid, q in questions.items():
        if qid not in answers:
            raise DecisionError(f"bad response: no answer for question {qid!r}")
        a = answers[qid]
        if q["type"] == "choice":
            if not isinstance(a, dict) or a.get("type") != "choice":
                raise DecisionError(f"bad response: answer {qid!r} is not a choice")
            choice = a.get("choice")
            if not isinstance(choice, str) or choice not in q["criteria"]:
                raise DecisionError(f"bad response: answer {qid!r} picked an option that was not offered")
            probs = a.get("probabilities")
            if probs is not None:
                ok = isinstance(probs, dict) and all(k in q["criteria"] and _is_prob(v) for k, v in probs.items())
                if not ok or (probs and abs(sum(probs.values()) - 1) > 0.02):
                    raise DecisionError(f"bad response: answer {qid!r} has inconsistent probabilities")
            conf = a.get("confidence")
            if conf is not None and not _is_prob(conf):
                raise DecisionError(f"bad response: answer {qid!r} has a confidence outside 0..1")
        else:  # noul / score: a bare probability (Span-01 Lite) or an object carrying one
            value = a.get("probability", a.get("score")) if isinstance(a, dict) else a
            if not _is_prob(value):
                raise DecisionError(f"bad response: answer {qid!r} is not a probability in 0..1")
    usage = resp.get("usage")
    return answers, (usage if isinstance(usage, dict) else {}), served


def decide(
    model,
    state,
    questions,
    key_env,
    *,
    provider="openrouter",
    url=None,
    post=None,
    sleep=None,
    retries=MAX_RETRIES,
    sleep_budget=SLEEP_BUDGET_S,
):
    """Ask the decisions API of ``provider`` ("openrouter" by default, or "commandcode"); ``url`` defaults to that
    provider's endpoint. Raises DecisionError (never returns a guessed answer)."""
    if provider not in PROVIDERS:
        raise DecisionError(f"unknown provider {provider!r}")
    default_url, allowed = PROVIDERS[provider]
    url = url or default_url
    if model not in allowed:
        raise DecisionError(f"model {model!r} is not in the {provider} allowlist")
    if not isinstance(questions, dict) or not questions:
        raise DecisionError("questions must be a non-empty object keyed by question id")
    for qid, q in questions.items():
        _check_question(model, qid, q)
    _check_state(model, state)
    raw_key = os.environ.get(key_env, "")
    if not raw_key.strip():
        raise DecisionError(f"env var {key_env} is not set")
    key = repair.clean_api_key(raw_key)
    if key is None:
        raise DecisionError(f"the key in env var {key_env} contains spaces or control characters")
    post = post or repair._post_json
    sleep = sleep or time.sleep
    body = {"model": model, "state": state, "questions": questions}
    headers = {"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT}
    slept = 0.0
    attempt = 0
    while True:
        t0 = time.monotonic()
        failure = None  # (kind, detail): built from the exception CLASS / status only, raised outside the except
        resp = None
        try:
            resp = post(url, body, headers=headers)
        except repair._HttpError as e:
            failure = ("http", (e.status, getattr(e, "retry_after", None)))
        except Exception as e:  # noqa: BLE001 -- anything else is a transport/parse failure; only its class is kept
            failure = ("other", type(e).__name__)
        latency = time.monotonic() - t0
        if failure is None:
            break
        if failure[0] == "other":
            raise DecisionError(f"request failed: {failure[1]}")
        status, retry_after = failure[1]
        if (status == 429 or status >= 500) and attempt < retries:
            wait = repair._retry_wait(retry_after, attempt)
            if slept + wait <= sleep_budget:
                sleep(wait)
                slept += wait
                attempt += 1
                continue
        raise DecisionHTTPError(status)
    answers, usage, served = validate_response(model, questions, resp)
    return DecisionResult(answers=answers, usage=usage, latency_s=latency, model=served, raw=resp)
