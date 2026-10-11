"""The glossary stages' DECISION backend: a decision model (Mercury Decide, Jev, ...) answers verify's and acquire's questions.

One implementation for production and the bake-off: tools/glossary_bakeoff.py imports the question builders from here, so what
the evaluation measured is what runs. The transport, response validation, key hygiene and https/host binding are
decision_client's; this module adds the questions (framing v1), the mapping from an answer to the adjudication shapes
`glossary_verify.apply_results` / `glossary_acquire.escalate` consume, the failure policy and the per-run counters.

  verify   one `choice` question over the candidate wiki titles plus a `none` option. A non-none pick whose confidence is at
           least VERIFY_DECISION_TAU is 'high' (an expansion of the term is then WRITTEN by apply_results, a respelling is
           flagged), below it 'low'; a none pick is canonical '' / confidence 'none'. The confidence is the answer's own, or
           the probability it gives the pick; with neither the pick is 'low' -- a number is required for 'high'.
  acquire  one `noul` question over a pair of spellings: same_entity = noul >= 0.5; 'high' when max(noul, 1 - noul) is at
           least ACQUIRE_DECISION_TAU, else 'low'.

A failed call (transport, HTTP, a response that fails validation) is NEVER turned into an answer. VERIFY_DECISION_FALLBACK:
  none   (default) the term stays PENDING (verify) / the pair is "unavailable" and not cached (acquire): retried next run;
  local  the stage's local model decides instead (VERIFY_DECISION_LOCAL_BACKEND, else REPAIR_BACKEND if llamacpp/ollama,
         else ollama), and the fallback is logged and counted.
Either way `counters()` says how many calls were made, succeeded, failed, fell back or were left pending, and the stages print
one summary line and put the same numbers in their report, so a rebuild can prove the old model was not used silently.

Environment (all optional; read per call):
  VERIFY_DECISION_MODEL      default inception/mercury-decide:free (any id decision_client allows for its provider; not Span)
  VERIFY_DECISION_URL        the provider's endpoint; default per provider; https on the provider's host. Loopback
                             (127.0.0.1 / localhost) is also accepted, for tests, in production too
  VERIFY_DECISION_KEY_ENV    the NAME of the env var holding the key; default OPENROUTER_JEV_API_KEY (OpenRouter models) or
                             COMMANDCODE_API_KEY (typesafe/jev)
  VERIFY_DECISION_TAU        default 0.5, in [0, 1]
  ACQUIRE_DECISION_TAU       default 0.8, in [0.5, 1]
  VERIFY_DECISION_FALLBACK   none (default) | local
  VERIFY_DECISION_LOCAL_BACKEND  llamacpp | ollama (only for the local fallback)
  VERIFY_DECISION_BREAKER    default 5; consecutive failed terms after which the provider is not called again this run
                             (0 = off). The rest of the run is pending (fallback none) or answered locally (fallback local)
  VERIFY_DECISION_WORKERS    default 1; concurrent adjudications in verify() (the local backends keep VERIFY_WORKERS)
  VERIFY_DECISION_RETRIES    default 0, at most 5; retries after a 429 / 5xx within one call (the next sweep retries anyway)"""

from __future__ import annotations

import math
import os
import threading
import urllib.parse
from dataclasses import dataclass

import decision_client
from common import log

NONE_OPTION = "no candidate is the same named entity"
DEFAULT_MODEL = "inception/mercury-decide:free"
DEFAULT_KEY_ENV = {"openrouter": "OPENROUTER_JEV_API_KEY", "commandcode": "COMMANDCODE_API_KEY"}
FALLBACKS = ("none", "local")


# ---- the v1 questions (shared with tools/glossary_bakeoff.py) ---------------------------------------------------------------


# Bump when the question wording or the _pick_confidence scoring changes:
# it invalidates journaled decision answers (adjudication_journal keys on it), so none is
# served across such a change.
DECISION_CLIENT_VERSION = "1"


def verify_question(show, term, titles):
    """(state, questions, options) for one verify item: options maps c1.. to the candidate titles, in the order given."""
    options = {f"c{i}": t for i, t in enumerate(titles, 1)}
    q = {
        "type": "choice",
        "instructions": (
            f'A term was mined from the English dub of "{show}". Pick the candidate wiki page that is the '
            f'SAME named entity as the term "{term}". Choose "none" if no candidate is the same entity.'
        ),
        "criteria": {**options, "none": NONE_OPTION},
    }
    return {"show": show, "term": term}, {"pick": q}, options


def acquire_instructions(show, a, b):
    return (
        f'Two spellings appear in the English dub of "{show}": "{a}" and "{b}". Are they the SAME name '
        "mis-transcribed (true), or two different legitimate forms such as a nickname, a title or a separate character (false)?"
    )


def acquire_noul_question(show, a, b):
    return {
        "type": "noul",
        "instructions": acquire_instructions(show, a, b),
        "criteria": {"true": "the same name, mis-transcribed", "false": "two different forms"},
    }


def acquire_question(show, a, b, quotes_a, quotes_b):
    """(state, questions) for one acquire pair."""
    state = {"show": show, "spelling_a": a, "spelling_b": b, "quotes_a": quotes_a, "quotes_b": quotes_b}
    return state, {"same": acquire_noul_question(show, a, b)}


# ---- configuration -------------------------------------------------------------------------------


class ConfigError(ValueError):
    """A decision-backend setting that cannot be used. The message names the variable, never a value that could be a key."""


@dataclass(frozen=True)
class Settings:
    model: str
    provider: str
    url: str | None
    key_env: str
    tau: float
    acquire_tau: float
    fallback: str
    breaker: int
    workers: int
    retries: int


def _fraction(env, name, default, lo):
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not (math.isfinite(value) and lo <= value <= 1):
        raise ConfigError(f"{name} must be a number between {lo} and 1")
    return value


def _count(env, name, default, lo, hi):
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = lo - 1
    if not lo <= value <= hi:
        raise ConfigError(f"{name} must be a whole number between {lo} and {hi}")
    return value


def settings(env=None):
    """The decision settings from the environment (defaults above); ConfigError when one is unusable."""
    env = os.environ if env is None else env
    model = (env.get("VERIFY_DECISION_MODEL") or "").strip() or DEFAULT_MODEL
    if model in decision_client.SPAN_MODELS:
        raise ConfigError(
            "VERIFY_DECISION_MODEL: Span models score one candidate at a time and cannot answer the choice question"
        )
    provider = "commandcode" if model in decision_client.COMMANDCODE_MODELS else "openrouter"
    fallback = (env.get("VERIFY_DECISION_FALLBACK") or "").strip() or "none"
    if fallback not in FALLBACKS:
        raise ConfigError(f"VERIFY_DECISION_FALLBACK must be one of {', '.join(FALLBACKS)}")
    return Settings(
        model=model,
        provider=provider,
        url=(env.get("VERIFY_DECISION_URL") or "").strip() or None,
        key_env=(env.get("VERIFY_DECISION_KEY_ENV") or "").strip() or DEFAULT_KEY_ENV[provider],
        tau=_fraction(env, "VERIFY_DECISION_TAU", 0.5, 0.0),
        acquire_tau=_fraction(env, "ACQUIRE_DECISION_TAU", 0.8, 0.5),
        fallback=fallback,
        breaker=_count(env, "VERIFY_DECISION_BREAKER", 5, 0, 1000),
        workers=_count(env, "VERIFY_DECISION_WORKERS", 1, 1, 16),
        retries=_count(env, "VERIFY_DECISION_RETRIES", 0, 0, 5),
    )


class _PreflightOk(Exception):
    pass


def _stop_before_sending(url, body, headers=None):
    raise _PreflightOk


def problem():
    """Why the decision backend cannot run, or "" when it can. No request is made: decision_client validates the model, the
    provider host, https and the key BEFORE it sends, so a stub transport that raises is reached only by a usable setup."""
    try:
        s = settings()
        decision_client.decide(
            s.model,
            {"preflight": True},
            {"pick": {"type": "choice", "instructions": "preflight", "criteria": {"c1": "a", "none": "b"}}},
            s.key_env,
            provider=s.provider,
            url=s.url,
            post=_stop_before_sending,
        )
    except ConfigError as e:
        return str(e)
    except decision_client.DecisionError as e:
        if str(e) == f"request failed: {_PreflightOk.__name__}":
            return ""
        return f"VERIFY_DECISION_*: {e}"
    return ""


# ---- counters (per run) --------------------------------------------------------------------------

_lock = threading.Lock()
_COUNTS = {"calls": 0, "ok": 0, "failures": 0, "fallbacks": 0, "pending": 0}
_breaker = {"streak": 0, "tripped_after": 0}  # consecutive failed terms; tripped_after > 0 once the breaker has opened


def reset():
    with _lock:
        for k in _COUNTS:
            _COUNTS[k] = 0
        _breaker.update(streak=0, tripped_after=0)


def counters():
    """The per-run counters; `breaker_tripped_after` is present only once the breaker has opened."""
    with _lock:
        out = dict(_COUNTS)
        if _breaker["tripped_after"]:
            out["breaker_tripped_after"] = _breaker["tripped_after"]
        return out


def _breaker_open():
    with _lock:
        return _breaker["tripped_after"] > 0


def _note_success():
    with _lock:
        _breaker["streak"] = 0


def _note_failure(limit):
    """Count one failed term; open the breaker (once, logged once) at ``limit`` consecutive failures. 0 = off."""
    with _lock:
        _breaker["streak"] += 1
        trip = limit > 0 and _breaker["streak"] >= limit and not _breaker["tripped_after"]
        if trip:
            _breaker["tripped_after"] = _breaker["streak"]
    if trip:
        log(
            f"  decision breaker tripped after {limit} consecutive failures: no more provider calls this run "
            "(the rest is left pending, or answered locally with VERIFY_DECISION_FALLBACK=local)"
        )


def _bump(name):
    with _lock:
        _COUNTS[name] += 1


def summary_line():
    c = counters()
    line = (
        f"decision backend: model={settings().model} calls={c['calls']} ok={c['ok']} failures={c['failures']} "
        f"fallbacks={c['fallbacks']} pending={c['pending']}"
    )
    if "breaker_tripped_after" in c:
        line += f" breaker tripped after {c['breaker_tripped_after']} failures"
    return line


def announce(stage):
    """Say at the start of a run which fields leave the machine and where: the host only, never a path, query or key."""
    s = settings()
    host = urllib.parse.urlsplit(s.url or decision_client.PROVIDERS[s.provider][0]).hostname
    if stage == "acquire":
        what = "the show name, both spellings of each pair and up to a few transcript lines quoting each"
    else:
        what = "the show name, the term and its candidate wiki page titles"
    log(f"glossary {stage}: sending {what} to {host} (model {s.model}) for each decision; nothing else leaves the machine")


# ---- the calls -----------------------------------------------------------------------------------


def _decide(s, state, questions):
    return decision_client.decide(s.model, state, questions, s.key_env, provider=s.provider, url=s.url, retries=s.retries)


def _failure(what, e):
    """Count and log a failed call. Only a DecisionError's message (a status or a class name, key-free by construction) or an
    exception class name is shown."""
    _bump("failures")
    detail = str(e) if isinstance(e, decision_client.DecisionError) else type(e).__name__
    log(f"  decision call failed ({what}): {detail}")


def _pick_confidence(ans):
    conf = ans.get("confidence")
    if conf is None and isinstance(ans.get("probabilities"), dict):
        conf = ans["probabilities"].get(ans["choice"])
    return conf if isinstance(conf, (int, float)) and not isinstance(conf, bool) else None


def adjudicate_verify(term, titles, show, local):
    """One verify decision -> {'canonical', 'confidence', 'dub_note'}, or the local fallback's answer, or None (pending)."""
    s = settings()
    if _breaker_open():  # no provider call: the term is pending, or answered locally, exactly as after a failed call
        if s.fallback == "local":
            _bump("fallbacks")
            return local()
        _bump("pending")
        return None
    state, questions, options = verify_question(show, term, titles)
    _bump("calls")
    try:
        ans = _decide(s, state, questions).answers["pick"]
    except Exception as e:  # noqa: BLE001 -- fail closed: no pick is invented
        _failure(f"verify {term!r}", e)
        _note_failure(s.breaker)
        if s.fallback == "local":
            _bump("fallbacks")
            log(f"  falling back to the local model for {term!r}")
            return local()
        _bump("pending")
        log(f"  leaving {term!r} pending (VERIFY_DECISION_FALLBACK=none)")
        return None
    _bump("ok")
    _note_success()
    canonical = options.get(ans["choice"], "")
    if not canonical:
        return {"canonical": "", "confidence": "none", "dub_note": ""}
    conf = _pick_confidence(ans)
    return {"canonical": canonical, "confidence": "high" if conf is not None and conf >= s.tau else "low", "dub_note": ""}


def adjudicate_pair(variant, canonical, ctx_v, ctx_c, show, local):
    """One acquire decision -> {'same_entity', 'confidence'}, the local fallback's answer, or the "unavailable" shape."""
    s = settings()
    if _breaker_open():
        if s.fallback == "local":
            _bump("fallbacks")
            return local()
        _bump("pending")
        return {"same_entity": False, "confidence": "none", "unavailable": True}
    state, questions = acquire_question(show, variant, canonical, ctx_v, ctx_c)
    _bump("calls")
    try:
        p = _decide(s, state, questions).answers["same"]["noul"]
    except Exception as e:  # noqa: BLE001 -- fail closed
        _failure(f"merge {variant!r}/{canonical!r}", e)
        _note_failure(s.breaker)
        if s.fallback == "local":
            _bump("fallbacks")
            log(f"  falling back to the local model for {variant!r}/{canonical!r}")
            return local()
        _bump("pending")
        return {"same_entity": False, "confidence": "none", "unavailable": True}
    _bump("ok")
    _note_success()
    return {"same_entity": p >= 0.5, "confidence": "high" if max(p, 1 - p) >= s.acquire_tau else "low"}
