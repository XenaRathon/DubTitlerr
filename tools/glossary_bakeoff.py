#!/usr/bin/env python3
"""Glossary-stage bake-off, phase 1: build the offline item set.

Two glossary stages ask a local LLM one small question per term: `glossary_verify.adjudicate` (which
wiki title is the same entity as this mined term) and `glossary_acquire.adjudicate_merge` (are these two
spellings one entity). This tool turns a COPY of the glossaries, the acquire caches and the wiki title
caches into `items.jsonl`, the fixed question set a later `run` / `score` will put to other models. See
specs/glossary-decision-bakeoff/spec.md.

  python3 tools/glossary_bakeoff.py build-set --glossaries DIR --wiki-cache DIR --out items.jsonl [--show TEXT ...]
  python3 tools/glossary_bakeoff.py run --items items.jsonl --arm NAME --out results/NAME.jsonl
        [--stage verify|acquire|both] [--only gold|all|nocall] [--sample N --seed S] [--limit N]
        [--reverse] [--delay S] [--retry-errors]

Offline by construction: no network, no model, no production module changed. The candidate list of every
verify item is recomputed with the production `glossary_verify.candidates` (TOPK 6, cutoff 0.62), so what a
model is asked is what production would have asked.

What the set is: what `glossary_verify.verify --force` would send, computed from an OFFLINE SNAPSHOT of the
glossaries and wiki caches. It is not a list of what production would ask tonight. Production (`verify`)
adjudicates `pending_terms(gloss)`, the names and phrases not yet in `verified`; a live glossary has mostly been
verified already, so the set takes ALL names and phrases and says per item whether production would still ask:
`would_ask` is true only for an unverified term of a show that production would not refuse as a wiki mismatch,
and `wiki_cache_stale` says production would refetch the titles (cache older than its refresh rule as of
--as-of, default the freshest cache in the snapshot, or a pinned wiki that differs from the cached api), so the
candidates could differ. A term with no candidates is kept with `no_call: true`: production returns "none"
for it without a model call, so it is a control, not a question.

Gold, only for shows with `_curated` true, and only where the label is not a guess. A candidate is gold when
  * `exact`: its title equals the term (casefolded); or
  * `expansion`: `glossary_acquire.is_expansion(term, title)` holds AND the title is itself one of the glossary's
    names/phrases (the same entity written longer; `incumbent_derived` is set when the term is in `verified`,
    because the incumbent model may have written that name itself).
A respelling or another character that merely shares letters is never gold, and hard_fixes targets are not a
source. If more than one candidate qualifies there is no gold: `gold` null, `gold_ambiguous` true, no tie-break.
Respelling cases are left to the spec's human-review queue.

Synthetic negatives. From every item whose gold is `exact`, an extra item `verify-neg:{show}:{term}` with
`negative: true`, `gold: "none"` and the source's candidates minus the exact title and minus every remaining
candidate that is an expansion of the term (otherwise a leftover 'Monkey D. Luffy' would make "none" wrong).
Survivors keep production order and scores; a negative left with no candidate is dropped.

Acquire items are the cached pairs of `<show>.acquire-cache.json`: the two spellings and the local model's
historical verdict. The transcript quotes are not available offline, so `quotes` is null.

Re-running on the same input gives byte-identical output.

`run` puts the items to ONE arm (see ARMS) and appends one row per (item, arm, order) to a results file:
id, arm, order ("fwd" | "rev"), raw, parsed, latency_s, usage, error (+ local: true for no-call controls).
  * the PRODUCTION prompt builders and parsers are used (glossary_verify.build_adjudication_prompt /
    parse_adjudication via adjudicate; glossary_acquire.build_merge_prompt and the parse inside
    adjudicate_merge), by routing each arm through the production function with its llm_chat swapped for the
    arm's transport; so parsing quality is part of what is measured;
  * a failure is a row with `error` set and parsed null: never a guessed pick. Only an exception's CLASS or an
    HTTP status is recorded, never its text (http.client quotes header values);
  * resumable: a (id, arm, order) already present without error is skipped; errored rows are skipped too
    unless --retry-errors (the retry appends a new row; the latest row for a key wins at score time);
  * no-call controls (zero candidates) are answered locally by the production rule and sent nowhere;
  * the confidence threshold of the decision arms is NOT applied here: tau is swept at score time.
PRIVACY: a third-party arm receives, for verify items, only the show title, the mined term and the wiki candidate
titles; for acquire items it receives the two spellings and the transcript quotes, so acquire items without
quotes are not sent to third-party arms. The first line printed says exactly this."""

from __future__ import annotations

import argparse
import contextlib
import difflib
import json
import os
import random
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field

sys.path.insert(0, ".")
import acquire_cache  # noqa: E402
import common  # noqa: E402
import glossary_acquire  # noqa: E402
import glossary_verify  # noqa: E402
import repair  # noqa: E402
import tools.bakeoff as bakeoff  # noqa: E402
import tools.decision_client as decision_client  # noqa: E402

LASTRUN = ".lastrun.json"
GLOSSARY_GLOB_EXCLUDE = (LASTRUN, acquire_cache.SUFFIX)


def _delay_seconds(raw):
    """argparse type: a finite, non-negative number of seconds."""
    try:
        value = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a number of seconds") from None
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        raise argparse.ArgumentTypeError(f"{raw!r} must be a finite number of seconds, 0 or more")
    return value


def _read_json(path):
    """(object, None) or (None, reason). Never raises on bad data."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except (OSError, ValueError) as e:
        return None, f"unreadable ({type(e).__name__})"
    if not text.strip():
        return None, "empty file"
    try:
        return json.loads(text), None
    except ValueError:
        return None, "malformed JSON"


def wiki_cache_path(wiki_dir, show):
    """Where `glossary_verify.fetch_titles` keeps a show's title list. That function has no separate mapping
    helper (the rule sits inline, and a miss or a stale entry would go to the network), so the one regex is
    mirrored here; a test proves the production reader finds the file this path names."""
    return os.path.join(wiki_dir, re.sub(r"[^A-Za-z0-9]+", "_", show) + ".json")


def _score(term, title):
    """difflib's ratio exactly as get_close_matches computes it (a = candidate, b = the word)."""
    return round(difflib.SequenceMatcher(None, title.lower(), term.lower()).ratio(), 4)


def _glossary_files(gloss_dir):
    names = (f for f in os.listdir(gloss_dir) if f.endswith(".json") and not f.endswith(GLOSSARY_GLOB_EXCLUDE))
    return sorted(f for f in names if os.path.isfile(os.path.join(gloss_dir, f)))


def _gold(term, cand_titles, gloss):
    """(gold title, kind, ambiguous) for a curated glossary, else (None, None, False). See the module docstring."""
    if not gloss.get("_curated"):
        return None, None, False
    members = {x.casefold() for x in [*gloss.get("names", []), *gloss.get("phrases", [])] if isinstance(x, str)}
    qualifying = []
    for title in cand_titles:
        if title.casefold() == term.casefold():
            qualifying.append((title, "exact"))
        elif title.casefold() in members and glossary_acquire.is_expansion(term, title):
            qualifying.append((title, "expansion"))
    if not qualifying:
        return None, None, False
    if len(qualifying) > 1:
        return None, None, True
    return qualifying[0][0], qualifying[0][1], False


def _wiki_mismatch(gloss, titles):
    """glossary_verify.verify's sanity gate (it is inline there, so mirrored): an auto-resolved wiki is refused
    when none of the glossary's known names is a title on it. A pinned `wiki` skips the gate."""
    names = gloss.get("names", [])
    if gloss.get("wiki") or len(names) < 3:
        return False
    tl = {t.lower() for t in titles}
    return not any(n.lower() in tl for n in names)


def _wiki_stale(doc, as_of, gloss):
    """Would fetch_titles refetch? Its rule: cached api differs from the resolved one, or the cache is at least
    WIKI_TTL old. The resolved api is known offline only for a pinned wiki."""
    fetched = doc.get("fetched_at")
    fetched = fetched if isinstance(fetched, (int, float)) and not isinstance(fetched, bool) else 0
    pinned = gloss.get("wiki")
    if isinstance(pinned, str) and pinned and doc.get("api") != glossary_verify.normalize_api(pinned):
        return True
    return as_of - fetched >= glossary_verify.WIKI_TTL


def _snapshot_time(wiki_dir):
    """The freshest fetched_at among the wiki caches: 'now' as the snapshot saw it, so the set does not depend on
    the day it is rebuilt."""
    best = 0.0
    for f in sorted(os.listdir(wiki_dir)):
        if f.endswith(".json"):
            doc, err = _read_json(os.path.join(wiki_dir, f))
            v = doc.get("fetched_at") if not err and isinstance(doc, dict) else None
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                best = max(best, float(v))
    return best


def verify_items(gloss, show, titles, stale=False):
    """One item per name/phrase, candidates from the PRODUCTION function in production order, each followed by its
    synthetic negative when it has one."""
    names, phrases = gloss.get("names", []), gloss.get("phrases", [])
    verified = set(gloss.get("verified", []) if isinstance(gloss.get("verified"), list) else [])
    flagged = gloss.get("flagged") if isinstance(gloss.get("flagged"), dict) else {}
    acquired = gloss.get("acquired") or ()
    items = []
    mismatch = _wiki_mismatch(gloss, titles)
    # pending_terms with nothing verified == names then phrases, deduplicated: what `verify --force` sends.
    for term in glossary_verify.pending_terms({"names": names, "phrases": phrases}):
        cand_titles = glossary_verify.candidates(term, titles)
        gold, kind, ambiguous = _gold(term, cand_titles, gloss)
        item = {
            "id": f"verify:{show}:{term}",
            "stage": "verify",
            "show": show,
            "term": term,
            "list": "names" if term in names else "phrases",
            "verified": term in verified,
            "flagged": flagged.get(term),
            "acquired": term in acquired,
            "candidates": [{"title": t, "score": _score(term, t)} for t in cand_titles],
            "no_call": not cand_titles,
            "would_ask": term not in verified and not mismatch,
            "wiki_cache_stale": stale,
            "gold": gold,
        }
        if gold is not None:
            item["gold_source"] = "curated"
            item["gold_kind"] = kind
            item["incumbent_derived"] = kind == "expansion" and term in verified
        elif ambiguous:
            item["gold_ambiguous"] = True
        items.append(item)
        if kind == "exact":
            survivors = [
                c for c in item["candidates"] if c["title"] != gold and not glossary_acquire.is_expansion(term, c["title"])
            ]
            if survivors:  # an empty list would be a no-call control, not a question
                items.append(
                    {
                        **{k: item[k] for k in ("stage", "show", "term", "list", "verified", "flagged", "acquired")},
                        "id": f"verify-neg:{show}:{term}",
                        "candidates": survivors,
                        "no_call": False,
                        "would_ask": item["would_ask"],
                        "wiki_cache_stale": stale,
                        "negative": True,
                        "source_id": item["id"],
                        "gold": "none",
                        "gold_source": "synthetic",
                        "gold_kind": "negative",
                    }
                )
    return items


def acquire_items(cache, show):
    """One item per cached (variant, canonical) pair that production's own reader accepts."""
    items, bad = [], 0
    for variant in sorted(cache):
        pairs = cache[variant]
        if not isinstance(pairs, dict):
            bad += 1
            continue
        for canonical in sorted(pairs):
            verdict = acquire_cache.escalation_for(cache, variant, canonical)
            if verdict is None:
                bad += 1
                continue
            items.append(
                {
                    "id": f"acquire:{show}:{variant}|{canonical}",
                    "stage": "acquire",
                    "show": show,
                    "variant": variant,
                    "canonical": canonical,
                    "historical": verdict,
                    "quotes": None,
                }
            )
    return items, bad


def _wanted(show, stem, filters):
    return not filters or any(f.casefold() in show.casefold() or f.casefold() in stem.casefold() for f in filters)


def build_set(gloss_dir, wiki_dir, filters=(), as_of=None):
    """(items, per-show stats, skipped notes). Pure with respect to its inputs; never raises on bad data."""
    items, stats, skipped = [], {}, []
    if as_of is None:
        as_of = _snapshot_time(wiki_dir)
    stems_with_glossary = set()
    for fname in _glossary_files(gloss_dir):
        stem = fname[: -len(".json")]
        stems_with_glossary.add(stem)
        gloss, err = _read_json(os.path.join(gloss_dir, fname))
        if err or not isinstance(gloss, dict):
            if _wanted(stem, stem, filters):
                skipped.append((stem, f"glossary skipped: {err or 'not a JSON object'}"))
                if os.path.exists(os.path.join(gloss_dir, stem + acquire_cache.SUFFIX)):
                    skipped.append((stem, "its acquire cache was not read (the glossary is unusable)"))
            continue
        show = gloss.get("show") if isinstance(gloss.get("show"), str) and gloss.get("show") else stem
        if not _wanted(show, stem, filters):
            continue
        row = stats.setdefault(show, dict.fromkeys(_COLS, 0))
        lists_ok = all(
            isinstance(gloss.get(k, []), list) and all(isinstance(x, str) for x in gloss.get(k, [])) for k in ("names", "phrases")
        )
        if not lists_ok:
            skipped.append((show, "glossary malformed: names/phrases are not lists of strings (verify items skipped)"))
        else:
            wiki_path = wiki_cache_path(wiki_dir, show)
            if not os.path.exists(wiki_path):
                skipped.append((show, "no wiki cache (verify items skipped)"))
            else:
                doc, werr = _read_json(wiki_path)
                titles = doc.get("titles") if isinstance(doc, dict) else None
                if werr or not isinstance(titles, list):
                    skipped.append((show, f"wiki cache {werr or 'malformed: no titles list'} (verify items skipped)"))
                elif not titles:
                    skipped.append((show, "wiki cache empty: no titles (verify items skipped)"))
                else:
                    titles = [t for t in titles if isinstance(t, str)]
                    vi = verify_items(gloss, show, titles, _wiki_stale(doc, as_of, gloss))
                    items += vi
                    real = [i for i in vi if not i.get("negative")]
                    row["verify"] = len(real)
                    row["with_candidates"] = sum(1 for i in real if not i["no_call"])
                    row["no_call"] = sum(1 for i in real if i["no_call"])
                    row["with_gold"] = sum(1 for i in real if i["gold"] is not None)
                    row["negatives"] = len(vi) - len(real)
                    row["would_ask"] = sum(1 for i in real if i["would_ask"])
        _acquire_for(os.path.join(gloss_dir, stem + acquire_cache.SUFFIX), show, row, items, skipped)
    # acquire caches whose glossary file is missing: the show is the file stem
    for fname in sorted(os.listdir(gloss_dir)):
        if fname.endswith(acquire_cache.SUFFIX):
            stem = fname[: -len(acquire_cache.SUFFIX)]
            if stem not in stems_with_glossary and _wanted(stem, stem, filters):
                row = stats.setdefault(stem, dict.fromkeys(_COLS, 0))
                _acquire_for(os.path.join(gloss_dir, fname), stem, row, items, skipped)
    return items, stats, skipped


def _acquire_for(path, show, row, items, skipped):
    if not os.path.exists(path):
        return
    cache, err = _read_json(path)
    if err or not isinstance(cache, dict) or not cache:
        skipped.append((show, f"acquire cache {err or 'empty or not an object'} (acquire items skipped)"))
        return
    ai, bad = acquire_items(cache, show)
    items += ai
    row["acquire"] = len(ai)
    if bad:
        skipped.append((show, f"{bad} malformed acquire pair entr{'y' if bad == 1 else 'ies'} skipped"))


_COLS = ("verify", "with_candidates", "no_call", "with_gold", "negatives", "would_ask", "acquire")


def _summary(stats, skipped, items):
    widths = (7, 8, 8, 7, 5, 9, 8)
    head = f"{'show':<44} {'verify':>7} {'w/cands':>8} {'no_call':>8} {'w/gold':>7} {'neg':>5} {'would_ask':>9} {'acquire':>8}"
    lines = [
        "Verify items = what `verify --force` would send, from an offline snapshot "
        "(would_ask: what a normal sweep would still ask).",
        head,
        "-" * len(head),
    ]
    for show in sorted(stats):
        r = stats[show]
        lines.append(f"{show[:44]:<44} " + " ".join(f"{r[c]:>{w}}" for c, w in zip(_COLS, widths, strict=True)))
    tot = {c: sum(r[c] for r in stats.values()) for c in _COLS}
    lines.append("-" * len(head))
    lines.append(f"{'TOTAL':<44} " + " ".join(f"{tot[c]:>{w}}" for c, w in zip(_COLS, widths, strict=True)))
    v = [i for i in items if i["stage"] == "verify" and not i.get("negative")]
    kinds = {k: sum(1 for i in v if i.get("gold_kind") == k) for k in ("exact", "expansion")}
    lines.append(
        f"gold: exact {kinds['exact']}, expansion {kinds['expansion']} "
        f"(incumbent-derived {sum(1 for i in v if i.get('incumbent_derived'))}); "
        f"ambiguous (no gold) {sum(1 for i in v if i.get('gold_ambiguous'))}; "
        f"single-candidate items {sum(1 for i in v if len(i['candidates']) == 1)}; "
        f"negatives {tot['negatives']}; would_ask {tot['would_ask']}; "
        f"wiki_cache_stale {sum(1 for i in v if i['wiki_cache_stale'])}"
    )
    lines.append(f"{len(items)} items written")
    lines.append(f"skipped: {len(skipped)}")
    lines += [f"  - {show}: {why}" for show, why in skipped]
    return "\n".join(lines)


_sleep = time.sleep  # indirection so tests never really sleep


# ---- run ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Arm:
    """One thing to measure. kind: local (the production llm_chat), text (an OpenAI-compatible chat API through
    tools/bakeoff.ask_openai) or decision (OpenRouter's decisions API through tools/decision_client).
    url / model can be overridden per arm with GLOSSARY_BAKEOFF_<ARM>_URL / _MODEL (ARM = upper-case, - -> _)."""

    name: str
    kind: str
    model: str = ""
    url: str = ""
    key_env: str = ""
    extra_body: dict = field(default_factory=dict)
    third_party: bool = True
    delay: float = 0.0  # default pause between calls (seconds); --delay overrides, including with 0


_LONGCAT_URL = "https://api.longcat.chat/openai/v1/chat/completions"
# URLs, model ids, key variables and extra bodies below are the ones the anchored repair bake-off ran live. NVIDIA's free tier
# allows about 40 requests a minute, hence the 1.6 s default pause; override with GLOSSARY_BAKEOFF_<ARM>_URL / _MODEL.
_NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_DECISIONS = decision_client.DECISIONS_URL
_JEV_KEY = "OPENROUTER_JEV_API_KEY"
ARMS = {
    a.name: a
    for a in (
        Arm("qwen-local", "local", model=glossary_verify.VERIFY_MODEL, third_party=False),
        Arm(
            "longcat-2.0", "text", "LongCat-2.0", _LONGCAT_URL, "LONGCATAI_API_KEY", {"thinking": {"type": "disabled"}}, delay=0.3
        ),
        Arm(
            "longcat-2.5",
            "text",
            "LongCat-2.5-Preview",
            _LONGCAT_URL,
            "LONGCATAI_API_KEY",
            {"thinking": {"type": "disabled"}},
            delay=0.3,
        ),  # fmt: skip
        Arm(
            "nemotron-super",
            "text",
            "nvidia/nemotron-3-super-120b-a12b",
            _NVIDIA_URL,
            "NVIDIA_API_KEY",
            {"chat_template_kwargs": {"enable_thinking": False}},
            delay=1.6,
        ),  # fmt: skip
        Arm("mercury-decide", "decision", "inception/mercury-decide:free", _DECISIONS, _JEV_KEY),
        Arm("span-01-lite", "decision", "respan/span-01-lite", _DECISIONS, _JEV_KEY),
        Arm("solar-decide-flash", "decision", "upstage/solar-decide-flash", _DECISIONS, _JEV_KEY),
        Arm("pplx-decider", "decision", "perplexity/pplx-decider-v1.1-27b", _DECISIONS, _JEV_KEY),
        Arm("gpt-6-luna-decisions", "decision", "openai/gpt-6-luna-decisions", _DECISIONS, _JEV_KEY),
        Arm("jev", "decision", "typesafe/jev-1.13", _DECISIONS, _JEV_KEY),
    )
}
NONE_OPTION = "no candidate is the same named entity"


def _arm_setting(arm, field_name):
    env = f"GLOSSARY_BAKEOFF_{arm.name.upper().replace('-', '_').replace('.', '_')}_{field_name.upper()}"
    return os.environ.get(env) or getattr(arm, field_name)


@contextlib.contextmanager
def _swapped_llm_chat(fn):
    """Route the production adjudicators through ``fn`` (same signature as common.llm_chat) for one call."""
    saved = (glossary_verify.llm_chat, glossary_acquire.llm_chat)
    glossary_verify.llm_chat = glossary_acquire.llm_chat = fn
    try:
        yield
    finally:
        glossary_verify.llm_chat, glossary_acquire.llm_chat = saved


class _Capture:
    """What the swapped llm_chat saw: the raw text, the failure (if any), usage and latency."""

    def __init__(self):
        self.raw, self.error, self.usage, self.latency = None, None, None, 0.0


def _llm_chat_for(arm, cap):
    def fn(prompt, **kw):
        t0 = time.monotonic()
        if arm.kind == "local":
            out = common.llm_chat(prompt, **kw)  # looked up at call time: the production transport
            cap.latency = time.monotonic() - t0
            if not out:
                cap.error = "no answer from the local model"
                return ""
            cap.raw = out
            return out
        sink = []
        out, dt = bakeoff.ask_openai(
            _arm_setting(arm, "url"), _arm_setting(arm, "model"), prompt, arm.key_env, arm.extra_body, sink,
            max_tokens=kw.get("max_tokens", 512), first_line=False, deadline=repair._request_deadline(),
        )  # fmt: skip
        cap.latency, cap.usage = dt, (sink[0] if sink else None)
        if out.startswith(("<ERROR", "<EMPTY")):
            cap.error = out.strip("<>")
            return ""
        cap.raw = out
        return out

    return fn


ANSWER_FIELDS = ("type", "choice", "probabilities", "confidence", "probability")
RATE_LIMIT_STREAK = 5


def _clean_answer(a):
    """Keep only the answer fields the scorer reads: a server may echo anything (even our headers) in an answer."""
    return {k: a[k] for k in ANSWER_FIELDS if k in a} if isinstance(a, dict) else a


def _is_span(arm):
    return _arm_setting(arm, "model").startswith("respan/span-01-lite")


def _row(raw=None, parsed=None, latency=0.0, usage=None, error=None, **extra):
    return {"raw": raw, "parsed": parsed, "latency_s": round(latency, 4), "usage": usage, "error": error, **extra}


def _quotes(item):
    q = item.get("quotes")
    if isinstance(q, dict) and isinstance(q.get("variant"), list) and isinstance(q.get("canonical"), list):
        return q["variant"], q["canonical"]
    return None


def _verify_text(arm, item, titles):
    cap = _Capture()
    with _swapped_llm_chat(_llm_chat_for(arm, cap)):
        adj = glossary_verify.adjudicate(item["term"], titles, item["show"])
    if cap.error:
        return _row(error=cap.error, latency=cap.latency, usage=cap.usage)
    return _row(cap.raw, {"canonical": adj["canonical"], "confidence": adj["confidence"]}, cap.latency, cap.usage)


def _acquire_text(arm, item):
    ctx_v, ctx_c = _quotes(item) or ([], [])
    cap = _Capture()
    with _swapped_llm_chat(_llm_chat_for(arm, cap)):
        adj = glossary_acquire.adjudicate_merge(item["variant"], item["canonical"], ctx_v, ctx_c, item["show"])
    if cap.error or adj.get("unavailable"):
        return _row(raw=cap.raw, error=cap.error or "unparseable answer", latency=cap.latency, usage=cap.usage)
    return _row(cap.raw, {"same_entity": adj["same_entity"], "confidence": adj["confidence"]}, cap.latency, cap.usage)


def _decide(arm, state, questions):
    return decision_client.decide(_arm_setting(arm, "model"), state, questions, arm.key_env, url=_arm_setting(arm, "url"))


def _verify_decision(arm, item, titles):
    if _is_span(arm):
        return _verify_span(arm, item, titles)
    options = {f"c{i}": t for i, t in enumerate(titles, 1)}
    q = {
        "type": "choice",
        "instructions": (
            f'A term was mined from the English dub of "{item["show"]}". Pick the candidate wiki page that is the '
            f'SAME named entity as the term "{item["term"]}". Choose "none" if no candidate is the same entity.'
        ),
        "criteria": {**options, "none": NONE_OPTION},
    }
    res = _decide(arm, {"show": item["show"], "term": item["term"]}, {"pick": q})
    ans = res.answers["pick"]
    choice = ans["choice"]
    parsed = {
        "choice": choice,
        "canonical": options.get(choice, ""),
        "probabilities": ans.get("probabilities"),
        "confidence": ans.get("confidence"),
    }
    return _row({"answer": _clean_answer(ans), "options": options}, parsed, res.latency_s, res.usage, served_model=res.model)


def _verify_span(arm, item, titles):
    """Span-01 Lite takes only noul questions on an {input, output} state: ask once per candidate title."""
    scores, raws, usage, latency, served = {}, [], {}, 0.0, None
    for title in titles:
        state = {
            "input": [{"role": "user", "content": f"Show: {item['show']}\nMined term: {item['term']}\nWhich wiki page is it?"}],
            "output": {"role": "assistant", "content": title},
        }
        q = {
            "type": "noul",
            "instructions": "Is this title the same named entity as the term?",
            "criteria": {"true": "the title is the same named entity as the term", "false": "the title is a different entity"},
        }
        res = _decide(arm, state, {"same": q})
        served = res.model
        scores[title] = _clean_answer(res.answers["same"])
        raws.append({"title": title, "answer": scores[title]})
        latency += res.latency_s
        for k, v in res.usage.items():
            usage[k] = usage.get(k, 0) + v if isinstance(v, (int, float)) else v
    return _row(raws, {"scores": scores}, latency, usage, served_model=served)


def _acquire_decision(arm, item):
    qv, qc = _quotes(item)
    a, b = item["variant"], item["canonical"]
    instructions = (
        f'Two spellings appear in the English dub of "{item["show"]}": "{a}" and "{b}". Are they the SAME name '
        "mis-transcribed (true), or two different legitimate forms such as a nickname, a title or a separate character (false)?"
    )
    q = {
        "type": "noul",
        "instructions": instructions,
        "criteria": {"true": "the same name, mis-transcribed", "false": "two different forms"},
    }
    if _is_span(arm):
        body = f"Spelling A: {a}\n" + "\n".join(qv) + f"\nSpelling B: {b}\n" + "\n".join(qc)
        state = {
            "input": [{"role": "user", "content": instructions + "\n" + body}],
            "output": {"role": "assistant", "content": f"{a} = {b}"},
        }
    else:
        state = {"show": item["show"], "spelling_a": a, "spelling_b": b, "quotes_a": qv, "quotes_b": qc}
    res = _decide(arm, state, {"same": q})
    ans = _clean_answer(res.answers["same"])
    return _row(ans, {"noul": ans}, res.latency_s, res.usage, served_model=res.model)


def run_item(arm, item, order):
    """One result row body for (arm, item, order); a failure is an error row, never a pick."""
    titles = [c["title"] for c in item.get("candidates", [])]
    if order == "rev":
        titles.reverse()
    try:
        if item["stage"] == "verify":
            if arm.kind == "decision":
                return _verify_decision(arm, item, titles)
            return _verify_text(arm, item, titles)
        if arm.kind == "decision":
            return _acquire_decision(arm, item)
        return _acquire_text(arm, item)
    except decision_client.DecisionError as e:
        return _row(error=str(e))  # messages are built from a status / class name only
    except SystemExit as e:  # bakeoff.ask_openai refuses an unusable key this way; the text names only the variable
        return _row(error=f"SystemExit: {e}")
    except Exception as e:  # noqa: BLE001 -- only the class is recorded: a transport error's text can quote a header
        return _row(error=type(e).__name__)


def _load_items(path):
    items, bad = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                it = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(it, dict) and it.get("stage") in ("verify", "acquire") and isinstance(it.get("id"), str):
                items.append(it)
            else:
                bad += 1
    return items, bad


def _load_done(path):
    """{(id, arm, order): errored?} from an existing results file, the latest row per key winning.
    A torn last line (a crash mid-write) is ignored."""
    state = {}
    if not os.path.exists(path):
        return state
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                state[(r["id"], r["arm"], r["order"])] = bool(r.get("error"))
            except (ValueError, KeyError, TypeError):
                continue
    return state


def _ends_with_newline(path):
    with open(path, "rb") as f:
        f.seek(-1, os.SEEK_END)
        return f.read(1) == b"\n"


def _startup_line(arm, stage):
    if not arm.third_party:
        url = glossary_verify.VERIFY_LLAMACPP_URL if glossary_verify.VERIFY_BACKEND == "llamacpp" else glossary_verify.OLLAMA
        return f"run: arm={arm.name} goes only to the production llm_chat endpoint ({urllib.parse.urlsplit(url).netloc or url})"
    host = _arm_setting(arm, "url").split("/")[2] if "//" in _arm_setting(arm, "url") else _arm_setting(arm, "url")
    parts = []
    if stage in ("verify", "both"):
        parts.append("verify items: show title, mined term, wiki candidate titles")
    if stage in ("acquire", "both"):
        parts.append("acquire items WITH quotes only: the two spellings and transcript quotes")
    return f"run: arm={arm.name} ({_arm_setting(arm, 'model')}) sends to {host}: " + "; ".join(parts)


def cmd_run(a):
    arm = ARMS[a.arm]
    items, bad = _load_items(a.items)
    if a.stage != "both":
        items = [i for i in items if i["stage"] == a.stage]
    if a.only == "gold":
        items = [i for i in items if i["stage"] == "verify" and i.get("gold") is not None]
    elif a.only == "nocall":
        items = [i for i in items if i["stage"] == "verify" and i.get("no_call")]
    if a.sample is not None and a.sample < len(items):
        keep = set(random.Random(a.seed).sample(range(len(items)), a.sample))
        items = [it for i, it in enumerate(items) if i in keep]
    if a.limit is not None:
        items = items[: a.limit]
    order = "rev" if a.reverse else "fwd"
    delay = arm.delay if a.delay is None else a.delay
    print(_startup_line(arm, a.stage), flush=True)
    done = _load_done(a.out)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    n = {"sent": 0, "local": 0, "resumed": 0, "errors": 0, "no_quotes": 0, "not_applicable": 0}
    handled = streak = 0
    limited = False
    secret = repair.clean_api_key(os.environ.get(arm.key_env, "")) if arm.key_env else None
    with open(a.out, "a", encoding="utf-8") as out:
        if out.tell() and not _ends_with_newline(a.out):
            out.write("\n")  # a crash mid-row left a torn line; do not glue the next row onto it
        for item in items:
            key = (item["id"], arm.name, order)
            if item["stage"] == "acquire" and a.reverse:
                n["not_applicable"] += 1  # an acquire pair has no candidate list to reverse
                continue
            if item["stage"] == "acquire" and arm.third_party and _quotes(item) is None:
                n["no_quotes"] += 1  # no quotes yet, and none are invented
                continue
            if key in done and (not done[key] or not a.retry_errors):
                n["resumed"] += 1
                continue
            if item["stage"] == "verify" and (item.get("no_call") or not item.get("candidates")):
                body = _row(None, {"canonical": "", "confidence": "none"}, 0.0, None, None, local=True)
                n["local"] += 1
            else:
                if n["sent"] and delay:
                    _sleep(delay)
                body = run_item(arm, item, order)
                n["sent"] += 1
                n["errors"] += 1 if body["error"] else 0
                streak = streak + 1 if body["error"] and re.search(r"\b429\b", body["error"]) else 0
            line = json.dumps({"id": item["id"], "arm": arm.name, "order": order, **body}, ensure_ascii=False)
            if secret and secret in line:
                line = line.replace(secret, "***")  # defence in depth: nothing a server echoes may carry the key to disk
            out.write(line + "\n")
            out.flush()
            if streak >= RATE_LIMIT_STREAK:
                limited = True
                break
            handled += 1
            if handled % 25 == 0:
                print(f"run: {handled}/{len(items)} items, {n['errors']} errors", file=sys.stderr, flush=True)
    print(
        f"run {arm.name} ({order}): sent {n['sent']}, local no-call {n['local']}, resumed {n['resumed']}, errors {n['errors']}, "
        f"skipped (no quotes): {n['no_quotes']}, skipped (not applicable): {n['not_applicable']}, bad item lines: {bad}"
    )
    if limited:
        print(f"run: rate limited, resume later with --retry-errors ({RATE_LIMIT_STREAK} HTTP 429 in a row)", file=sys.stderr)
        return 3
    return 0


def cmd_build_set(a):
    items, stats, skipped = build_set(a.glossaries, a.wiki_cache, a.show or (), a.as_of)
    text = "".join(json.dumps(i, ensure_ascii=False, sort_keys=False) + "\n" for i in items)
    try:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    except OSError as e:
        print(f"build-set: cannot write --out {a.out!r}: {e.strerror or type(e).__name__}", file=sys.stderr)
        return 1
    print(_summary(stats, skipped, items))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Glossary-stage bake-off (phase 1: build the offline item set).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    bs = sub.add_parser("build-set", help="write items.jsonl from copies of the glossaries and wiki caches")
    bs.add_argument("--glossaries", required=True, help="directory of <show>.json and <show>.acquire-cache.json copies")
    bs.add_argument("--wiki-cache", required=True, help="directory of wiki title caches (<show_key>.json)")
    bs.add_argument("--out", required=True, help="items.jsonl to write")
    bs.add_argument(
        "--as-of", type=float, metavar="EPOCH", help="'now' for the wiki-cache staleness flag (default: the freshest cache)"
    )
    bs.add_argument("--show", nargs="+", metavar="SUBSTRING", help="only shows whose name contains one of these (casefolded)")
    rn = sub.add_parser("run", help="put the item set to one arm and append result rows")
    rn.add_argument("--items", required=True, help="items.jsonl from build-set")
    rn.add_argument("--arm", required=True, choices=sorted(ARMS), help="which model / route to measure")
    rn.add_argument("--out", required=True, help="results file (appended; resumable)")
    rn.add_argument("--stage", choices=("verify", "acquire", "both"), default="both")
    rn.add_argument(
        "--only",
        choices=("gold", "all", "nocall"),
        default="all",
        help="gold: items with a gold label; nocall: only the controls",
    )
    rn.add_argument("--sample", type=int, metavar="N", help="a deterministic random sample of N items (with --seed)")
    rn.add_argument("--seed", type=int, default=0)
    rn.add_argument("--limit", type=int, metavar="N", help="stop after the first N selected items")
    rn.add_argument("--reverse", action="store_true", help="verify items with the candidate list reversed (order 'rev')")
    rn.add_argument(
        "--delay",
        type=_delay_seconds,
        default=None,
        metavar="SECONDS",
        help="pause between sent calls (default: the arm's own, see ARMS)",
    )
    rn.add_argument("--retry-errors", action="store_true", help="re-run rows that ended in an error")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        if not os.path.isfile(a.items):
            ap.error(f"--items: {a.items!r} is not a file")
        arm = ARMS[a.arm]
        if os.path.realpath(a.out) == os.path.realpath(a.items):
            ap.error("--out must not be the --items file (results would be appended into the item set)")
        if arm.third_party and not os.environ.get(arm.key_env, "").strip():
            ap.error(f"arm {arm.name} needs the API key in the environment variable {arm.key_env}, which is not set")
        return cmd_run(a)
    for flag in ("glossaries", "wiki_cache"):
        if not os.path.isdir(getattr(a, flag)):
            ap.error(f"--{flag.replace('_', '-')}: {getattr(a, flag)!r} is not a directory")
    return cmd_build_set(a)


if __name__ == "__main__":
    sys.exit(main())
