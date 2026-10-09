#!/usr/bin/env python3
"""REPAIR stage (gold) — fix garbled low-confidence dub dialogue using the video's
own embedded subtitle (a *different* translation of the same scene) as a semantic
anchor, via a local LLM. Runs between generate.py and the assemble stage.

Whisper sometimes mishears hard audio (overlap, SFX, mumbling). Those segments
carry a low ``avg_logprob`` (recorded by generate.py in ``<stem>.dubtitles.conf.json``).
For each such SPEECH segment (low logprob but not music — ``no_speech_prob`` low),
we find the embedded *dialogue* line(s) overlapping that time window and ask a
local LLM to reconstruct the most likely English-DUB line: keep the transcription's
wording where it's plausible, use the subtitle only to resolve the garbled parts,
never copy the subtitle verbatim (dub != sub — localization differs).

Then the ``.srt`` is rewritten from the (possibly repaired) confidence rows and a
``<stem>.dubtitles.repair.csv`` audit (orig -> repaired) is written. Timing untouched.
A ``<stem>.dubtitles.repair-summary.json`` (targets/repaired/skipped/latency stats/model(s))
is written alongside it (V2 A10).

C1: targets are broadened to mid-confidence-AND-lower OR name-suspect lines; the show
glossary is injected into a STRICT prompt (canonical spellings, never invent/swap a name);
the LLM only runs on lines with a fansub anchor (the bake-off showed glossary-only repair
hallucinates names even on qwen3:8b, so no-anchor lines keep the deterministic text); the
LLM output is run back through the deterministic correction to enforce canon.

CPU/network only — the LLM runs on the 2070 (Ollama) or, optionally, a llama.cpp server.
Env:
  OLLAMA_URL           default http://127.0.0.1:11434/api/generate
  REPAIR_MODEL         default qwen3-4b-instruct   (see the note at MODEL: a live
                         2026-09-01 anchored bake-off against real production data)
  REPAIR_BACKEND         ollama | llamacpp | openai  (default llamacpp; see the note at
                         REPAIR_BACKEND — V2 A1 added the dispatch, the default moved later)
  openai backend (REPAIR_BACKEND=openai; any OpenAI-compatible chat API):
  REPAIR_OPENAI_URL      full chat/completions URL
  REPAIR_OPENAI_KEY_ENV  the NAME of the env var holding the API key (read at call time; trailing
                         CR/LF is stripped; the value is never logged)
  REPAIR_MAX_TOKENS      max_tokens, default 1024, minimum 1 (a bad value warns and uses the default)
  REPAIR_EXTRA_BODY      optional JSON object merged into the request body, e.g.
                         {"enable_thinking": false} (cannot replace model/messages; checked per call)
  REPAIR_OPENAI_RETRIES  retries after HTTP 429 / 5xx, default 2, clamped to 0..5 (so up to 3 attempts); waits a finite
                         Retry-After capped at 30 s, else 2 s then 4 s. HTTP 400/404/409/413/422 (on every
                         backend, llamacpp and ollama too) mean "this request was rejected": the line
                         gets no repair, no retry; if EVERY request that reached the model is rejected
                         the episode is refused (wrong model id or URL). 401/403/408/429/5xx and
                         transport errors count as the backend being unreachable.
  Failure handling (all backends, including the default llamacpp/ollama):
  REPAIR_UNREACHABLE_REFUSE_PCT  default 10 (1..100): refuse the episode (keep the shipped srt, stage
                         backend-unreachable) when the backend failed this percent or more of the
                         targets; the loop stops as soon as that is certain
  REPAIR_MAX_CONSECUTIVE_UNREACHABLE  default 5, minimum 1: that many failures in a row = outage, stop
                         and refuse
  REPAIR_RETRY_SLEEP_BUDGET  default 600 s, minimum 0: total retry sleep per episode; once spent (0 =
                         from the start) each remaining target gets a single attempt, except that a
                         Retry-After of 0 s still retries
  REPAIR_REQUEST_DEADLINE  default 300 s (min 10): total wall time of the response to ONE HTTP request,
                         counted from after the connection is made (connecting is bounded by
                         REPAIR_TIMEOUT_CONNECT); REPAIR_TIMEOUT_READ alone is per socket read and a
                         trickling server defeats it
  REPAIR_EPISODE_DEADLINE  default 3600 s (0 or less = off): wall time per episode, checked between targets,
                         before each retry sleep and before the secondary-model call; exceeded = refuse
                         like an outage, logging the elapsed time and how far it got
  STOP_FLAG              soft stop (set by container_run.sh): checked between targets and before any
                         retry; repair stops without rewriting the srt and records the failed stage
                         `stopped`, so the next pass re-runs it
  REPAIR_LLAMACPP_URL    default http://127.0.0.1:8090/v1/chat/completions
                         (chat endpoint: the raw /completion path applies no chat
                         template and yields empty output from instruct models)
  REPAIR_MODEL_SECONDARY default REPAIR_MODEL — two-pass re-check model (V2 A3; no-op if equal)
  REPAIR_TIMEOUT_CONNECT default 10   (seconds; V2 A2)
  REPAIR_TIMEOUT_READ    default 120  (seconds; V2 A2)
  MAX_REF_BORROW default 3     (reject a repair importing this many NEW words that are
                                present in the fansub reference — see accept_repair)
  LEN_RATIO_MIN default 0.6    (…and reject one whose length ratio leaves this band)
  LEN_RATIO_MAX default 1.5
                               C2/C4/C5: on top of these, a repair is rejected unless the
                               RESULT still fits the card — <=MAX_LINES lines of <=MAX_LINE
                               after reflow.wrap_balance, <=MAX_CHARS, and <=MAX_CPS at the
                               card's DISPLAY duration. Card timing is immutable in repair
                               (C1), so the repair gives way, never the timing. The
                               secondary-model pass goes through the identical gate.
  LOGPROB_MIN   default -0.4   (mid-confidence-and-lower; below this is a repair target)
  NSP_MAX       default 0.5    (…and below this no_speech_prob — i.e. it IS speech)
  GLOSSARY_DIR  default /config/glossaries   (per-show glossary, resolved from the path)
  DECISIONS_DIR default /config/decisions    (per-show human verdicts, resolved the same
                               way; absent on every install that has never reviewed
                               anything, which is an empty store and a no-op)
  DECISIONS_APPLY default 1    ([S-4]) apply stored verdicts. A reject keeps the ASR text,
                               a correct substitutes the human's wording, a force admits a
                               repair accept_repair refused, and any of the four marks the
                               line settled so it is not queued for review again. "0" is
                               suggestion-only: verdicts are still recorded by the review,
                               repair simply stops acting on them. NOTHING overrides
                               fits_card — C1 keeps card timing immutable for humans too.
  SUB_LANGS     accepted embedded-sub languages (default eng,en,und,) -- read by
                common.dialogue_intervals (T1: hoisted out of this module)
  MEDIA_UID/GID default 1000/100
Requires ffmpeg/ffprobe + pysubs2.  Built with help of Claude (Anthropic).
"""

import csv
import http.client
import json
import math
import os
import re
import socket
import sys
import threading
import time
import urllib.parse

import card_split
import decisions
import glossary
import hallucination
import ordering
import qc
import reflow
import unresolved
from common import (
    MEDIA_GID,
    MEDIA_UID,
    atomic_write,
    dialogue_intervals,
    find_video,
    out_for,
    read_words,
    stop_requested,
    ts_srt,
    write_stage,
)

_LOGGED_ONCE = set()


def env_int(name, default, lo=None, hi=None):
    """An integer env var, read safely: unset -> ``default``; not an integer -> ``default`` plus one
    warning that names the variable (never its content); otherwise clamped to lo..hi. A typo in one
    of these must not take down ``import repair`` for every backend."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        if name not in _LOGGED_ONCE:
            _LOGGED_ONCE.add(name)
            print(f"  WARNING {name} is not a whole number; using {default}", flush=True)
        return default
    if lo is not None:
        value = max(value, lo)
    if hi is not None:
        value = min(value, hi)
    return value


OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
# qwen3-4b-instruct, not nanbeige4.2-3b -- flipped 2026-09-01 on a live anchored bake-off
# against real production data (Trigun, MARRIAGETOXIN, Serial Experiments Lain), each
# scored on a real embedded fansub anchor. Four real candidates were compared
# (nanbeige4.2-3b, gemma3n-e2b, phi4-mini, qwen3-4b-instruct, all four on real repair
# targets, not synthetic ones); qwen3-4b-instruct was the only one with zero
# hallucinations, zero severe content drops, and zero verbatim-reference-copy instances --
# nanbeige and gemma3n-e2b both imported the reference verbatim on the same Trigun line
# ("4:30 p.m." -> the reference's "1:30 pm."), and phi4-mini fabricated an entire line
# ("How'd he live?" -> "I'm confused.") on MARRIAGETOXIN. This is a DIFFERENT qwen variant
# from the one the original C1 bake-off rejected (qwen3.5:9b, the 84.1%-verbatim-import
# offender the comment here used to describe) -- not a reversal of that finding, a fresh
# measurement of a model that didn't exist when C1 ran. qwen3-4b-instruct was also the
# 2026-08-31 unanchored verdict-bake-off's exact-match leader (59/90 vs nanbeige's 43/90).
MODEL = os.environ.get("REPAIR_MODEL", "qwen3-4b-instruct")
# llamacpp, not ollama. The owner swapped to it on measurement -- it was the stronger
# performer -- and it is what both arms of the quant A/B run on, so the default matches
# what the numbers in the README will have been taken on. It costs a beta user a harder
# install than `ollama pull`; the quickstart carries that, and OLLAMA_URL still works for
# anyone who prefers it.
REPAIR_BACKEND = os.environ.get("REPAIR_BACKEND", "llamacpp")
# Loopback, not a LAN address. The previous default named a host that was DEAD, so the
# documented default could not have worked for anybody -- including the maintainer, who was
# passing this explicitly and had no reason to notice.
LLAMACPP_URL = os.environ.get("REPAIR_LLAMACPP_URL", "http://127.0.0.1:8090/v1/chat/completions")
MODEL_SECONDARY = os.environ.get("REPAIR_MODEL_SECONDARY", MODEL)
OPENAI_URL = os.environ.get("REPAIR_OPENAI_URL", "")
OPENAI_KEY_ENV = os.environ.get("REPAIR_OPENAI_KEY_ENV", "")
OPENAI_MAX_TOKENS = env_int("REPAIR_MAX_TOKENS", 1024, lo=1)
TIMEOUT_CONNECT = float(os.environ.get("REPAIR_TIMEOUT_CONNECT", "10"))
TIMEOUT_READ = float(os.environ.get("REPAIR_TIMEOUT_READ", "120"))
LOGPROB_MIN = float(os.environ.get("LOGPROB_MIN", "-0.4"))  # mid-confidence-and-lower (C1)
NSP_MAX = float(os.environ.get("NSP_MAX", "0.5"))
GLOSSARY_DIR = os.environ.get("GLOSSARY_DIR", "/config/glossaries")
ROOTS = os.environ.get("MERGE_ROOTS", "/data/Media/Anime Library").split(":")
CONF_SUFFIX = ".dubtitles.conf.json"
SRT_SUFFIX = ".eng.dubtitles.srt"


def log(*a):
    print(*a, flush=True)


_sleep = time.sleep  # indirection so tests can run the retry loop without sleeping


def _openai_retries():
    """REPAIR_OPENAI_RETRIES (default 2, clamped to 0..5; garbage -> 2 with one warning), read per call."""
    return env_int("REPAIR_OPENAI_RETRIES", 2, lo=0, hi=5)


# HTTP statuses that are about THIS request (bad payload, unknown model, too large, a content filter),
# not about the backend: the line gets no repair and the episode carries on. Everything else that fails
# (401/403 bad key, 408, 429, 5xx, transport) is outage-like: it must never silently ship zero repairs.
_REJECTED_STATUSES = frozenset({400, 404, 409, 413, 422})
_last_reject = None  # status of the last request-scoped rejection from llm_openai; read via _take_reject()


def _deadline_passed():
    return _episode_deadline_at is not None and time.monotonic() >= _episode_deadline_at


def _client_rejection(e):
    """True (after recording it) when ``e`` is an HTTP error about this one request: the caller returns ""
    for the line instead of reporting the backend unreachable. Shared by every backend."""
    global _last_reject
    if isinstance(e, _HttpError) and e.status in _REJECTED_STATUSES:
        log(f"  llm fail: HTTP {e.status} (the request was rejected; no repair for this line)")
        _last_reject = e.status
        return True
    return False


def _take_reject():
    global _last_reject
    status, _last_reject = _last_reject, None
    return status


_episode_started_at = None
_episode_limit_s = 0
_episode_deadline_at = None  # time.monotonic() value after which this episode is out of time; None = no limit
_retry_budget_left = None  # seconds of retry sleep this episode may still spend; None = unlimited (no episode)
_retry_slept = 0.0  # total seconds spent in retry sleeps; lets callers time the attempts alone


def _retry_sleep(seconds):
    global _retry_slept, _retry_budget_left
    _sleep(seconds)
    _retry_slept += seconds
    if _retry_budget_left is not None:
        _retry_budget_left -= seconds


def _retry_wait(retry_after, attempt):
    """Seconds to wait before retry number ``attempt`` (0-based): a finite Retry-After of
    0 or more, capped at 30 s; anything else (absent, nan, inf, negative, an HTTP-date) backs
    off 2 s then 4 s."""
    try:
        wait = float(retry_after)
        if math.isfinite(wait) and wait >= 0:
            return min(wait, 30.0)
    except (TypeError, ValueError):
        pass
    return 2.0 * 2**attempt


def _log_once(tag, *a):
    """Log a config problem on the first call only (it repeats identically for every card)."""
    if tag not in _LOGGED_ONCE:
        _LOGGED_ONCE.add(tag)
        log(*a)


def clean_api_key(raw):
    """The key from an env value, or None when it is unusable. Strips surrounding whitespace
    (a CRLF .env leaves a trailing \\r); anything left that is not printable, space-free ASCII
    is a config error -- http.client would refuse it with an error text that quotes the key."""
    key = (raw or "").strip()
    if not key or any(not 33 <= ord(ch) <= 126 for ch in key):
        return None
    return key


def _parse_extra_body(raw):
    """REPAIR_EXTRA_BODY -> dict, ValueError on bad JSON. Parsed per call by llm_openai, not
    at import: a typo must not take down every importer, and must not silently send requests
    without the provider flag the operator meant."""
    if not raw.strip():
        return {}
    try:
        extra = json.loads(raw)
    except ValueError as e:
        raise ValueError(f"REPAIR_EXTRA_BODY is not valid JSON: {e}") from e
    if not isinstance(extra, dict):
        raise ValueError("REPAIR_EXTRA_BODY must be a JSON object")
    return extra


def glossary_for(path, gloss_dir=GLOSSARY_DIR):
    """Resolve the show glossary for an episode by walking up to the first ancestor
    directory that has a matching <Show>.json in the glossary dir; else a no-op glossary."""
    d = os.path.dirname(os.path.abspath(path))
    while d and d != os.path.dirname(d):
        gp = os.path.join(gloss_dir, os.path.basename(d) + ".json")
        if os.path.exists(gp):
            return glossary.load(gp)
        d = os.path.dirname(d)
    return glossary.load("")


LOW_WORD_PROB = 0.25  # V2 A7: a single word this unconfident marks the whole card a target


def has_low_prob_word(c):
    """True if any per-word linear probability in ``word_probs`` (V2 A6, generate.py) is
    below LOW_WORD_PROB -- catches a single wildly-mis-heard word hiding inside a card
    whose avg_logprob still looks fine overall. Missing/empty ``word_probs`` (older
    conf.json files predating A6, or a card generate.py couldn't join any words to) ->
    False, backward-compatible."""
    return any(p < LOW_WORD_PROB for p in c.get("word_probs", []))


def is_target(c, gloss):
    """A conf row to send to the LLM: it must be speech (low no_speech_prob) AND either
    mid-confidence-or-lower, name-suspect, OR containing a very-low-confidence word."""
    if c.get("no_speech_prob", 1.0) > NSP_MAX:
        return False
    return c.get("avg_logprob", 0.0) < LOGPROB_MIN or has_low_prob_word(c) or glossary.name_suspect(c.get("text", ""), gloss)


def _glossary_terms(gloss, arc=None, episode=None):
    """The reference-spelling list for the prompt, current episode first, then arc.

    S-13: the cap below is not cosmetic -- measured 2026-08-26 on the live One Pace
    glossary, 1000 chars holds 110 of 140 terms and silently drops 30, `Nico Robin` and
    `Rob Lucci` among them. Whatever sorts last is simply never shown to the model, so the
    order decides which names it can verify against.

    Weighting REORDERS; it never filters. Dropping an out-of-arc name would make things
    worse, not better: a name absent from the list reads to the model as unrecognised, and
    the documented failure (`Oimo` -> `Zoro`) is exactly a valid name being "corrected"
    into a listed one. Every term still fitting the cap is still offered -- the arc's names
    just get first claim on the budget.

    A term in several arcs is prioritised in all of them, so a recurring character is never
    demoted in an arc he genuinely appears in. With no arc, or a glossary carrying no tags
    -- which is every glossary in the library today -- the order is exactly as before.

    [S-9/S-10]: `episode` adds a THIRD, higher tier ahead of the arc tier, populated from
    `episode_tags`. Deliberately asymmetric versus the arc tier: an episode-UNTAGGED term
    is NOT defaulted into the episode-first tier the way an arc-untagged term defaults into
    the arc tier -- it simply falls through to the (unchanged) arc-tier logic below, which
    still applies its own untagged-defaults-IN rule. This is what keeps `episode=None`
    byte-identical to today's 2-tier behaviour: with no episode tier ever populated, the
    rest of the function runs exactly as it did before this parameter existed."""
    terms = list(gloss["names"]) + list(gloss["phrases"])
    terms += list(gloss["token_fixes"].values()) + list(gloss["phrase_fixes"].values())
    seen, out = set(), []
    for t in terms:  # de-dup, preserve order
        if t not in seen:
            seen.add(t)
            out.append(t)
    episode_tags = gloss.get("episode_tags") or {}
    episode_first = []
    if episode and episode_tags:
        episode_first = [t for t in out if episode in (episode_tags.get(t.lower()) or ())]
    remaining = [t for t in out if t not in set(episode_first)]
    tags = gloss.get("arc_tags") or {}
    if arc and tags:
        # stable partition: in-arc terms keep their relative order, then the rest
        # An UNTAGGED name defaults IN. The 92 names already in the library predate
        # tagging; reading "no tags" as "not this arc" would demote the whole existing
        # glossary behind a handful of newly tagged ones, making the first weighted run a
        # strict subset of what the model already had. Only a name KNOWN to belong to other
        # arcs is demoted.
        in_arc = [t for t in remaining if arc in (tags.get(t.lower()) or (arc,))]
        arc_first = in_arc
    else:
        arc_first = []
    out = episode_first + arc_first + [t for t in remaining if t not in set(arc_first)]
    # C12: cap the prompt size on WHOLE-TERM boundaries -- a raw [:1000] slice can cut a
    # name in half mid-word, which would feed the model a garbled "canonical spelling".
    result = ""
    for t in out:
        candidate = t if not result else f"{result}, {t}"
        if len(candidate) > 1000:
            break
        result = candidate
    return result


def skips_unanchored(ref, gloss=None):
    """Whether a card with reference ``ref`` is refused before the LLM is ever called.

    S-12. Historically this was unconditional: no fansub anchor meant no repair, because
    "the bake-off showed glossary-only repair hallucinates names (Oimo->Zoro) even on
    qwen3:8b" and the deterministic layer was the safe ceiling. That ceiling leaves real
    damage on screen -- measured on One Pace S31E01, 161 targets were refused here and 0
    repaired, and the season carries 6,492 such cards. Among them was `Dothamingo`, which
    `glossary.correct()` cannot reach (difflib 0.800 against a 0.84 cutoff; metaphone T0MNK
    vs TFLMNK) and which therefore nothing in the pipeline could fix.

    Re-running those 161 with the gate open produced 21 repairs, 18 acceptable, including
    `Dothamingo` -> `Doflamingo`. But that is ONE episode of ONE show on ONE model against a
    decision taken on a measured sweep, so the gate stays CONDITIONAL and defaults CLOSED.
    Turning it on is a deliberate act, and `substitutes_a_vouched_name` guards the path it
    opens.

    A2. The gate is now declared PER SHOW, in the glossary, rather than by a global that no
    committed artifact records. The live One Pace library was produced with the env flag
    hand-set; nothing in the repo said so, so a merge pass run from the committed scripts
    skipped every card and rebuilt the srt as raw ASR OVER the shipped repairs (reproduced
    on S31E24: targets=144 repaired=0 skipped_no_ref=144). A show declares
    `unanchored_repair` when the user's copies carry no English subtitles for the Japanese
    audio -- a mainstream configuration for dub-only libraries, not a One Pace quirk.

    The global default stays CLOSED and everything above stays the authority on why: a
    show that declares nothing behaves exactly as it did before."""
    return not ref and not (REPAIR_UNANCHORED or (gloss or {}).get("unanchored_repair"))


def build_prompt(asr, sub, gloss, prev_text="", next_text="", arc=None, episode=None):
    """Build the repair prompt. Every element here is the result of a measured sweep over
    real conf.json targets (3 shows x 40 targets, temperature 0), not authorship taste.

    Two failure modes had to be balanced against each other:
      * qwen3.5:9b, told only what NOT to do, rewrote 42% of lines and pasted glossary
        names over correct text ("Border Control" -> "Cipher Pol", "Neptune" ->
        "Nefertari Vivi", "Uchihime" -> "Uchiha" -- a name from another franchise).
      * nanbeige4.2-3b, given the same prohibitions, went inert: 0 safe fixes across 120
        targets, returning the input verbatim, losing the real repairs it used to make.

    What resolved both at once:
      * the name list framed as VERIFICATION ONLY, never as material to apply;
      * an explicit POSITIVE DUTY -- rules phrased only as prohibitions produce a model
        that does nothing, which is not a repair stage;
      * NO worked example of leaving a name alone. Counter-intuitive, but it over-anchored
        inaction: removing it was the single biggest gain in the sweep (nanbeige 12 -> 16
        safe fixes, qwen 6 -> 23) *and* name edits went down for both;
      * nothing after the ASR line. An earlier version put a trailing "Remember:" reminder
        there and the model echoed that rule text into the subtitle output.

    Measured on 120 targets: qwen 6 -> 23 safe fixes (17 -> 14 name edits), nanbeige
    0 -> 16 safe fixes (1 -> 2 name edits), zero prompt leaks or length blowups for either.

    prev_text/next_text are extra context only -- never part of what gets corrected."""
    names = _glossary_terms(gloss, arc, episode)
    head = "You fix speech-recognition errors in one English-dub subtitle line.\n"
    name_line = (f"Reference spellings (VERIFICATION ONLY - this is NOT a list of names to insert): {names}.\n") if names else ""
    # Only with reference spellings to refer to AND the name-part check on (REPAIR_KEEP_NAME_PARTS, default on): the rule and
    # the check
    # switch on together, so a feature that is off costs no prompt change (and no stale human verdicts).
    parts_rule = (
        "- Write each name exactly as the line says it: a given name or surname said alone stays alone, and a full "
        "name stays full. The reference spellings list long forms only for spelling - never add or remove a name part "
        "because of them.\n"
        if names and _keep_name_parts()
        else ""
    )
    ref_intro = (
        (
            "A DIFFERENT translation of this moment is quoted below; use it only to "
            "resolve garbled words and confirm names, never to copy its wording.\n"
        )
        if sub
        else ""
    )
    rules = (
        "Rules:\n"
        "- You MUST fix: run-together sentences with missing punctuation, missing "
        "capitalisation at a sentence start, and obviously garbled ordinary words.\n"
        "- You MUST NOT change any proper noun unless it is an obvious phonetic "
        "misspelling of a reference spelling above.\n"
        "- Never insert a name that is not already in the line.\n"
        f"{parts_rule}"
        "- Do NOT turn ordinary words into names. Keep the wording and length almost identical.\n\n"
        "Example -> ASR line: it worked Now we run\n"
        "Corrected line: It worked. Now we run.\n"
        "(Two sentences were run together with no punctuation. That IS damage - fix it.)\n\n"
        "Return ONLY the corrected line - no quotes, no notes, no rule text.\n\n"
    )
    # C9: the fansub reference is untrusted third-party text -- keep it wrapped in an XML
    # tag so it reads as quoted DATA, not instructions (prompt-injection guard). Context
    # and reference come BEFORE the ASR line: anything trailing it gets echoed into output.
    prev_line = f'Previous line (for context): "{prev_text}"\n' if prev_text else ""
    next_line = f'Next line (for context): "{next_text}"\n' if next_text else ""
    ref_line = f"<official_subtitle_reference>{sub}</official_subtitle_reference>\n" if sub else ""
    return f"{head}{name_line}{ref_intro}{rules}{prev_line}{next_line}{ref_line}ASR line: {asr}\nCorrected line:"


def overlap_ref(ivals, a, b):
    hits = [t for (s, e, t) in ivals if e > a and s < b]  # any time overlap
    return " ".join(hits)[:300]


def _request_deadline():
    """REPAIR_REQUEST_DEADLINE: wall-clock seconds one HTTP request may take in total (default 300, min 10).
    REPAIR_TIMEOUT_READ is per socket read, so a server that trickles a byte every few seconds never trips it."""
    return env_int("REPAIR_REQUEST_DEADLINE", 300, lo=10)


class _HttpError(RuntimeError):
    """HTTP >= 400 from _post_json. Same text as before; ``status`` lets a caller log the code
    alone and ``retry_after`` is the raw Retry-After header (or None) for a caller that retries."""

    def __init__(self, status, message, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _post_json(url, body, headers=None):
    """POST body (dict) as JSON to url with separate connect (TIMEOUT_CONNECT) and read
    (TIMEOUT_READ) timeouts (V2 A2). stdlib's urllib.request.urlopen only exposes a single
    timeout for the whole call (connect + every read), so we go one layer lower via
    http.client: the connect timeout is set on the connection itself (used for connect()),
    then the read timeout is set on the underlying socket right after connecting.
    ``headers`` are added to the default Content-Type (used by the openai backend)."""
    parsed = urllib.parse.urlsplit(url)
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(parsed.hostname, parsed.port, timeout=TIMEOUT_CONNECT)
    deadline = _request_deadline()
    expired = threading.Event()
    sock = []  # the connected socket; conn.sock is reset to None as soon as a will-close response arrives

    def _expire():  # shuts the socket down under whatever read is blocked on it
        expired.set()
        try:
            sock[0].shutdown(socket.SHUT_RDWR)
        except Exception:
            pass

    watchdog = threading.Timer(deadline, _expire)
    watchdog.daemon = True
    request_out = False  # set BEFORE conn.request() starts sending: from then on the server may have the request (and bill it)
    try:
        conn.connect()
        conn.sock.settimeout(TIMEOUT_READ)
        sock.append(conn.sock)
        watchdog.start()
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        hdrs = {"Content-Type": "application/json", **(headers or {})}
        payload = json.dumps(body).encode()  # serialised first: a body that cannot be encoded fails before any byte is sent
        request_out = True
        conn.request("POST", path, body=payload, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        if resp.status >= 300:  # http.client never follows redirects; a 3xx body is not a JSON answer
            getheader = getattr(resp, "getheader", None)
            retry_after = getheader("Retry-After") if getheader else None
            raise _HttpError(resp.status, f"HTTP {resp.status}: {data[:200]!r}", retry_after)
        return json.loads(data)
    except Exception as e:
        if expired.is_set():
            raise TimeoutError(f"request deadline of {deadline}s exceeded") from None
        e.not_sent = not request_out  # read by _is_transport_error: only a failure before transmission started may be re-sent
        raise
    finally:
        watchdog.cancel()
        conn.close()


REPAIR_UNANCHORED = os.environ.get("REPAIR_UNANCHORED", "") not in ("", "0")
# [S-4] Apply stored human verdicts. Default ON: the store is empty on every install that
# has never reviewed anything, and an empty store is a no-op, so the default costs nothing.
# "0" drops the whole path to suggestion-only -- the review still records verdicts, repair
# just stops acting on them -- which is the knob for an operator who wants the queue as a
# report rather than as an authority.
DECISIONS_APPLY = os.environ.get("DECISIONS_APPLY", "1") not in ("", "0")
# The verdicts that SHIP a repair. All three bypass accept_repair identically: its length
# band and borrow limit are heuristics standing in for a reader, and a reader has now read
# the line. They differ in what the gate said at REVIEW time -- `accept` confirms a repair
# it admitted, `force` overrides one it refused, `correct` supplies different words -- which
# is what the review UI offers and what the store counts, not how repair applies them.
#
# `accept` belongs here for a reason that is easy to miss: accept_repair's answer is not
# stable over time. LEN_RATIO_*/MAX_REF_BORROW are operator knobs, the glossary changes, and
# `ref` moves when a video is re-muxed. Re-judging an accepted line means a later glossary
# edit can silently revert a human decision AND re-queue it as a fresh guard rejection.
APPLYING = ("accept", "correct", "force")
MAX_REF_BORROW = int(os.environ.get("MAX_REF_BORROW", "3"))
LEN_RATIO_MIN = float(os.environ.get("LEN_RATIO_MIN", "0.6"))
LEN_RATIO_MAX = float(os.environ.get("LEN_RATIO_MAX", "1.5"))

_WORD = re.compile(r"[a-z']+")


def _words(s):
    return _WORD.findall((s or "").lower())


def borrowed_from_ref(orig, new, ref):
    """Words the repair ADDED that are present in the fansub reference.

    These are the signature of the model treating the reference as the answer rather than
    as a disambiguation aid. Words already in the ASR line don't count (keeping them isn't
    borrowing), and invented words absent from the reference don't either — that is
    hallucination, a different failure with its own guards."""
    had, have, in_ref = set(_words(orig)), _words(new), set(_words(ref))
    return [w for w in have if w not in had and w in in_ref]


def fits_card(text, dur, orig=None):
    """Whether ``text`` can be DISPLAYED legally on a card lasting ``dur`` seconds (C4).

    Validates the candidate as it will actually be written: through the same
    ``reflow.wrap_balance`` + flatten normalisation generate.py uses, so the thing checked
    is the thing shipped. Per line, not total only -- a total-char check passes text that
    is visually invalid (an 85-char card wraps to two legal 42-char lines but is one
    character over the card ceiling; a 49-char card whose word boundaries fall badly wraps
    to a 44-char line), and that blind spot is exactly how the library-wide wrapping defect
    survived. Line lengths are integer character counts, so only cps needs EPS."""
    wrapped = reflow.wrap_balance((text or "").replace("\n", " "))
    if not reflow.layout_faults(wrapped, dur):
        return True
    if orig is None:
        return False
    # The card ALREADY breaks the profile -- ~28% of cards are over cps, and A2
    # deliberately does not retime for cps. Refusing every repair on those would refuse
    # to fix `Zorro`->`Zoro` on a dense line, which is the exact case repair exists to
    # serve. Accept a repair that worsens NO dimension; reject one that worsens any.
    before = reflow.layout_metrics(reflow.wrap_balance((orig or "").replace("\n", " ")), dur)
    after = reflow.layout_metrics(wrapped, dur)
    return all(a <= b + reflow.EPS for a, b in zip(after, before))


PHONETIC_MIN = float(os.environ.get("REPAIR_PHONETIC_MIN", "0.75"))


def _proper_cores(text):
    """Capitalised, non-English, glossary-shaped bare cores -- the tokens both name guards
    reason about. Shared so the two cannot drift apart on what counts as a proper noun."""
    out = []
    for tok in (text or "").split():
        m = glossary._TOKEN_RE.match(tok)
        if not m:
            continue
        core = m.group(2)
        if core[:1].isupper() and len(core) >= glossary.MIN_FUZZY_LEN and not glossary.is_english(core):
            out.append(core)
    return out


def invents_name(orig, new, gloss):
    """True if ``new`` substitutes an INVENTED proper noun for one that was in ``orig``.

    By the time this runs, ``glossary.correct(new, gloss)`` has already executed (see the
    call site in process(), repair.py:513): any token the deterministic tiers can match to
    a glossary name -- exact, hard-fix, or guarded-fuzzy/metaphone -- is already snapped to
    its canonical spelling. So ``Syrahose -> Shirahoshi`` is handled upstream and never
    reaches here. What this function judges is the residue prompt tuning could not close
    (ISSUE-phonetic-name-guard.md, measured on One Pace S29E08, 40 targets, temperature 0):

        Syrahose  -> Shyarros    (the SAME token got the right answer elsewhere in the
                                   same episode -- the model is guessing phonetically
                                   per-call, not recalling a name it recognises)
        Deccan    -> Decman
        Hirohoshi -> Hihohi      (a name already close to correct, destroyed into a
                                   non-word)
        Garnus    -> Garnel

    None of these are reachable from the glossary by any tier the deterministic corrector
    runs, so they ship as fabricated proper nouns. There is deliberately no edit-distance
    or phonetic comparison here -- that is what the fuzzy and metaphone tiers upstream
    already tried, and it is exactly what let a wrong guess through as "close enough" in
    the failures above. The only signal left that is both cheap and precise: did a
    capitalised, non-English, glossary-shaped token DISAPPEAR, and did a token no tier
    recognises take its place. Comparison is on the bare core (glossary._TOKEN_RE, which
    strips leading/trailing punctuation) and case-insensitive -- that is the whole
    casing/punctuation escape hatch, on purpose: ``Garnus,`` -> ``Garnus`` or ``Garnus`` ->
    ``garnus`` reads as the same token, not a substitution.

    Judged on what is GAINED, whether or not anything was lost. A card that conjures a
    capitalised non-English token the glossary does not know is refused even if it replaced
    nothing: `jester` -> `Dester` is a fabrication exactly as much as `Deccan` -> `Decman`,
    and the lowercase original meant the substitution rule could not see it. The cost of
    this width is a repair that legitimately ADDS an unknown name is refused too; that is
    accepted deliberately, because an added name has no original to fall back on and a
    wrong one is indistinguishable from a right one once written.
    """

    # Scope widened 2026-08-26: a gained name is judged on its own, whether or not one was
    # LOST. The original rule required a SUBSTITUTION, which made a name conjured from
    # nothing invisible -- measured on the hotwords spike, where `jester` became `Dester`
    # and neither direction fired, because a lowercase word is not a proper noun to lose.
    #
    # GAINED is measured against every core in ORIG, not only its capitalised ones. A word
    # merely RE-CAPITALISED was not conjured, and punctuation restoration re-capitalises
    # constantly: `that's` -> `That's` after a new sentence boundary, `human` -> `Human`
    # rebuilding a garbled line. Comparing against the capitalised cores alone reported both
    # as fabricated names -- two real repairs refused, caught by the existing suite.
    # (`that's` is doubly exposed: _read_words drops every wordlist entry containing an
    # apostrophe, so is_english() can never be True for a contraction.)
    proper_cores = _proper_cores
    orig_all = {m.group(2).lower() for m in (glossary._TOKEN_RE.match(t) for t in (orig or "").split()) if m}
    known = {n.lower() for n in gloss["names"]} | {v.lower() for v in gloss["token_fixes"].values()}
    return any(c.lower() not in orig_all and c.lower() not in known for c in proper_cores(new))


def substitutes_a_vouched_name(orig, new, gloss):
    """True if ``new`` overrules a name the glossary already vouched for, or reaches for a
    known name that sounds nothing like what it replaced.

    Applied ONLY where there is no fansub reference. `repair.py`'s no-reference skip records
    why: "the bake-off showed glossary-only repair hallucinates names (Oimo->Zoro) even on
    qwen3:8b". Both failures in that shape need the model to be guessing from the glossary
    rather than reading evidence, so with a reference in hand these must NOT fire -- a
    reference-backed `Oimo` -> `Zoro` is exactly the correction repair exists to make, and
    refusing it everywhere would lose real anchored repairs across the library.

    Two rules, both measured 2026-08-26:

    * KNOWN -> KNOWN is refused outright. The glossary vouched for the original; a model
      with no reference has no standing to overrule it.
    * UNKNOWN -> KNOWN must be phonetically close. jaro_winkler admits the genuine fixes --
      dothamingo->doflamingo 0.893, zolo->zoro 0.867, syrahose->shirahoshi 0.755 -- and
      blocks oimo->zoro at 0.667. The threshold is 0.75 and it is KNOWINGLY imperfect:
      vivra->vivi scores 0.848 and gets through. No threshold separates that case, because
      the genuine syrahose->shirahoshi fix scores LOWER than it. That one is a glossary
      COVERAGE gap ("Vivre Card" is a real term absent from the names), not a distance
      problem, and metaphone cannot help either -- it is False for every pair here."""
    known = {n.lower() for n in gloss["names"]} | {v.lower() for v in gloss["token_fixes"].values()}
    orig_cores = _proper_cores(orig)
    new_cores = _proper_cores(new)
    orig_all = {c.lower() for c in orig_cores}
    new_all = {c.lower() for c in new_cores}
    lost = [c for c in orig_cores if c.lower() not in new_all]
    gained = [c for c in new_cores if c.lower() not in orig_all]
    if not (lost and gained):
        return False
    if any(c.lower() in known for c in lost):
        return True  # the glossary already vouched for what was replaced
    # Only the PHONETIC half needs jellyfish; the vouched-name rule above does not, and
    # must keep working when the optional dependency is absent. Degrading both would let
    # the exact bake-off failure through on a box without it.
    gained_known = [c for c in gained if c.lower() in known]
    if gained_known and glossary.jellyfish is not None:
        best = max(glossary.jellyfish.jaro_winkler_similarity(a.lower(), b.lower()) for a in lost for b in gained_known)
        if best < PHONETIC_MIN:
            return True
    return False


# OFF until there is a live measurement. The replay over the 728 Wano cues had no long forms in its cue context, so it measured
# nothing either way; the live glossary has no multi-word NAMES at all (verify writes long forms into phrases), so with this on
# the check also judges mined phrases like 'Grand Line' and 'Devil Fruit'. To measure: repair the Wano episodes with the rebuilt
# glossary once on, once off, and judge the rejected_name_part cues. REPAIR_KEEP_NAME_PARTS=0 turns it off (the maintainer
# decided on 2026-10-09 that it is on by default).
KEEP_NAME_PARTS_DEFAULT = "1"


def _keep_name_parts():
    """REPAIR_KEEP_NAME_PARTS=0 turns the name-part check off; unset: on (KEEP_NAME_PARTS_DEFAULT). Read per call."""
    return os.environ.get("REPAIR_KEEP_NAME_PARTS", KEEP_NAME_PARTS_DEFAULT) != "0"


def _name_tokens(text):
    """Lower-cased bare cores of the tokens of ``text`` (punctuation stripped, as the name guards compare them)."""
    cores = [m.group(2).lower() for m in (glossary._TOKEN_RE.match(t) for t in (text or "").split()) if m]
    # a possessive is the same name: "Momonosuke's" -> "momonosuke"
    return [re.sub(r"(?:['\u2019]s|['\u2019])$", "", c) or c for c in cores]


def changes_name_parts(orig, new, gloss):
    """True if ``new`` ADDS or REMOVES a part of a multi-word glossary name next to a name token ``orig`` already had.

    A dub often says one name alone ('Momonosuke'), and the glossary now also lists the long form ('Kouzuki Momonosuke') as a
    spelling reference. The line is the evidence of what was said: a given name or surname said alone stays alone, a full name
    stays full. So an INSERT that completes a glossary full name around a token the line already had ('Momonosuke' ->
    'Kouzuki Momonosuke'), or a DELETE that breaks one ('Kouzuki Momonosuke' -> 'Momonosuke'), is refused.

    A same-length REPLACE is never judged, which is what keeps a misheard token fixable: 'Kojuki Momonosuke' -> 'Kouzuki
    Momonosuke', 'Odin' -> 'Oden'. A replace that GROWS ('Zorro' -> 'Roronoa Zoro') is judged like an insert of its extra
    tokens, unless the new tokens only re-space the old ('Grandline' -> 'Grand Line'). A name invented from nothing, with no
    kept part ('I'm here.' -> 'Nico Robin, I'm here.'), is invents_name's business. Possessives count as the name.
    Tokens are aligned with difflib on the lower-cased bare cores. A fansub reference does not rescue a refusal: the dub line is
    the evidence of what was said, and this runs before any reference logic. Glossary PHRASES count as names here (verify writes
    long forms there), so a mined phrase like 'Grand Line' is judged too -- one reason the check is opt-in."""
    import difflib

    full = set()
    terms = (
        list(gloss["names"]) + list(gloss["phrases"]) + list(gloss["token_fixes"].values()) + list(gloss["phrase_fixes"].values())
    )
    for t in terms:
        toks = tuple(_name_tokens(t))
        if len(toks) >= 2:
            full.add(toks)
    if not full:
        return False
    o, n = _name_tokens(orig), _name_tokens(new)
    inserted, deleted, kept_new, kept_old = set(), set(), set(), set()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, o, n, autojunk=False).get_opcodes():
        if tag == "replace" and (j2 - j1) > (i2 - i1) and "".join(n[j1:j2]) != "".join(o[i1:i2]):
            # A fixed token that also GREW ('Zorro' -> 'Roronoa Zoro', 'Kojuki' -> 'Kouzuki Momonosuke'): the extra tokens are
            # an insert, the aligned ones count as kept. A pure re-spacing ('Grandline' -> 'Grand Line') adds no name part.
            kept_new.update(range(j1, j2))
            inserted.update(range(j1 + (i2 - i1), j2))
        elif tag == "insert":
            inserted.update(range(j1, j2))
        elif tag == "delete":
            deleted.update(range(i1, i2))
        elif tag == "equal":
            kept_old.update(range(i1, i2))
            kept_new.update(range(j1, j2))

    def broken(tokens, changed, kept):
        for f in full:
            for p in range(len(tokens) - len(f) + 1):
                if tuple(tokens[p : p + len(f)]) == f:
                    idx = set(range(p, p + len(f)))
                    if idx & changed and idx & kept:
                        return True
        return False

    return broken(n, inserted, kept_new) or broken(o, deleted, kept_old)


def accept_repair(orig, new, ref, dur, gloss, prev_text=None):
    """Whether to write ``new`` over ``orig`` on a card lasting ``dur`` seconds.

    A dubtitle must carry what the DUB AUDIO says. The reference is a different translation
    of the same scene, so lifting its phrasing produces a subtitle that reads well and is
    wrong against the sound — the worst kind of error here, because it looks correct.

    The standard is REFERENT AND SENSE, not word-for-word fidelity (owner's bar,
    2026-08-26). A deviation carrying the same meaning is acceptable -- `Hawkeye Dracule
    Mihawk` shortened to `Mihawk` was ruled acceptable explicitly, being the same character
    and the same information. A deviation changing the meaning is not: `factory` -> `needle`
    destroys it, `VIVRA card` -> `Vivi card` swaps an item for a character.

    NOTHING BELOW ENFORCES THAT. The checks here are mechanical -- length ratio, card fit,
    reference borrowing, invented names -- and none can tell "same meaning" from "meaning
    destroyed"; both examples above pass this function today, verified 2026-08-26. The bar
    is enforced by human review of the repaired lines, which is why the spec makes that
    review a required step of accepting a measured episode rather than an optional one.

    Measured over every repair the library had accumulated before this guard: qwen3:8b
    imported reference words in 84.1% of its repairs (29.2% imported three or more),
    nanbeige in 52.5% (17.1%). Lines like "That's enough of that, idiots!" became "Hold
    it, you brats!" — the reference, verbatim. The old gate was a 0.4–2.5 length band,
    which a same-length rewrite sails straight through.

    C2: the length ratio cannot see readability. LEN_RATIO_MAX is 1.5, so 40 chars on a
    3.0s card (13 cps) may become 58 (19.3 cps) with nothing re-checking it. The card's
    timing is immutable here (C1) -- a repair that does not fit the card it is repairing
    is rejected, never accommodated by moving the card -- so ``dur`` is required, not
    optional: a caller that does not know the card cannot be allowed to skip the check.

    Kept deliberately permissive for the case the reference exists to serve: a single
    misheard proper noun corrected from it.

    ``gloss`` is required for the same reason ``dur`` is: the phonetic-name-guard
    (``invents_name``, below) needs to know what the show's names ARE to tell a real
    correction from a fabricated one, so a caller that cannot say what those names are
    must not be allowed to silently skip the check by omitting the argument."""
    return rejecting_guard(orig, new, ref, dur, gloss, prev_text=prev_text) is None


def _accept_punct_case_only() -> bool:
    """REPAIR_ACCEPT_PUNCT_CASE_ONLY=1 (default off): see rejecting_guard. Read per call."""
    return os.environ.get("REPAIR_ACCEPT_PUNCT_CASE_ONLY") == "1"


_SENTENCE_END = re.compile(r"[.!?]")
_ELLIPSIS = re.compile(r"\.{2,}|\u2026")
_CLOSERS = "\"')]}\u201d\u2019"


def _ends_sentence(text):
    """Whether ``text`` (the end of a card, or the gap between two words) finishes a sentence: it holds a '.', '!' or '?' that is
    not part of an ellipsis ('...', '\u2026'). Closing quotes and brackets after the mark do not matter."""
    return bool(_SENTENCE_END.search(_ELLIPSIS.sub("", (text or "").rstrip(_CLOSERS + " \n"))))


def _card_starts_sentence(prev_text):
    """The card's first word starts a sentence only when the previous card finished one (or there is no previous card, ``""``).
    ``None`` is 'no information': a lower-case start usually CONTINUES the previous card, so there is no card-initial leniency."""
    if prev_text is None:
        return False
    end = prev_text.rstrip(_CLOSERS + " \n")
    if not end:
        return True
    return end[-1] in ".!?" and not end.endswith(("..", "\u2026"))


def _gap_signature(gap):
    return (sorted(len(m) for m in re.findall(r"\.{2,}", gap)), gap.count("\u2026"))


def _punct_only_added(old_gap, new_gap):
    """``new_gap`` (the non-word, non-space characters between two words) is ``old_gap`` plus added '.' and ',' only: the old
    characters survive in order, every extra is '.' or ',', and no ellipsis appears or grows."""
    if old_gap == new_gap:
        return True
    i = 0
    for ch in new_gap:
        if i < len(old_gap) and ch == old_gap[i]:
            i += 1
        elif ch not in ".,":
            return False
    return i == len(old_gap) and _gap_signature(old_gap) == _gap_signature(new_gap)


def _lenient_case_change(old, new, sentence_start, single_names, entry_covered):
    """Whether turning the word ``old`` into ``new`` (equal ignoring case) is a case edit that cannot change meaning: the first
    letter of a sentence, the pronoun i -> I, ok -> OK, a single-word glossary entry that is not an ordinary word (luffy -> Luffy,
    not law -> Law), or a word that completes a whole multi-word glossary entry in sequence (devil fruit -> Devil Fruit, not a
    lone line -> Line). Anything else (us -> US, march -> March, turkey -> Turkey) can turn a common word into a name or a
    country, so it counts as a word change."""
    if old == new:
        return True
    if sentence_start and old[:1].islower() and new == old[:1].upper() + old[1:]:
        return True
    if old == "i" and new == "I":
        return True
    if old.lower() == "ok" and new == "OK":
        return True
    if entry_covered:
        return True
    # Fails closed without a word list: the bundled fallback is 228 words, so 'rain' would look like a name.
    return new in single_names and glossary.wordlist_status() != "missing" and not glossary.is_ordinary_word(new)


def _guard_terminal_punct() -> bool:
    """REPAIR_GUARD_TERMINAL_PUNCT=1 (default off): see terminal_punct_changed. Read per call."""
    return os.environ.get("REPAIR_GUARD_TERMINAL_PUNCT") == "1"


def _terminal_run(text):
    """The run of '.', '!', '?' and the ellipsis character that ends ``text`` (closing quotes, brackets and spaces ignored)."""
    t = (text or "").rstrip(_CLOSERS + " \n\t")
    end = len(t)
    while end and t[end - 1] in ".!?\u2026":
        end -= 1
    return t[end:]


def terminal_punct_changed(orig, new) -> bool:
    """True when ``new`` changes the KIND of a line's terminal punctuation in a way that changes tone or meaning: it
    adds or removes a terminal '?' (question <-> statement, '!' <-> '?' included), or turns a trailing ellipsis ('...',
    '\u2026') into '.' or '!' or the reverse ('Damn...' -> 'Damn!'). Comma <-> period, '.' <-> '!' and '?!' -> '?' are
    style and pass. Only the END of the line counts. Measured on real accepted repairs this class is about 5 of the 7
    harmful punctuation changes in a hand-judged 40."""
    a, b = _terminal_run(orig), _terminal_run(new)
    if ("?" in a) != ("?" in b):
        return True
    ell = lambda r: ".." in r or "\u2026" in r  # noqa: E731
    return ell(a) != ell(b) and bool(a) and bool(b)


def is_punct_case_only(orig, new, gloss=None, prev_text=None) -> bool:
    """``new`` differs from ``orig`` (exactly) but changes no word and only ADDS punctuation: the words are the same SEQUENCE
    (a reorder is a change), the punctuation between them differs only by added '.' and ',' (nothing removed, replaced or
    reordered: hyphens, apostrophes outside a word, brackets, quotes, '?', '!', musical notes and ellipses all count; an added
    ellipsis is not allowed), and each case change is on the lenient list (see _lenient_case_change; ``gloss`` supplies the
    glossary entries, ``prev_text`` the previous card for the card-initial capital). Anything else is not punctuation-only and
    meets the ordinary guards. unresolved.word_changes stays a multiset count for the dismissal rule."""
    if not new or new == (orig or ""):
        return False
    fold = lambda t: (t or "").replace("\u2019", "'")  # noqa: E731
    old_text, new_text = fold(orig), fold(new)
    old_words = list(unresolved._WORD.finditer(old_text))
    new_words = list(unresolved._WORD.finditer(new_text))
    if len(old_words) != len(new_words) or [m.group().lower() for m in old_words] != [m.group().lower() for m in new_words]:
        return False

    def gaps(text, words):
        edges = [0, *[x for m in words for x in (m.start(), m.end())], len(text)]
        return ["".join(text[edges[k] : edges[k + 1]].split()) for k in range(0, len(edges), 2)]

    if not all(_punct_only_added(o, n) for o, n in zip(gaps(old_text, old_words), gaps(new_text, new_words))):
        return False
    entries = [str(e) for e in list((gloss or {}).get("names") or []) + list((gloss or {}).get("phrases") or [])]
    single_names = {t[0] for e in entries if len(t := unresolved._WORD.findall(fold(e))) == 1}
    tokens = [m.group() for m in new_words]
    covered = set()
    for e in entries:
        parts = unresolved._WORD.findall(fold(e))
        for at in range(len(tokens) - len(parts) + 1):
            if len(parts) > 1 and tokens[at : at + len(parts)] == parts:
                covered.update(range(at, at + len(parts)))
    prev_end = None
    for k, (old, m) in enumerate(zip(old_words, new_words)):
        start = _card_starts_sentence(prev_text) if prev_end is None else _ends_sentence(new_text[prev_end : m.start()])
        if not _lenient_case_change(old.group(), m.group(), start, single_names, k in covered):
            return False
        prev_end = m.end()
    return True


LAYOUT_SLACK_CHARS = 2  # what an edit that only adds punctuation may add to a card that already breaks the profile


def _no_new_layout_fault(new, dur, orig):
    """``new`` can be shown wherever it breaks no profile rule, or, on a card ``orig`` already broke, breaks no kind of rule that
    ``orig`` did not and grows no dimension (lines, longest line, characters, cps) by more than LAYOUT_SLACK_CHARS characters (and
    the matching cps). fits_card's per-dimension comparison with a small allowance for added punctuation, so an already-bad card
    cannot get much worse."""
    wrapped = reflow.wrap_balance((new or "").replace("\n", " "))
    after_faults = set(reflow.layout_faults(wrapped, dur))
    if not after_faults:
        return True
    original = reflow.wrap_balance((orig or "").replace("\n", " "))
    if not after_faults <= set(reflow.layout_faults(original, dur)):
        return False
    before, after = reflow.layout_metrics(original, dur), reflow.layout_metrics(wrapped, dur)
    slack = (0, LAYOUT_SLACK_CHARS, LAYOUT_SLACK_CHARS, LAYOUT_SLACK_CHARS / max(dur, reflow.EPS))
    return all(a <= b + s + reflow.EPS for a, b, s in zip(after, before, slack))


def rejecting_guard(orig, new, ref, dur, gloss, punct_case_ok=None, prev_text=None):
    """The name of the FIRST guard that refuses ``new`` for ``orig``, or None when accept_repair admits it. accept_repair is
    exactly ``rejecting_guard(...) is None``; the name is what the review queue records (key 'guard') so a human, and later
    measurements, can tell why a proposal was refused:

        empty, unchanged, terminal_punct, invents_name, name_part, vouched_name, length_ratio, fits_card, ref_borrow

    ``punct_case_ok`` (default: REPAIR_ACCEPT_PUNCT_CASE_ONLY=1) gives a proposal that changes only case and punctuation two
    allowances: it is not "unchanged" when the case differs (only for case changes that cannot change meaning: a sentence start,
    i -> I, ok -> OK, a glossary spelling), and fits_card is replaced by "no NEW kind of layout fault and at most +2 characters".
    The relaxed path is for punctuation ADDITIONS only ('.' and ',' added, see is_punct_case_only). NOTE the ordinary gate never
    judges punctuation for MEANING: 'Let's eat, Grandma' -> 'Let's eat Grandma', a moved comma or '?' -> '.'
    all pass, with the flag off as well as on; that is why the flag stays off unless a human audits a sample. Measured
    on a real queue, 7 of 100 rejected proposals changed no word, and fits_card refuses an edit that makes an already over-cps
    card worse in ANY dimension, so one added period on a dense card was refused. Every other guard still applies."""
    if not new:
        return "empty"
    if punct_case_ok is None:
        punct_case_ok = _accept_punct_case_only()
    special = punct_case_ok and is_punct_case_only(orig, new, gloss, prev_text)
    if new.lower() == (orig or "").lower() and not special:
        return "unchanged"  # nothing changed
    if _guard_terminal_punct() and terminal_punct_changed(orig, new):
        return "terminal_punct"  # a question became a statement (or the reverse), or an ellipsis became '.'/'!'
    if invents_name(orig, new, gloss):
        return "invents_name"  # phonetic-name-guard: fabricated proper noun, not a real correction
    if _keep_name_parts() and changes_name_parts(orig, new, gloss):
        return "name_part"  # a name said alone stays alone, a full name stays full
    if not ref and substitutes_a_vouched_name(orig, new, gloss):
        return "vouched_name"  # S-14: no reference, so no standing to overrule a vouched name
    ratio = len(new) / max(1, len(orig))
    if not (LEN_RATIO_MIN <= ratio <= LEN_RATIO_MAX):
        return "length_ratio"  # added or dropped a clause
    if not (_no_new_layout_fault(new, dur, orig) if special else fits_card(new, dur, orig)):
        return "fits_card"  # unreadable/undisplayable on THIS card
    if len(borrowed_from_ref(orig, new, ref)) >= MAX_REF_BORROW:
        return "ref_borrow"
    return None


def llm_ollama(prompt, model=None):
    """Ollama /api/generate backend (the original/default path — byte-for-byte the same
    request shape and response parsing as before A1's dispatch refactor)."""
    # think=False keeps qwen3/qwen3.5 from emitting <think> blocks (ignored by qwen2.5)
    body = {"model": model or MODEL, "prompt": prompt, "stream": False, "think": False, "options": {"temperature": 0}}
    try:
        out = _post_json(OLLAMA, body).get("response", "").strip()
        return out.splitlines()[0].strip().strip('"').strip() if out else ""
    except Exception as e:
        if _client_rejection(e):
            return ""
        log("  llm fail:", e)
        return LLM_UNREACHABLE


# A transport failure is NOT an empty reply. Both used to return "", which made a dead
# endpoint indistinguishable from "the model left the line alone" -- so every target on an
# episode landed in llm_empty, `fixed` stayed 0, and the srt was rebuilt from conf.json as
# raw ASR over whatever the last run shipped. A distinct sentinel is the smallest thing that
# lets the caller tell the two apart.
LLM_UNREACHABLE = "\x00unreachable"


def llm_llamacpp(prompt, model):
    """llama.cpp backend, via the OpenAI-compatible /v1/chat/completions endpoint.

    This previously posted a RAW prompt to /completion, which applies NO chat template.
    Verified against a live Nanbeige 4.2-3B server, that path returns nothing but newlines
    -- 200 tokens of "\n" -- because a templated instruct model never sees its template.
    It could only ever have worked for a base/completion model, so REPAIR_BACKEND=llamacpp
    was effectively broken for the models anyone would actually use.

    ``chat_template_kwargs.enable_thinking=false`` is required by this fork: with the
    template applied but thinking still on, the model spends its whole budget on
    reasoning_content and returns an empty message (measured empty after 114s at
    max_tokens=512; correct output in 4.3s with thinking off). An empty reply is treated as
    "no repair" -- never as text to embed, which would put the model's monologue in a
    subtitle.

    No "model" selector is sent (the server has exactly one model loaded); ``model`` is
    accepted for signature parity with llm_ollama and the two-pass dispatch."""
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 80,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        msg = _post_json(LLAMACPP_URL, body)["choices"][0]["message"]
        out = (msg.get("content") or "").strip()
        return out.splitlines()[0].strip().strip('"').strip() if out else ""
    except Exception as e:
        if _client_rejection(e):
            return ""
        log("  llm fail:", e)
        return LLM_UNREACHABLE


_TRANSPORT_RETRIES_TOTAL = 0  # retries made by _post_with_transport_retries over the life of the process


def transport_retries_total():
    return _TRANSPORT_RETRIES_TOTAL


def _transport_retries():
    """REPAIR_TRANSPORT_RETRIES (default 2, clamped 0..5; garbage -> 2; 0 = the legacy single attempt), read per call.
    One transient OSError cost a Wano episode a line."""
    return env_int("REPAIR_TRANSPORT_RETRIES", 2, lo=0, hi=5)


def _is_transport_error(e):
    """A failure known to happen BEFORE transmission started: connection refused, DNS, a connect timeout, a reset while
    connecting (``_post_json`` sets ``e.not_sent``). A failure once sending has begun is ambiguous (the server may hold the
    body), and so are a read timeout, RemoteDisconnected and IncompleteRead: a provider is usually still generating (and
    billing) the request, so re-sending would pay twice. Not an HTTP answer (_HttpError), not the request-deadline watchdog,
    not a body that parsed badly."""
    if isinstance(e, _HttpError) or not getattr(e, "not_sent", False):
        return False
    if isinstance(e, TimeoutError) and str(e).startswith("request deadline"):
        return False
    return isinstance(e, (OSError, http.client.HTTPException))


def _post_with_transport_retries(url, body, headers, posts_left=None):
    """_post_json, retried on a transport error (see _is_transport_error) up to REPAIR_TRANSPORT_RETRIES times with a short
    backoff (0.5 s, 1 s, ...), the backoff spent from REPAIR_RETRY_SLEEP_BUDGET like the status retries. ``posts_left`` caps the
    POSTs of this call (llm_openai passes what its REPAIR_OPENAI_RETRIES allowance has left, so the two layers never multiply).
    An HTTP answer (4xx/5xx, including 429) is raised at once: llm_openai's own status retry owns those. The POSTs made are
    left in ``_last_posts`` (also when it raises)."""
    global _TRANSPORT_RETRIES_TOTAL, _last_posts
    tries = _transport_retries()
    if posts_left is not None:
        tries = min(tries, max(0, posts_left - 1))
    _last_posts = 0
    for k in range(tries + 1):
        _last_posts += 1
        try:
            return _post_json(url, body, headers=headers)
        except Exception as e:  # noqa: BLE001 -- classified below, re-raised unchanged when not ours
            wait = 0.5 * 2**k
            if (
                k < tries
                and _is_transport_error(e)
                and not stop_requested()
                and not _deadline_passed()
                and (_retry_budget_left is None or wait <= _retry_budget_left)
            ):
                _TRANSPORT_RETRIES_TOTAL += 1
                log(f"  llm retry {k + 1}/{tries} after {type(e).__name__} (request not sent)")
                _retry_sleep(wait)
                continue
            raise


_last_posts = 0  # POSTs made by the last _post_with_transport_retries call


def llm_openai(prompt, model):
    """Any OpenAI-compatible chat API (OpenRouter, Kilo, CommandCode, NVIDIA, Cerebras, ...).

    Only choices[0].message.content is read; reasoning_content is ignored on purpose (some
    models put their monologue there and the answer in content). Empty content means "no
    repair". The key is looked up by NAME at call time and only the name is ever logged.
    The explicit User-Agent matters: CommandCode's Cloudflare 403s Python's default one.
    No chat_template_kwargs -- that is llama.cpp-only; use REPAIR_EXTRA_BODY for provider flags."""
    global _last_reject
    _last_reject = None
    raw_key = os.environ.get(OPENAI_KEY_ENV, "") if OPENAI_KEY_ENV else ""
    key_name = OPENAI_KEY_ENV or "REPAIR_OPENAI_KEY_ENV"
    if not OPENAI_URL or not raw_key.strip():
        log(f"  llm fail: REPAIR_OPENAI_URL or the key env var {key_name} is not set")
        return LLM_UNREACHABLE
    key = clean_api_key(raw_key)
    if key is None:
        log(f"  llm fail: the key in env var {key_name} contains spaces or control characters (CRLF .env?)")
        return LLM_UNREACHABLE
    try:
        extra = _parse_extra_body(os.environ.get("REPAIR_EXTRA_BODY", ""))
    except ValueError:
        _log_once("extra-body", "  llm fail: REPAIR_EXTRA_BODY is not a valid JSON object")  # name only, never the content
        return LLM_UNREACHABLE
    body = {
        "temperature": 0,
        "max_tokens": OPENAI_MAX_TOKENS,
        **extra,
        "model": model or MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {"Authorization": f"Bearer {key}", "User-Agent": "DubTitlerr/repair"}
    retries = _openai_retries()
    posts = 0  # POSTs sent for this line, transport retries included: never more than retries + 1
    for attempt in range(retries + 1):
        if attempt and stop_requested():
            return LLM_UNREACHABLE  # soft stop during the backoff: the between-target check ends the episode
        try:
            try:
                answer = _post_with_transport_retries(OPENAI_URL, body, headers, retries + 1 - posts)
            finally:
                posts += _last_posts
            choice = answer["choices"][0]
            out = (choice["message"].get("content") or "").strip()
            if not out and choice.get("finish_reason") == "length":
                log(
                    "  llm fail: truncated (finish_reason=length): raise REPAIR_MAX_TOKENS"
                    " or disable reasoning via REPAIR_EXTRA_BODY"
                )
                return LLM_UNREACHABLE
            return out.splitlines()[0].strip().strip('"').strip() if out else ""
        except _HttpError as e:
            if _client_rejection(e):
                return ""
            # Rate limits and server errors are worth another try; other 4xx (bad key, bad model) are not.
            if (e.status == 429 or e.status >= 500) and attempt < retries and posts < retries + 1:
                if stop_requested() or _deadline_passed():
                    log(f"  llm fail: HTTP {e.status} (retry skipped: soft stop or episode deadline)")
                    return LLM_UNREACHABLE
                wait = _retry_wait(e.retry_after, attempt)
                if _retry_budget_left is None or wait <= _retry_budget_left:
                    log(f"  llm retry {attempt + 1}/{retries} after HTTP {e.status}")
                    _retry_sleep(wait)
                    continue
                # The episode's retry-sleep budget is spent: this target keeps its first attempt only.
                _log_once("retry-budget", "  llm: retry sleep budget spent for this episode (REPAIR_RETRY_SLEEP_BUDGET)")
            # Never log str(e): it carries the response body, and a provider may echo the key there.
            log(f"  llm fail: HTTP {e.status}")
            return LLM_UNREACHABLE
        except Exception as e:
            # Nor here: http.client quotes the header value (the key) in its ValueError. Class name only.
            log(f"  llm fail: {type(e).__name__}")
            return LLM_UNREACHABLE
    return LLM_UNREACHABLE  # unreachable: the last attempt always returns above


def llm(prompt, model=None):
    """Dispatch to the backend configured by REPAIR_BACKEND (ollama|llamacpp|openai, default
    llamacpp). model=None uses the backend's default
    (REPAIR_MODEL); pass it explicitly for the two-pass secondary-model re-check (A3)."""
    if REPAIR_BACKEND == "llamacpp":
        return llm_llamacpp(prompt, model or MODEL)
    if REPAIR_BACKEND == "openai":
        return llm_openai(prompt, model)
    return llm_ollama(prompt, model)


def _needs_secondary_check(orig, new, gloss):
    """A3 two-pass trigger: the first-pass repair looks divergent enough to re-verify with
    the (usually stronger/slower) secondary model — either the length changed a lot, or a
    glossary name showed up in the output that wasn't in the original line. NOTE (spec
    correction): the name-appeared condition fires on ~every successful name repair by
    design — inserting the correct name IS the point of repair — so this is "re-verify all
    name-changing repairs," not a rare-case optimization."""
    ratio = len(new) / max(1, len(orig))
    if ratio < 0.6 or ratio > 1.5:
        return True
    for name in gloss["names"]:
        pat = r"\b" + re.escape(name) + r"\b"
        if re.search(pat, new, re.I) and not re.search(pat, orig, re.I):
            return True
    return False


def _p95(values):
    """Nearest-rank 95th percentile; no numpy dependency for one summary stat (A10)."""
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, round(0.95 * (len(s) - 1)))]


def apply_human_text(c, store, stem, words_doc=None):
    """A card the repair loop is about to SKIP: ship the human's wording if one is stored.

    `decisions.lookup` sits further down the loop and needs both sides of the pair, so a card
    that skips -- no fansub anchor, or `llm()` returned "" on a transport failure -- never
    reaches it. `process` then rebuilds the srt from conf.json, replacing a reviewer's typed
    correction with raw ASR. `decisions.corrected_text` answers on the orig alone, which is
    safe for `correct` and only for it.

    Returns the summary bucket this card belongs in, or None when nothing was stored and the
    caller keeps its own. "owed" is the outcome that must never be silent again: a human had
    ruled on the line, and this path could not act on it.

    `force` is rescued here too, via `decisions.forced_text`. It is the verdict a reviewer
    escalates to precisely because the automated checks would refuse the line, so losing it
    on a skipped card is the worst version of this bug, not a lesser one -- measured on
    MARRIAGETOXIN S01E10, where every forced verdict on a skipped card shipped raw ASR.
    `accept` is deliberately NOT rescued: it endorses the MODEL's wording for a proposal
    this card no longer has, which is the case `corrected_text`'s docstring rules out.

    fits_card is NOT bypassed. C1 keeps card timing immutable for humans too, exactly as it
    does for the verdict path below."""
    if not DECISIONS_APPLY:
        return None
    text = decisions.corrected_text(store, c["text"]) or decisions.forced_text(store, c["text"])
    if text:
        if not fits_card(text, c["end"] - c["start"], c["text"]):
            cw = card_split.card_words(words_doc, c["start"], c["end"])
            split = card_split.find_legal_split(text, c["start"], c["end"], cw)
            if split is None:
                unresolved.record(stem, "repair", "verdict_unfittable", original_text=c["text"], proposed_text=text)
                return "unfittable"
            c["_split"] = split
        c["text"] = text
        return "rescued"
    if decisions.for_orig(store, c["text"]):
        unresolved.record(stem, "repair", "verdict_owed", original_text=c["text"])
        return "owed"
    return None


def prior_repairs(stem):
    """How many repairs the LAST run of this episode shipped, from the summary it left.

    The summary survives the mux (mux.py removes the srt/ass sidecars, not this), so it is
    the durable record of whether an episode already carries repaired text."""
    try:
        with open(stem + ".dubtitles.repair-summary.json") as f:
            return int(json.load(f).get("repaired", 0))
    except Exception:
        return 0


def process(conf_path):
    """Repair one episode. Wraps the work so the per-episode retry-sleep budget (REPAIR_RETRY_SLEEP_BUDGET
    seconds, default 600) starts full for this episode and is lifted again afterwards."""
    global _retry_budget_left, _episode_deadline_at, _episode_started_at, _episode_limit_s
    _retry_budget_left = float(env_int("REPAIR_RETRY_SLEEP_BUDGET", 600, lo=0))
    limit = env_int("REPAIR_EPISODE_DEADLINE", 3600, lo=0)  # 0 disables
    _episode_started_at, _episode_limit_s = time.monotonic(), limit
    _episode_deadline_at = _episode_started_at + limit if limit else None
    try:
        return _process_episode(conf_path)
    finally:
        _retry_budget_left = None
        _episode_deadline_at = None


def _process_episode(conf_path):
    stem = conf_path[: -len(CONF_SUFFIX)]
    srt = stem + SRT_SUFFIX
    video = find_video(stem)
    # No conf.json is a normal state, not an error: tools/recover_dub_srt.py rebuilds the
    # sidecar straight out of the already-muxed track for episodes whose conf was long
    # since cleaned up, and merge_pass.sh calls repair.py unconditionally. That dialogue
    # was already repaired when it was first built, so there is nothing to redo.
    if not video:
        write_stage(stem, "repair", "no-video")
        return "skip"
    if not os.path.exists(srt) or not os.path.exists(conf_path):
        write_stage(stem, "repair", "ok", "no-srt" if not os.path.exists(srt) else "no-conf")
        return "skip"
    conf = json.load(open(conf_path))
    # For card_split's word-alignment path only (see card_split.card_words). None on any episode
    # whose sidecar is missing/stale/version-mismatched -- word-alignment then degrades to
    # the proportional fallback for every card, same as it always has.
    words_doc = read_words(stem)
    gloss = glossary_for(video)
    # A3. glossary_for falls back to a no-op glossary when no <Show>.json resolves, which is
    # the right behaviour -- a missing glossary must never fail an episode. Doing it SILENTLY
    # is what is wrong: a misconfigured GLOSSARY_DIR repairs a whole library with no names at
    # all and nothing anywhere says why. load_dict leaves `show` empty when nothing resolved.
    if not gloss.get("show"):
        log(
            f"  WARNING no glossary resolved for {os.path.basename(stem)} — names will not be corrected."
            " Check GLOSSARY_DIR and that a <Show>.json matches the show directory."
        )
    # S-13: the episode's arc, for weighting the reference spellings. None for most
    # of the library (no season.nfo), which leaves the term order exactly as before.
    arc = glossary.arc_for(video)
    # [S-10]: the episode's own SxxExx, for the episode-tag weighting tier. None for any
    # video with no SxxExx in its filename, which leaves the term order exactly as before.
    episode = ordering.episode_key(video)
    # [S-4] The human rung, read back. Resolved ONCE per episode rather than per card: it is
    # a file read, and the per-card path already pays a network round-trip per LLM call.
    # An absent or unreadable store is {} -- every install that has never reviewed anything.
    store, _ = decisions.decisions_for(video)
    # Pairs this episode's queue ALREADY holds. merge_pass.sh re-runs repair on every sweep
    # while an srt exists, and an episode held by the [S-6] gate never loses its srt (mux
    # stops before removing sidecars, and dub_signs_merge writes no .ass for a dialogue-only
    # episode -- dub_signs_merge.py:126-127). Without this the queue gains another copy of
    # every unreviewed line every MERGE_INTERVAL, and the gate's stall alert -- which reads
    # this file's mtime -- can never fire, because each append refreshes it.
    #
    # ONE read for the whole episode, not a scan per card: unresolved.record is an O(1)
    # append precisely because the array version was O(n^2) I/O over ~86 calls an episode.
    # Matched against EVERY entry, resolved or not -- keying on pending-only would re-append
    # the moment a human resolved one through the --review CLI, which is the same deadlock
    # inverted.
    _queued = unresolved.items(stem)
    queued_pairs = {
        (decisions.key(e.get("original_text", "")), decisions.key(e.get("proposed_text", "")))
        for e in _queued
        if e.get("stage") == "repair_applied"
    }
    # [F-2] Pending entries by ORIGINAL line, so a changed proposal can supersede the one it
    # replaces instead of queueing beside it. The pair is right as the DECISION key -- keying
    # a verdict on `orig` alone would let one rejection suppress the proposal that fixes the
    # line -- but the reviewer's PENDING set is a different question: two live proposals for
    # one card are two questions about a card that will only ever ship one answer, and a
    # verdict on either leaves a gated episode held on the other.
    pending_by_orig: dict = {}
    for i, e in enumerate(_queued):
        if e.get("stage") == "repair_applied" and not e.get("resolved"):
            pending_by_orig.setdefault(decisions.key(e.get("original_text", "")), []).append(
                (i, decisions.key(e.get("proposed_text", "")))
            )
    targets = [(i, c) for i, c in enumerate(conf) if is_target(c, gloss)]
    if not targets:
        return "clean"  # nothing to repair (e.g. S15E01)
    ivals = dialogue_intervals(video)
    audit, fixed, skipped_no_ref, rejected = [], 0, 0, 0
    rec = qc.Recorder()  # S-6 liveness counters, merged into the summary below
    llm_empty = 0
    unreachable = 0
    llm_calls = 0  # targets that actually reached llm(): the denominator of the unreachable guard
    refuse_pct = env_int("REPAIR_UNREACHABLE_REFUSE_PCT", 10, lo=1, hi=100)
    max_streak = env_int("REPAIR_MAX_CONSECUTIVE_UNREACHABLE", 5, lo=1)
    streak = 0  # unreachable targets in a row; any answer (even an empty one) resets it
    deadline_hit = False
    deadline_note = ""
    refuse_why = None  # set when the episode must be refused: what to say in the log
    rejected_4xx = 0  # request-scoped client errors (llm_openai): no repair for that line, not an outage
    rejected_secondary = 0  # C5: second-pass output refused by the gate
    rejected_name_part = 0  # subset of rejected: the repair added or removed a part of a name
    transport_retries_at_start = transport_retries_total()
    dismissed_large_change = 0  # subset of rejected: recorded but kept out of the queue (REPAIR_AUTO_DISMISS_WORDS)
    accepted_punct_case_only = 0  # repairs admitted only by REPAIR_ACCEPT_PUNCT_CASE_ONLY
    rejected_terminal_punct = 0  # subset of rejected: REPAIR_GUARD_TERMINAL_PUNCT refused them
    unreachable_secondary = 0  # the second-pass backend call itself failed (first pass stands)
    # The model returned the line verbatim -- the single most common outcome of this stage
    # (568 of 836 targets on the SAO pass). accept_repair refuses it and the `not admitted`
    # inner guard is false by construction, so before this counter it incremented nothing
    # and recorded nothing: the [S-4] invariant below was stated as fact and was false.
    unchanged = 0
    # [S-4]. Both are terminal `continue` paths, so without their own buckets `targets`
    # would quietly exceed the sum of the others and the residual would be unexplained.
    verdict_reject = 0  # a stored `reject`: settled by a human, nothing shipped
    verdict_rescued = 0  # a SKIPPED card whose stored human text was shipped anyway (A4)
    verdict_owed = 0  # skipped, a human had ruled, and this path could not act on it (A4)
    verdict_unfittable = 0  # an applying verdict refused by fits_card (C1)
    verdict_stale = 0  # the human approved OTHER wording for this line; the model moved on
    repaired_lines = []  # A10: per-line detail for the summary
    for pos, (i, c) in enumerate(targets):
        if _deadline_passed():
            deadline_hit = True
            deadline_note = (
                f"{time.monotonic() - _episode_started_at:.0f}s elapsed (limit {_episode_limit_s}s)"
                f" after {pos} of {len(targets)} targets; raise REPAIR_EPISODE_DEADLINE if the backend is healthy but slow"
            )
            break
        if stop_requested():
            # Soft stop (container_run.sh got SIGTERM): checked between targets, never inside one. The srt
            # is NOT rebuilt -- a half-repaired rebuild would ship raw ASR over shipped repairs -- and the
            # failed `stopped` record makes merge_pass.sh hold the episode back and re-run repair next pass.
            log("  soft stop requested: repair stopped before the srt rewrite, the episode is retried on the next pass")
            write_stage(stem, "repair", "stopped")
            return "stopped"
        # C6: select the reference on the SOURCE window -- where the audio actually was --
        # not the display window, which the timing layer may have stolen forward onto the
        # NEIGHBOUR's cue. The .get fallback keeps every pre-C6 sidecar working unchanged.
        #
        # S-6: unless that window is one whisper got wrong. A 7-second span on a one-word
        # card selects whatever fansub line happens to fall inside it -- possibly a
        # different line entirely -- and the guard then rejects the repair and counts a
        # rejection, recording nothing about the REFERENCE having been wrong. The guard
        # fires BEFORE the .get() below, or it reads the very default it exists to doubt.
        # No reference, not the display window: on 99% of gated cards display == source,
        # so falling back reproduces the window just declared implausible.
        if hallucination.bad_source_window(c, rec=rec):
            ref = ""
        else:
            ref = overlap_ref(ivals, c.get("source_start", c["start"]), c.get("source_end", c["end"]))
        if skips_unanchored(ref, gloss):
            bucket = apply_human_text(c, store, stem, words_doc)
            if bucket == "rescued":
                verdict_rescued += 1
                continue
            if bucket == "unfittable":
                verdict_unfittable += 1
                continue
            if bucket == "owed":
                verdict_owed += 1
                continue
            skipped_no_ref += 1
            # The counter alone made this indistinguishable from "repair ran and found
            # nothing wrong". Record the card so a human can see WHICH lines went unrepaired
            # and judge whether the release simply has no fansub or the anchor logic missed.
            unresolved.record(
                stem,
                "repair",
                "no_reference",
                original_text=c["text"],
                source_start=c.get("source_start", c["start"]),
                source_end=c.get("source_end", c["end"]),
                avg_logprob=c.get("avg_logprob"),
            )
            continue  # see skips_unanchored() for why, and for what opens this path
        prev_text = conf[i - 1]["text"] if i > 0 else ""
        next_text = conf[i + 1]["text"] if i + 1 < len(conf) else ""
        prompt = build_prompt(c["text"], ref, gloss, prev_text, next_text, arc, episode)
        t0, slept0 = time.monotonic(), _retry_slept  # V2 A2: per-call latency
        llm_calls += 1
        _take_reject()
        new = llm(prompt)
        was_rejected = _take_reject() is not None
        latency_ms = round((time.monotonic() - t0 - (_retry_slept - slept0)) * 1000)  # backoff is not model time
        if new:
            new = glossary.correct(new, gloss)[0]  # enforce canonical spelling on output
        # C2: the card's DISPLAY duration -- how long the viewer actually has to read it.
        # (source_start/source_end anchor the EVIDENCE window above; they are not what is
        # on screen.) Timing stays immutable: a repair that does not fit is rejected.
        dur = c["end"] - c["start"]
        if new == LLM_UNREACHABLE:
            # The BACKEND is down, which is a fact about the release, not about this card.
            # A human cannot review "the server was unreachable", and unresolved.record's
            # own docstring says llm_empty carries no proposal and was never a decision --
            # so nothing is queued. The episode-level guard below refuses the rewrite.
            unreachable += 1
            streak += 1
            new = ""
            bucket = apply_human_text(c, store, stem, words_doc)
            if bucket == "rescued":
                verdict_rescued += 1
            elif bucket == "unfittable":
                verdict_unfittable += 1
            elif bucket == "owed":
                verdict_owed += 1
            if streak >= max_streak:
                # A run of consecutive failures is an outage, not a poison pill: stop sending
                # the rest of the episode to a dead backend (and sleeping through retries).
                refuse_why = f"{streak} targets in a row"
                break
            if unreachable * 100 >= refuse_pct * len(targets):
                # llm_calls can never exceed len(targets), so the rate rule below is already decided.
                refuse_why = f"{unreachable} of {len(targets)} targets (threshold {refuse_pct}%)"
                break
            continue
        streak = 0
        if was_rejected:
            rejected_4xx += 1
        if not new:
            bucket = apply_human_text(c, store, stem, words_doc)
            if bucket == "rescued":
                verdict_rescued += 1
                continue
            if bucket == "unfittable":
                verdict_unfittable += 1
                continue
            if bucket == "owed":
                verdict_owed += 1
                continue
            llm_empty += 1
            unresolved.record(
                stem, "repair", "llm_empty", original_text=c["text"], reference=ref[:120], avg_logprob=c.get("avg_logprob")
            )
            continue
        # [S-4] A human already ruled on this exact (original, proposal) pair. Consulted
        # HERE -- after glossary.correct() has canonicalised `new`, before accept_repair
        # judges it -- because the verdict was recorded against the corrected proposal.
        # Placed above the correction it would key on raw model output and miss silently.
        # No `and store` short-circuit: the consult runs whether or not anything is stored,
        # so the path cannot quietly become dead code on the installs where it matters least
        # to test and most to keep working. lookup() on {} returns None off an empty list.
        verdict = decisions.lookup(store, c["text"], new) if DECISIONS_APPLY else None
        ruling = verdict.get("verdict") if verdict else None
        human_text = verdict.get("text", "") if verdict else ""
        if verdict is None and DECISIONS_APPLY:
            # The human APPROVED wording for this original, and the model has since
            # proposed different wording. `lookup` needs both sides, so their approval does
            # not apply here -- and `accept_repair` below will judge the new proposal on its
            # own merits and may well ship it. That is not wrong, but it is invisible: the
            # store still shows the line as settled, and the reviewer is never told that
            # what shipped is not what they approved.
            #
            # Measured 2026-09-02 on MARRIAGETOXIN S01E10, moving REPAIR_MODEL from
            # nanbeige4.2-3b to qwen3-4b-instruct: two approved verdicts were orphaned this
            # way and the log recorded `repair_applied / accepted` for wording the reviewer
            # had never seen. The proposal side of the key is MODEL OUTPUT, so changing the
            # model rewrites the key for every line in the library at once.
            #
            # Only an ORPHANED APPROVAL is recorded. A superseded `reject` is the designed
            # flow -- `lookup`'s docstring exists to stop one rejection suppressing the
            # proposal that fixes the line -- and flagging those would bury this in noise.
            stale = [e for e in decisions.for_orig(store, c["text"]) if e.get("verdict") in APPLYING]
            if stale:
                unresolved.record(
                    stem,
                    "repair",
                    "verdict_stale_proposal",
                    original_text=c["text"],
                    proposed_text=new,
                    approved_text=(stale[-1].get("text") or stale[-1].get("proposed") or ""),
                    model=MODEL,
                    avg_logprob=c.get("avg_logprob"),
                )
                verdict_stale += 1
        if ruling == "reject":
            # Settled: not applied, and NOT re-queued. Re-queueing it would show the
            # reviewer a line they have already ruled on, every run, forever.
            verdict_reject += 1
            continue
        if ruling == "correct":
            new = human_text or new
        # C1, and the exact boundary of what a human verdict may overrule. Every verdict in
        # APPLYING bypasses accept_repair -- its length band and borrow limit are
        # heuristics standing in for a reader who is now present -- but NONE bypasses
        # fits_card, which is not judgement: it is whether the line can be on screen for
        # the seconds the card lasts. There is no verdict that admits an unrenderable line.
        # `c["text"]` as `orig` keeps the existing already-over-cps allowance, so a human
        # editing a card that was always too fast is not what this refuses.
        if ruling in APPLYING and not fits_card(new, dur, c["text"]):
            # A single cue can't hold it -- try a legal split before refusing outright.
            # over_line_len/over_chars can split cleanly; over_cps cannot (a proportional
            # split holds cps constant across both halves by construction, so a card
            # already too fast stays too fast either way) and correctly finds none.
            cw = card_split.card_words(words_doc, c["start"], c["end"])
            split = card_split.find_legal_split(new, c["start"], c["end"], cw)
            if split is None:
                # Refused, and SAID SO. A verdict that vanishes silently is the failure this
                # whole loop exists to prevent -- the reviewer would believe the line settled.
                unresolved.record(
                    stem,
                    "repair",
                    "decision_unfittable",
                    original_text=c["text"],
                    proposed_text=new,
                    avg_logprob=c.get("avg_logprob"),
                )
                verdict_unfittable += 1
                continue
            c["_split"] = split
        # Every applying verdict is admitted here, so `not admitted` below can only be
        # reached with no ruling at all -- which is why that branch needs no ruling guard of
        # its own to avoid re-queueing a settled line.
        admitted = ruling in APPLYING or accept_repair(c["text"], new, ref, dur, gloss, prev_text)
        if (
            admitted
            and ruling not in APPLYING
            and _accept_punct_case_only()
            and is_punct_case_only(c["text"], new, gloss, prev_text)
            and rejecting_guard(c["text"], new, ref, dur, gloss, punct_case_ok=False) is not None
        ):
            accepted_punct_case_only += 1  # admitted only because of REPAIR_ACCEPT_PUNCT_CASE_ONLY
        if not admitted:
            if new and new.lower() != c["text"].lower():
                rejected += 1  # surfaced in the summary so the guard stays visible
                # ...but the PROPOSAL was discarded, and it is the whole evidence a human
                # needs to judge whether the guard was right or overzealous.
                if invents_name(c["text"], new, gloss):
                    reason = "rejected_name_invented"
                elif _keep_name_parts() and changes_name_parts(c["text"], new, gloss):
                    reason = "rejected_name_part"
                    rejected_name_part += 1
                else:
                    reason = "rejected_guard"
                dismissed_fields = unresolved.dismissal(c["text"], new)
                dismissed_large_change += bool(dismissed_fields)
                guard_name = rejecting_guard(c["text"], new, ref, dur, gloss, prev_text=prev_text)
                rejected_terminal_punct += guard_name == "terminal_punct"
                unresolved.record(
                    stem,
                    "repair",
                    reason,
                    original_text=c["text"],
                    proposed_text=new,
                    reference=ref[:120],
                    avg_logprob=c.get("avg_logprob"),
                    guard=guard_name,
                    **dismissed_fields,
                )
            else:
                # `new` is non-empty (the `if not new` above returned), so this is exactly
                # the verbatim echo. NOT queued: there is no proposal for a human to judge,
                # and queueing every unrepaired line would flood the review page.
                unchanged += 1
        else:
            # A3: re-verify divergent-looking repairs (esp. name changes) with the secondary
            # model. No-op by default (REPAIR_MODEL_SECONDARY == REPAIR_MODEL).
            #
            # NOT when a human has ruled. C5 says "a stronger model is still a model"; a
            # human is not, and outranks both passes. Without `not ruling` this block
            # reassigns `new` AFTER the consult, so an accept/correct/force would be
            # admitted and then quietly replaced by the second model's wording -- and the
            # suppression below would write no queue entry, because the line counts as
            # settled. The substitution would reach the viewer with nothing recording it.
            # (not once the episode deadline has passed: that bounds the overrun to one request)
            wants_second = MODEL_SECONDARY != MODEL and not _deadline_passed()
            if not ruling and wants_second and _needs_secondary_check(c["text"], new, gloss):
                t1, slept1 = time.monotonic(), _retry_slept
                new2 = llm(prompt, model=MODEL_SECONDARY)
                latency_ms += round((time.monotonic() - t1 - (_retry_slept - slept1)) * 1000)
                if new2 == LLM_UNREACHABLE:
                    # The marker is truthy text, not an answer: never gate it. The first-pass
                    # repair stands, as for any second pass that does not verify.
                    unreachable_secondary += 1
                    new2 = ""
                if new2:
                    new2 = glossary.correct(new2, gloss)[0]
                    # C5: a stronger model is still a model. Its output went straight over
                    # the first pass with no validation at all -- same gate, same card. When
                    # it fails, the already-accepted first-pass repair stands rather than the
                    # card being left garbled.
                    if new2 and accept_repair(c["text"], new2, ref, dur, gloss, prev_text):
                        new = new2
                    elif new2 and new2.lower() != new.lower():
                        rejected_secondary += 1
            audit.append((c["text"], new, ref[:80], latency_ms))
            repaired_lines.append({"orig": c["text"], "repaired": new, "ref": ref[:80], "latency_ms": latency_ms})
            # The human rung of the ladder, for the branch that had none. accept_repair
            # ADMITTED this repair and its own docstring says nothing below it checked the
            # meaning -- `factory -> needle` passes every gate. So the admitted line is
            # queued for the one reviewer who can judge it.
            #
            # MUST stay above `c["text"] = new`. Below the assignment, `original_text` would
            # be the REPAIRED text and every entry would compare a line against itself --
            # a queue that always looks unanimous.
            #
            # Also below the secondary-model block above, so `new` is the text actually
            # applied rather than the first pass's proposal.
            # ...unless a human already ruled on it. [S-4]: an accept/correct/force verdict
            # means this line is SETTLED, and re-queueing a settled line would hand the
            # reviewer their own decision back on every subsequent run. That is the re-run
            # amplification the spec records under Edge cases, and the pair being the
            # store's key is what lets it be suppressed here rather than deduplicated in
            # unresolved.record(), whose O(1) append is deliberate.
            pair = (decisions.key(c["text"]), decisions.key(new))
            if not ruling and pair not in queued_pairs:
                # Retire any live entry for this same line whose proposal has changed. Marked
                # RESOLVED, never deleted: the queue is the audit trail, and what the model
                # proposed before is the evidence for whether the gate is drifting.
                # No "is it different?" check: an IDENTICAL pair never reaches here, because
                # `pair not in queued_pairs` above already skipped it, and queued_pairs is
                # built from every entry including the pending ones. Any live entry for this
                # original therefore carries a different proposal by construction.
                for idx_old, _ in pending_by_orig.get(pair[0], []):
                    unresolved.resolve(stem, idx_old, accept=False, note=f"superseded by a newer proposal: {new}")
                pending_by_orig[pair[0]] = [(len(_queued), pair[1])]
                _queued.append({})  # keep index accounting honest for a second supersession
                queued_pairs.add(pair)
                unresolved.record(
                    stem,
                    "repair_applied",
                    "accepted",
                    original_text=c["text"],
                    proposed_text=new,
                    reference=ref[:120] or None,
                    avg_logprob=c.get("avg_logprob"),
                )
            c["text"] = new
            fixed += 1
    # A2 guard (c). This function REBUILDS the srt from conf.json unconditionally, so a run
    # that repaired nothing because every target was refused for want of an anchor writes RAW
    # ASR over whatever was already shipped. Reproduced on One Pace S31E24 (targets=144
    # repaired=0 skipped_no_ref=144), which came back as `our mods will never give up There's
    # a` where the shipped track had `Our mods will never give up. There's a fire...`.
    #
    # Refusing is deliberately narrow: it fires only when EVERY target was skipped for want of
    # a reference AND the last run shipped repairs. An episode that genuinely has nothing to
    # fix still rewrites normally, and the first run of a new episode has no prior summary.
    # Refuse when the backend was down for REPAIR_UNREACHABLE_REFUSE_PCT percent or more of the targets
    # that actually reached llm() (cards skipped for want of a fansub line never asked it anything), or
    # when it failed REPAIR_MAX_CONSECUTIVE_UNREACHABLE targets in a row. Repairs live only in the srt,
    # so a rebuild after a partial outage would overwrite shipped repairs with raw ASR. A single
    # poison-pill line (a few percent) still ships.
    if refuse_why is None and not deadline_hit and llm_calls and unreachable * 100 >= refuse_pct * llm_calls:
        refuse_why = f"{unreachable} of {llm_calls} targets that reached it (threshold {refuse_pct}%)"
    if deadline_hit:
        problem = f"episode deadline exceeded: {deadline_note}"
    elif refuse_why is not None:
        problem = f"the repair backend was unreachable for {refuse_why}"
    elif llm_calls >= 1 and rejected_4xx == llm_calls:
        # Every request that reached the model came back a client error: that is a wrong model id or URL,
        # at any episode size (a tiny episode would otherwise be rebuilt as raw ASR over shipped repairs).
        # One bad line among several answered ones is not this: it ships.
        problem = "every request was rejected with a client error: check the model id and URL"
    else:
        problem = None
    if problem:
        log(
            f"  REFUSED {os.path.basename(stem)}: {problem}."
            " Rebuilding the srt would overwrite the shipped text with"
            " raw ASR, and a dead endpoint is not a review item, so nothing was queued."
            " Check REPAIR_LLAMACPP_URL / REPAIR_BACKEND and re-run."
        )
        write_stage(stem, "repair", "backend-unreachable")
        return "refused"
    if targets and fixed == 0 and skipped_no_ref == len(targets) and prior_repairs(stem) > 0:
        log(
            f"  REFUSED {os.path.basename(stem)}: every one of {len(targets)} targets was skipped for want of a"
            f" fansub anchor, but the last run shipped {prior_repairs(stem)} repairs. Rebuilding the srt would"
            " overwrite them with raw ASR. Declare `unanchored_repair` in this show's glossary if its copies"
            " carry no English subtitles for the Japanese audio."
        )
        write_stage(stem, "repair", "refused", "prior-repairs")
        return "refused"
    # rewrite srt from (possibly repaired) conf rows. conf.json stores text FLATTENED
    # (generate.py replaces '\n' with ' '), so re-wrap here or every episode that
    # passes through repair ships as unwrapped single lines -- which is exactly what
    # the library did until this fix.
    srt_out = out_for(srt)
    rep_out = out_for(stem + ".dubtitles.repair.csv")

    def _render_srt(f):
        i = 0
        for c in conf:
            # `_split` is set ONLY by the card_split path above and never written back to
            # conf.json -- it is a transient in-memory marker for this run's write, not a
            # durable card shape. Two cues here, one there; conf.json stays one row either
            # way (.procoder/todo/20260829-split-a-card-so-a-human-correction-fits.md).
            for p in c.get("_split") or ({"start": c["start"], "end": c["end"], "text": c["text"]},):
                i += 1
                f.write(f"{i}\n{ts_srt(p['start'])} --> {ts_srt(p['end'])}\n{reflow.wrap_balance(p['text'])}\n\n")

    def _render_csv(f):
        w = csv.writer(f)
        w.writerow(["orig", "repaired", "ref", "latency_ms"])
        w.writerows(audit)

    # Atomic: a crash mid-write must not truncate the shipped srt (SKIP_IF_SRT reads a
    # truncated file as a finished episode) or the audit csv.
    atomic_write(srt_out, _render_srt)
    atomic_write(rep_out, _render_csv, newline="")
    # A10: per-show repair summary, written alongside the srt/csv
    lat_values = [r["latency_ms"] for r in repaired_lines]
    summary = {
        "targets": len(targets),
        "repaired": fixed,
        "skipped_no_ref": skipped_no_ref,
        "llm_empty": llm_empty,
        "unreachable": unreachable,
        "rejected_4xx": rejected_4xx,  # subset of llm_empty: the provider rejected that one request
        "rejected_guard": rejected,  # model proposed an edit, accept_repair() refused it
        "rejected_name_part": rejected_name_part,  # subset of rejected_guard: it added/removed a name part
        **({"dismissed_large_change": dismissed_large_change} if unresolved.auto_dismiss_threshold() is not None else {}),
        **({"accepted_punct_case_only": accepted_punct_case_only} if _accept_punct_case_only() else {}),
        **({"rejected_terminal_punct": rejected_terminal_punct} if _guard_terminal_punct() else {}),
        **({"transport_retries": transport_retries_total() - transport_retries_at_start} if _transport_retries() else {}),
        "unreachable_secondary": unreachable_secondary,
        "rejected_secondary": rejected_secondary,  # C5: second pass refused, first pass kept
        "unchanged": unchanged,  # model echoed the line back; nothing proposed, nothing shipped
        # [S-4]. targets == repaired + skipped_no_ref + llm_empty + rejected_guard +
        # verdict_reject + verdict_unfittable + verdict_rescued + verdict_owed + unchanged,
        # for every episode. `unchanged`
        # was missing until 2026-08-29 and it is the LARGEST bucket, so the identity this
        # comment asserts was false everywhere it was read. Pinned by
        # test_every_target_lands_in_exactly_one_summary_bucket -- add an outcome to the
        # loop without a bucket here and that test fails.
        "verdict_reject": verdict_reject,  # human said no; ASR text stands
        "verdict_rescued": verdict_rescued,  # skipped, but the human's stored text shipped (A4)
        "verdict_owed": verdict_owed,  # skipped while a human verdict existed and could not be applied (A4)
        "verdict_unfittable": verdict_unfittable,  # human's text cannot be rendered (C1)
        # An approval orphaned by the model proposing different wording for the same line.
        # Non-zero after a REPAIR_MODEL change is expected, not alarming -- it is the count
        # of decisions the reviewer needs to look at again.
        "verdict_stale_proposal": verdict_stale,
        "mean_latency_ms": round(sum(lat_values) / len(lat_values)) if lat_values else 0,
        "p95_latency_ms": round(_p95(lat_values)) if lat_values else 0,
        "model": MODEL,
        "model_secondary": MODEL_SECONDARY,
        # evaluated>0 with activated==0 across a season is the dead-rule signal. Carried
        # here because repair writes its own summary rather than a qc sidecar.
        "rules": dict(rec.counters),
        "repaired_lines": repaired_lines,
    }
    summary_out = out_for(stem + ".dubtitles.repair-summary.json")
    atomic_write(summary_out, lambda f: json.dump(summary, f, indent=2))
    for p in (srt_out, rep_out, summary_out):
        try:
            os.chown(p, MEDIA_UID, MEDIA_GID)
        except OSError as e:
            log(f"chown failed for {p}: {e}")
    # A3. The beta-user shape: dub-only copies, `unanchored_repair` never declared, and no
    # prior repairs -- so guard (c) above cannot fire, since it only protects work that
    # already exists. Every card is skipped and, until this line, the only trace was a
    # skipped_no_ref count inside a JSON sidecar nobody opens. The message names the remedy:
    # a user who does not know the setting exists cannot act on "144 targets skipped".
    if targets and fixed == 0 and skipped_no_ref == len(targets):
        log(
            f"  WARNING every one of {len(targets)} targets on {os.path.basename(stem)} was skipped for want of a"
            " reference — this release has no English subtitles for the Japanese audio, so there is nothing to"
            ' anchor a repair on. Set "unanchored_repair": true in this show\'s glossary to repair from the'
            " glossary alone (wider guesses, fewer missed names), or leave it off to ship the ASR text as-is."
        )
    log(f"  targets={len(targets)} repaired={fixed}")
    write_stage(stem, "repair", "ok", f"repaired={fixed},targets={len(targets)}")
    return "repaired"


def main():
    args = sys.argv[1:]
    confs = list(args) if args else []  # explicit .conf.json paths, else walk roots
    if not confs:
        for root in ROOTS:
            if not os.path.isdir(root):
                continue
            for dp, _, files in os.walk(root):
                for f in files:
                    if f.endswith(CONF_SUFFIX):
                        confs.append(os.path.join(dp, f))
    counts = {}
    for cp in sorted(confs):
        res = process(cp)
        counts[res] = counts.get(res, 0) + 1
        log(f"{res}: {os.path.basename(cp)}")
        if res == "stopped":
            break  # soft stop: start no further episode
    log("SUMMARY", counts)


if __name__ == "__main__":
    main()
