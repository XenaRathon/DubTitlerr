#!/usr/bin/env python3
"""Glossary wiki-verifier — make any glossary's proper-noun spellings as accurate as the
hand-tuned One Pace one, automatically.

Hybrid approach: fetch the show's wiki main-namespace page index (Fandom MediaWiki API),
pre-match each glossary term to the top-K similar titles (deterministic), then a local LLM
(qwen3:8b) picks the canonical entity and prefers the DUB spelling. High-confidence matches
are applied to the glossary; low-confidence / no-match terms are kept and flagged for review.
Incremental (a ``verified`` set skips re-checks) and cached (page index per show). Resilient:
any wiki/LLM failure is a no-op, never stalls the pipeline.

What adjudicates is VERIFY_BACKEND (llamacpp | ollama | openai | decision; see the comment above resolve_backend): the local
qwen3:8b by default, a hosted OpenAI-compatible text model, or a decision model through glossary_decision. The hosted two are
opt-in; a misconfigured or unresolvable backend refuses the run (`note: refused: ...`) instead of marking terms "no match".

Reusable module + CLI — called by the mining hook in gen_loop, a standalone command, and
future community-repo front-ends. Source of truth = wiki/publisher (dub-preferred). See
specs/glossary-wiki-verify/spec.md.  Built with help of Claude (Anthropic).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import difflib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import common
from common import llm_chat, stop_requested


def log(*a):
    print(*a, flush=True)


TOPK = 6  # candidate titles per term handed to the LLM
CAND_CUTOFF = 0.62  # min similarity for a candidate (0.5 let junk like blarghxyzqq->Largo in)
VERIFY_MODEL = os.environ.get("VERIFY_MODEL", "qwen3:8b")
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
# VERIFY_BACKEND (llamacpp|ollama|openai|decision) picks what adjudicates, for verify AND acquire's LLM calls:
#   llamacpp / ollama  the local server (the default; VERIFY_LLAMACPP_URL / OLLAMA_URL, VERIFY_MODEL for ollama);
#   openai             a hosted OpenAI-compatible text model: VERIFY_OPENAI_URL, VERIFY_OPENAI_KEY_ENV (the NAME of the env
#                      var holding the key), VERIFY_MODEL (required), VERIFY_OPENAI_EXTRA_BODY (optional JSON object);
#   decision           a decision model through decision_client (see glossary_decision for its VERIFY_DECISION_* variables).
# Unset, it follows REPAIR_BACKEND so the whole pipeline can sit on one local model on a shared 8 GB GPU, but ONLY for the two
# legacy values: REPAIR_BACKEND=openai describes repair's chat-completions client, and inheriting it here used to send glossary
# prompts in Ollama's request shape. Any other REPAIR_BACKEND with VERIFY_BACKEND unset is refused (resolve_backend).
LEGACY_BACKENDS = common.LEGACY_BACKENDS
VERIFY_BACKENDS = (*LEGACY_BACKENDS, "openai", "decision")


def resolve_backend(env=None):
    """(backend, problem): the glossary stages' backend from the environment, or ("", why it is refused).

    VERIFY_BACKEND, when set and non-empty, must be one of VERIFY_BACKENDS. Unset, REPAIR_BACKEND is inherited only when it
    is llamacpp or ollama (unset too: ollama, the long-standing default); anything else must be answered explicitly."""
    env = os.environ if env is None else env
    explicit = (env.get("VERIFY_BACKEND") or "").strip()
    if explicit:
        if explicit in VERIFY_BACKENDS:
            return explicit, ""
        return "", f"VERIFY_BACKEND={explicit!r} is not one of {', '.join(VERIFY_BACKENDS)}"
    return common.inherit_repair_backend(
        env.get("REPAIR_BACKEND"), "the glossary stages", f"set VERIFY_BACKEND to one of {', '.join(VERIFY_BACKENDS)}"
    )


VERIFY_BACKEND, BACKEND_PROBLEM = resolve_backend()
VERIFY_LLAMACPP_URL = os.environ.get(
    "VERIFY_LLAMACPP_URL", os.environ.get("REPAIR_LLAMACPP_URL", "http://127.0.0.1:8080/v1/chat/completions")
)
# Adjudication returns a JSON object, not a subtitle line: it needs a real token budget and
# must not be truncated to its first line.
VERIFY_MAX_TOKENS = int(os.environ.get("VERIFY_MAX_TOKENS", "512"))
CACHE_DIR = os.environ.get("WIKI_CACHE_DIR", "/config/wiki_cache")
HTTP_TIMEOUT = int(os.environ.get("WIKI_HTTP_TIMEOUT", "20"))
WIKI_TTL = int(os.environ.get("WIKI_CACHE_TTL", str(30 * 24 * 3600)))  # refresh index monthly
VERIFY_WORKERS = int(os.environ.get("VERIFY_WORKERS", "4"))  # V2 C2: concurrent adjudicate() calls


class BackendConfigError(RuntimeError):
    """The glossary stages' backend is unresolved or misconfigured: nothing may be adjudicated (see backend_problem)."""


def backend_problem():
    """Why the glossary stages must not run, or "" when the configured backend is usable. Checked once before any work by
    verify() and acquire(), so a misconfiguration refuses the run instead of turning every term into a "no match".
    The env vars of the openai backend are read here, at call time, and only their NAMES appear in the message."""
    if VERIFY_BACKEND not in VERIFY_BACKENDS:
        return BACKEND_PROBLEM or f"VERIFY_BACKEND={VERIFY_BACKEND!r} is not one of {', '.join(VERIFY_BACKENDS)}"
    if VERIFY_BACKEND == "decision":
        import glossary_decision

        why = glossary_decision.problem()
        if why:
            return why
        if glossary_decision.settings().fallback == "local":
            local = os.environ.get("VERIFY_DECISION_LOCAL_BACKEND", "").strip()
            if local and local not in LEGACY_BACKENDS:
                return f"VERIFY_DECISION_LOCAL_BACKEND must be one of {', '.join(LEGACY_BACKENDS)}"
    if VERIFY_BACKEND == "openai":
        import repair

        url = os.environ.get("VERIFY_OPENAI_URL", "").strip()
        key_env = os.environ.get("VERIFY_OPENAI_KEY_ENV", "").strip()
        if not url:
            return "VERIFY_BACKEND=openai needs VERIFY_OPENAI_URL"
        why = common.openai_endpoint_problem(url)
        if why:
            return f"VERIFY_OPENAI_URL is refused: {why}"
        if not key_env:
            return "VERIFY_BACKEND=openai needs VERIFY_OPENAI_KEY_ENV (the NAME of the env var holding the key)"
        if not os.environ.get(key_env, "").strip():
            return f"the env var {key_env} named by VERIFY_OPENAI_KEY_ENV is not set"
        if repair.clean_api_key(os.environ[key_env]) is None:
            return f"the key in env var {key_env} contains spaces or control characters"
        if not os.environ.get("VERIFY_MODEL", "").strip():
            return "VERIFY_BACKEND=openai needs VERIFY_MODEL (the default belongs to the local Ollama)"
        try:
            repair._parse_extra_body(os.environ.get("VERIFY_OPENAI_EXTRA_BODY", ""))
        except ValueError:
            return "VERIFY_OPENAI_EXTRA_BODY is not a valid JSON object"
    return ""


def local_backend():
    """The local backend the decision backend falls back to (VERIFY_DECISION_FALLBACK=local): VERIFY_DECISION_LOCAL_BACKEND,
    else REPAIR_BACKEND when it is llamacpp or ollama, else ollama."""
    chosen = os.environ.get("VERIFY_DECISION_LOCAL_BACKEND", "").strip()
    if chosen in LEGACY_BACKENDS:
        return chosen
    inherited = os.environ.get("REPAIR_BACKEND", "").strip()
    return inherited if inherited in LEGACY_BACKENDS else "ollama"


def announce(stage):
    """At the start of a run on a hosted backend (openai, decision), say which fields go to which host. Local backends say
    nothing: nothing leaves the machine."""
    if VERIFY_BACKEND == "decision":
        import glossary_decision

        glossary_decision.announce(stage)
    elif VERIFY_BACKEND == "openai":
        host = urllib.parse.urlsplit(os.environ.get("VERIFY_OPENAI_URL", "")).hostname
        what = (
            "the show name, both spellings of each pair and up to a few transcript lines quoting each"
            if stage == "acquire"
            else "the show name, the term and its candidate wiki page titles"
        )
        log(
            f"glossary {stage}: sending {what} to {host} (model {os.environ.get('VERIFY_MODEL', '')}); "
            "nothing else leaves the machine"
        )


def begin_run(stage):
    """Start of a verify / acquire run: announce a hosted backend and zero the decision counters."""
    if VERIFY_BACKEND in ("openai", "decision"):
        announce(stage)
    if VERIFY_BACKEND == "decision":
        import glossary_decision

        glossary_decision.reset()


def end_run(rep):
    """End of a run: on the decision backend print the one summary line and add the counters to the report as `decision`.
    Any other backend: the report is returned untouched and nothing is printed."""
    if VERIFY_BACKEND == "decision":
        import glossary_decision

        log(glossary_decision.summary_line())
        rep = {**rep, "decision": glossary_decision.counters()}
    return rep


def refusal_exit(rep):
    """VERIFY_REFUSE_EXIT=1 (default off): a run refused for its backend ends with a final 'REFUSED' line and exit status 2, so a
    wrapper that only looks at the status notices it. Unset, a refusal exits 0 like every other no-op of this stage."""
    note = rep.get("note", "") if isinstance(rep, dict) else ""
    if os.environ.get("VERIFY_REFUSE_EXIT") == "1" and note.startswith("refused:"):
        log(f"REFUSED: {note[len('refused:') :].strip()}")
        sys.exit(2)


def worker_count():
    """Concurrent adjudications in verify(): VERIFY_WORKERS for the local backends (as always); VERIFY_DECISION_WORKERS
    (default 1) for the decision backend, whose provider meters requests and rate-limits per key."""
    if VERIFY_BACKEND == "decision":
        import glossary_decision

        return glossary_decision.settings().workers
    return VERIFY_WORKERS


def llm_settings(backend=None):
    """The keyword arguments adjudication passes to common.llm_chat for ``backend`` (default: the configured one). For a legacy
    backend they are exactly the six the stages have always passed; the openai backend adds its three."""
    backend = backend or VERIFY_BACKEND
    kw = {
        "backend": backend,
        "ollama_url": OLLAMA,
        "llamacpp_url": VERIFY_LLAMACPP_URL,
        "model": VERIFY_MODEL,
        "max_tokens": VERIFY_MAX_TOKENS,
        "first_line": False,
    }
    if backend == "openai":
        kw.update(
            model=os.environ.get("VERIFY_MODEL", "").strip(),
            openai_url=os.environ.get("VERIFY_OPENAI_URL", "").strip(),
            openai_key_env=os.environ.get("VERIFY_OPENAI_KEY_ENV", "").strip(),
            openai_extra_body=os.environ.get("VERIFY_OPENAI_EXTRA_BODY", ""),
        )
    return kw


def candidates(term: str, titles: list[str], k: int = TOPK) -> list[str]:
    """Top-k wiki titles most similar to `term` (>= CAND_CUTOFF). Pure/deterministic."""
    lower_map: dict[str, str] = {}
    for t in titles:
        lower_map.setdefault(t.lower(), t)
    hits = difflib.get_close_matches(term.lower(), list(lower_map), n=k, cutoff=CAND_CUTOFF)
    return [lower_map[h] for h in hits]


def pending_terms(gloss: dict) -> list[str]:
    """Names + phrases not yet in `verified` (incremental: skip already-verified terms)."""
    verified = set(gloss.get("verified", []))
    seen, out = set(), []
    for t in list(gloss.get("names", [])) + list(gloss.get("phrases", [])):
        if t not in verified and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def build_adjudication_prompt(term: str, cands: list[str], show: str) -> str:
    """Prompt asking the LLM to pick the canonical (dub-preferred) spelling among candidates."""
    cl = "\n".join(f"- {c}" for c in cands) or "- (none)"
    return (
        f"You verify the canonical spelling of a proper noun from the anime/manga {show}.\n"
        f'Term as transcribed/mined: "{term}"\n'
        f"Candidate official wiki page titles:\n{cl}\n\n"
        "Pick the ONE candidate that is the SAME entity as the term and give its canonical "
        "spelling. If the English DUB spells it differently from the wiki/manga, PREFER the dub "
        "spelling and say so in dub_note.\n"
        "Use confidence 'high' ONLY when you are certain a candidate is the same named entity as "
        "the term (a clear misspelling/variant of it). If the term is garbled beyond recognition, "
        "or no candidate is clearly the same entity, return confidence 'none' and empty canonical. "
        "Do NOT guess.\n"
        'Reply ONLY as JSON: {"canonical": "<spelling or empty>", '
        '"confidence": "high|low|none", "dub_note": "<short or empty>"}'
    )


def parse_adjudication(text: str) -> dict:
    """Parse the LLM's JSON reply (tolerating surrounding prose) into a normalized adjudication."""
    none = {"canonical": "", "confidence": "none", "dub_note": ""}
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return none
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return none
    conf = str(d.get("confidence", "none")).lower()
    if conf not in ("high", "low", "none"):
        conf = "low"
    return {"canonical": str(d.get("canonical", "") or ""), "confidence": conf, "dub_note": str(d.get("dub_note", "") or "")}


def adjudicate(term: str, cands: list[str], show: str) -> dict | None:
    """LLM pick -> {'canonical': str, 'confidence': 'high'|'low'|'none', 'dub_note': str}.

    Raises BackendConfigError when the configured backend is unusable. Only the decision backend with
    VERIFY_DECISION_FALLBACK=none can return None: the call failed and the term must stay pending, not become a "no match"."""
    if not cands:
        return {"canonical": "", "confidence": "none", "dub_note": ""}
    problem = backend_problem()
    if problem:
        raise BackendConfigError(problem)
    if VERIFY_BACKEND == "decision":
        import glossary_decision

        return glossary_decision.adjudicate_verify(
            term, cands, show, local=lambda: _adjudicate_llm(term, cands, show, local_backend())
        )  # None = left pending (a failed call with VERIFY_DECISION_FALLBACK=none)
    return _adjudicate_llm(term, cands, show, VERIFY_BACKEND)


def _adjudicate_llm(term: str, cands: list[str], show: str, backend: str) -> dict:
    out = llm_chat(build_adjudication_prompt(term, cands, show), **llm_settings(backend))
    if not out:
        return {"canonical": "", "confidence": "none", "dub_note": ""}
    return parse_adjudication(out)


def _shape_list(names: list, phrases: list, term: str) -> list:
    """Which list a term belongs in BY SHAPE. `names` feeds glossary.correct()'s per-token
    tiers (`_TOKEN_RE` matches one token), so a multi-word string there can never match; the
    multi-word path is `phrases`, which feeds repair's term list."""
    return phrases if " " in term.strip() else names


def _whole_word(term: str, canon: str) -> bool:
    """The term's words occur in the canonical as a contiguous, whole-word run (token-wise, casefolded)."""
    if len(re.findall(r"[^\W\d_]", term)) < 2:
        return False  # a one-letter or letterless term ('D', '3') is a whole word of almost any title
    t, c = re.findall(r"\w+", term.casefold()), re.findall(r"\w+", canon.casefold())
    return bool(t) and any(c[i : i + len(t)] == t for i in range(len(c) - len(t) + 1))


def auto_writes(term: str, canon: str) -> bool:
    """Whether a high-confidence ``canon`` for ``term`` is WRITTEN (True) or flagged for review (False).

    By default that is glossary_acquire.is_expansion alone. is_expansion is a substring rule, so it also writes
    near-respellings: 'Usop' -> 'Usopp', 'Burn' -> 'Coburn'. VERIFY_WRITE_WHOLE_WORD=1 (default off) additionally
    requires the term to be a whole word (token-wise, casefolded) of the canonical, which is how the bake-off's expansion gold
    is defined; anything else is flagged 'respelling-needs-review' like any non-expansion. A term with fewer than two letters
    ('D', '3') never passes under this guard. Read per call."""
    # Imported at call time, NOT at module scope: glossary_acquire imports this module (a hard cycle otherwise).
    from glossary_acquire import is_expansion

    if not is_expansion(term, canon):
        return False
    return os.environ.get("VERIFY_WRITE_WHOLE_WORD", "") != "1" or _whole_word(term, canon)


_gate_noop_logged = False


def arc_universe(gloss: dict):
    """The titles of every arc the glossary knows (casefolded), or None when the gate does not apply.

    VERIFY_ARC_GATE=1 (default off) turns the gate on; it is a NO-OP, said once in the log, for a glossary without arc titles
    (never tagged, or a show whose seasons carry no arc). The titles are stored in the glossary by tag_arcs, so applying
    results needs no network.

    debt: this is the 'first' use of the tags (a hard gate on auto-WRITES). The 'second' -- tag-derived confidence for
    episodes with no fansub anchor -- would also read this universe; it is deliberately not built (revisit when unanchored
    repair has a measured need for it)."""
    global _gate_noop_logged
    if os.environ.get("VERIFY_ARC_GATE") != "1":
        return None
    titles = {t.casefold() for ts in (gloss.get("arc_titles") or {}).values() for t in ts}
    if not titles:
        if not _gate_noop_logged:
            _gate_noop_logged = True
            log(
                "VERIFY_ARC_GATE is on but this glossary has no arc titles "
                "(run glossary_verify --tag-arcs): the gate does nothing"
            )
        return None
    return titles


def write_decision(term: str, canon: str, universe) -> str:
    """'write', 'respelling' (flagged: not an expansion / not a whole word) or 'not-in-arc-pages' (flagged: the canonical is not
    on any arc page of the show). ONE place for apply_results and the report's counts."""
    if not auto_writes(term, canon):
        return "respelling"
    if universe is not None and canon.casefold() not in universe:
        return "not-in-arc-pages"
    return "write"


def apply_results(gloss: dict, results: dict) -> dict:
    """Apply per-term adjudications. Pure; preserves unknown fields (curated hard_fixes,
    initial_prompt, wiki, …) by deep-copying the input.

    NEVER REPLACES A TERM IN PLACE. Until 2026-08-21 a high-confidence canonical was written
    over the existing entry (`lst[i] = canon`). That deleted 17 names and 6 phrases from the
    live One Pace glossary -- `Doflamingo`, `Hancock`, `Lucci`, `Rayleigh`, `Kaido`,
    `Trafalgar` and more -- leaving them only in `verified`, which nothing reads at runtime.
    The short form is what the fuzzy and Metaphone tiers match a mishear against; the long
    canonical is what the repair LLM needs. They are not alternatives.

    So the original term ALWAYS survives, and the canonical is handled by kind:

      EXPANSION  (`Doflamingo` -> `Donquixote Doflamingo`): the same entity written longer.
                 Added alongside, routed by shape. Additive and safe -- worst case is one
                 unused phrase, never a lost correction.
      RESPELLING (`Raftel` -> `Ratel`, `Jabra` -> `Jabari`): different letters for what may
                 be a different entity. This is the class that goes wrong, so it is never
                 auto-applied -- it is flagged for `glossary_acquire.py --review`.

    That split is measured, not assumed. Over the 12 canonicals the 2026-08-21 verify run
    produced for One Pace, judged against the dub: every one of the four WRONG respellings
    (`Arabasta`, `Ratel`, `Jabari`, and `Kaidou`'s wiki-over-dub form) is a respelling, and
    six of six correct expansions are expansions. Auto-applying respellings had a measured
    error rate above half.

    A corpus-corroboration guard was designed and REJECTED for this: scored against the real
    463-episode transcript corpus it lands 2 of 8, and it fails toward APPLYing wrong names
    (`Arabasta` outnumbers `Alabasta` 108 to 35 in the transcripts). The corpus is Whisper's
    own output, so it votes for its own mishearing. See
    docs/superpowers/specs/2026-08-21-glossary-integrity-design.md."""
    g = json.loads(json.dumps(gloss))
    names, phrases = g.setdefault("names", []), g.setdefault("phrases", [])
    verified = set(g.get("verified", []))
    flagged = dict(g.get("flagged", {}))
    universe = arc_universe(gloss)
    for term, adj in results.items():
        verified.add(term)
        canon = (adj or {}).get("canonical") or ""
        conf = (adj or {}).get("confidence", "none")
        if conf == "high" and canon and canon != term:
            # Imported at call time, NOT at module scope: glossary_acquire imports this
            # module, so a top-level import is a hard cycle (ImportError on the
            # acquire-first order only -- verify-first appears to work, which is exactly
            # how it would reach production unnoticed).
            decision = write_decision(term, canon, universe)
            if decision == "write":
                dest = _shape_list(names, phrases, canon)
                if canon not in dest:
                    dest.append(canon)  # ADD -- the term itself is left in place
            else:
                flagged[term] = {
                    "reason": "respelling-needs-review" if decision == "respelling" else decision,
                    "canonical": canon,
                }
        elif conf != "high" or not canon:
            flagged[term] = "low-confidence" if (conf == "low" and canon) else "no-match"
    g["verified"] = sorted(verified)
    if flagged:
        g["flagged"] = flagged
    return g


def _clean_title(title: str) -> str:
    return re.sub(r"\s*\(\d{4}\)|\s*\{[^}]*\}", "", title).strip()


def wiki_candidates(title: str) -> list[str]:
    """Candidate Fandom api.php URLs derived from a (messy) show title, best first."""
    t = _clean_title(title).lower()
    slug = re.sub(r"[^a-z0-9]", "", t)
    hyph = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    first = (t.split() or [slug])[0]
    out: list[str] = []
    for s in (slug, hyph, first):
        api = f"https://{s}.fandom.com/api.php"
        if s and api not in out:
            out.append(api)
    return out


def normalize_api(url: str) -> str:
    """Reduce any wiki URL to its `<scheme>://<host>/api.php`."""
    m = re.match(r"(https?://[^/]+)", url)
    return (m.group(1) if m else url).rstrip("/") + "/api.php"


def allpages_url(api: str, apcontinue: str | None = None) -> str:
    u = api + "?action=query&list=allpages&apnamespace=0&aplimit=500&apfilterredir=nonredirects&format=json"
    if apcontinue:
        u += "&apcontinue=" + urllib.parse.quote(apcontinue)
    return u


def parse_allpages(resp: dict) -> tuple[list[str], str | None]:
    titles = [p["title"] for p in resp.get("query", {}).get("allpages", [])]
    return titles, resp.get("continue", {}).get("apcontinue")


def _http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "DubTitlerr-glossary-verify"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return json.loads(r.read())


def resolve_wiki(title: str, override: str | None = None) -> str | None:
    """Resolve the show's Fandom MediaWiki API base (override wins; else probe candidates)."""
    if override:
        return normalize_api(override)
    for api in wiki_candidates(title):
        try:
            j = _http_json(api + "?action=query&meta=siteinfo&format=json")
            if j.get("query", {}).get("general"):
                return api
        except Exception:
            continue
    return None


def arc_categories(wiki_api: str, arc: str) -> list[str]:
    """Category pages that scope an arc, DISCOVERED rather than guessed.

    S-2. Arc category naming is not uniform and cannot be derived from the arc name:
    measured 2026-08-26 on the One Piece wiki, `Category:Dressrosa Arc` does not exist,
    while `Dressrosa Residents`, `Dressrosa Locations` and `Dressrosa Saga Antagonists` do.
    A search of namespace 14 finds whatever that wiki actually calls them.

    Non-canon categories are excluded: this feeds canonical spellings, and `Non-Canon
    Dressrosa Residents` is exactly the material that must not become one.

    Returns [] on any failure. Emptiness is the [S-7] fallback trigger -- a `season.nfo`
    title that is not an arc at all (`Gaimon` is a character) finds no arc categories, and
    the caller must degrade rather than tag from some unrelated page's cast."""
    url = wiki_api + "?action=query&list=search&srnamespace=14&srlimit=25&format=json&srsearch=" + urllib.parse.quote(arc)
    try:
        resp = _http_json(url)
    except Exception:
        return []
    out = []
    for hit in resp.get("query", {}).get("search", []):
        title = hit.get("title", "")
        low = title.lower()
        if "non-canon" in low:
            continue
        # Episode/Chapter/Volume categories hold NUMBERED PAGES, not names. Measured
        # 2026-08-26: including `Dressrosa Arc Episodes` and `Arc Chapters` took the union
        # from 96 entries to 294, the excess being `Episode 629`-shaped noise.
        if any(w in low for w in ("episode", "chapter", "volume")):
            continue
        if arc.lower() in low:
            out.append(title)
    return out


def _extract_links(wt: str) -> set[str]:
    """[[...]] links from wikitext, templates/refs stripped, non-entity links dropped
    (Category:/File:/Image:/w: namespaces, lowercase-first, bare Chapter/Episode/Volume
    N). Shared by arc_page_links (whole page) and plot_section_links (one section) so
    the filter cannot drift between them."""
    for _ in range(4):  # nested templates
        wt = re.sub(r"\{\{[^{}]*\}\}", " ", wt)
    wt = re.sub(r"<ref[^>]*>.*?</ref>", " ", wt, flags=re.S)
    wt = re.sub(r"<[^>]+>", " ", wt)
    out = set()
    for link in re.findall(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]", wt):
        link = link.strip()
        if not link or link[:1].islower():
            continue
        if link.startswith(("Category:", "File:", "Image:", "w:")):
            continue
        if re.match(r"^(Chapter|Episode|Volume)\s+\d+$", link):
            continue
        out.add(link)
    return out


# Longer/more specific alternatives first so e.g. "Plot Details" is matched as itself
# rather than the engine settling for a partial "Plot" attempt that then fails the
# trailing \s*== and backtracks anyway -- correct either order, but this is the clearer one.
_PLOT_SECTION_RE = re.compile(
    r"==\s*(?:Plot Details|Short Summary|Long Summary|Plot|Synopsis|Summary)\s*==(.*?)(?=\n==[^=]|\Z)",
    re.S | re.I,
)


def plot_section_links(wikitext: str) -> set[str]:
    """Entity links from a wiki EPISODE page's plot/summary section(s) -- the per-episode
    candidate primitive [S-2]. Measured 2026-08-29 on SAO's wiki (==Plot==): 26-30 correct
    links per episode versus 1,281+ franchise-wide, zero navbox pollution.

    Different wikis use different headings for the same content, discovered 2026-09-01
    testing per-episode-acquire against real library data: One Piece Fandom uses "Short
    Summary"/"Long Summary" (the latter usually an unpopulated {{Empty section}} stub, not
    "Plot" at all) -- its OWN primary target show, silently inert until this fix. Jujutsu
    Kaisen uses "Plot Details". Spy x Family and My Hero Academia use "Synopsis"/"Summary"
    with no "Plot" heading. Every matching heading on the page is unioned rather than only
    the first: Cowboy Bebop's wiki populates both "Plot" and "Synopsis" with distinct real
    content on the same page, and an empty/stub section like {{Empty section}} naturally
    extracts to no links via _extract_links's own template-strip, so it costs nothing to
    include it in the union. Pure/no network; the caller supplies wikitext already fetched."""
    links: set[str] = set()
    for m in _PLOT_SECTION_RE.finditer(wikitext):
        links |= _extract_links(m.group(1))
    return links


def resolve_redirects(wiki_api: str, titles: set[str]) -> set[str]:
    """Both redirect directions in one MediaWiki call per chunk of <=50 titles [S-3]:
    an input title that is itself a redirect resolves to its target (query.redirects),
    and other pages redirecting TO a resolved target are pulled in too (each page's
    own "redirects" list) -- 'Kirito' linked in prose resolves to 'Kirigaya Kazuto',
    and 'Kirigaya Kazuto' linked directly still admits 'Kirito' as an alias. Fails
    open to the unresolved input set on any error -- never drops a title outright."""
    if not titles:
        return set()
    out = set(titles)
    items = sorted(titles)
    for i in range(0, len(items), 50):
        chunk = items[i : i + 50]
        url = (
            wiki_api
            + "?action=query&redirects=1&prop=redirects&rdlimit=500&format=json&titles="
            + urllib.parse.quote("|".join(chunk))
        )
        try:
            resp = _http_json(url)
        except Exception:
            continue  # this chunk's titles stay unresolved, already in `out`
        q = resp.get("query", {})
        for r in q.get("redirects", []):
            frm, to = r.get("from"), r.get("to")
            if frm and to:
                out.discard(frm)
                out.add(to)
        for page in q.get("pages", {}).values():
            title = page.get("title")
            if not title:
                continue
            out.add(title)
            for inc in page.get("redirects", []):
                inc_title = inc.get("title")
                if inc_title:
                    out.add(inc_title)
    return out


def fetch_episode_titles(wiki_api: str, show_key: str, page_title: str) -> list[str]:
    """Cached Plot-section entity titles for one wiki episode page [S-4]. One JSON
    cache file per SHOW (not per page), each page entry independently WIKI_TTL-gated
    -- mirrors fetch_titles' TTL-file pattern, not acquire_cache's token-verdict
    cache. Only positive results are cached, mirroring fetch_titles' own asymmetry:
    a missing page is retried every call rather than cached empty forever."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, re.sub(r"[^A-Za-z0-9]+", "_", show_key) + "_episodes.json")
    try:
        doc = json.load(open(cache_path))
    except (OSError, ValueError):
        doc = {}
    pages = doc.get("pages", {}) if doc.get("api") == wiki_api else {}
    entry = pages.get(page_title)
    if entry and (time.time() - entry.get("fetched_at", 0)) < WIKI_TTL:
        return entry["titles"]
    url = wiki_api + "?action=parse&prop=wikitext&format=json&page=" + urllib.parse.quote(page_title)
    try:
        wt = _http_json(url)["parse"]["wikitext"]["*"]
    except Exception:
        return []
    titles = sorted(resolve_redirects(wiki_api, plot_section_links(wt)))
    if titles:
        pages[page_title] = {"fetched_at": time.time(), "titles": titles}
        json.dump({"api": wiki_api, "pages": pages}, open(cache_path, "w"))
    return titles


def episode_page_titles(wiki_api: str, show_key: str, page_titles: list[str]) -> tuple[set[str], list[str], list[str]]:
    """Union Plot-section titles across several wiki pages, reporting which pages
    resolved and which didn't [S-5] -- the split S-13's partial-mapping status
    needs, without a second pass over the same pages."""
    union: set[str] = set()
    resolved: list[str] = []
    failed: list[str] = []
    for title in page_titles:
        titles = fetch_episode_titles(wiki_api, show_key, title)
        if titles:
            union |= set(titles)
            resolved.append(title)
        else:
            failed.append(title)
    return union, resolved, failed


def arc_page_links(wiki_api: str, arc: str) -> set[str]:
    """Entities linked from the arc page's PROSE.

    The primary arc source, because categories provably miss the leads: measured
    2026-08-26, neither `Rebecca` nor `Kyros` -- the arc's two most-mentioned characters --
    appears in any `Dressrosa *` category. Rebecca is filed under `Riku Family` and
    `Former Princesses`, which no arc-name search can reach.

    Read from the wikitext with templates and refs stripped, NOT from `prop=links`: that
    API returns the page's navboxes too, which on this wiki means 500 alphabetical
    franchise-wide entries (`100% Island`, `Abdullah`, ...) and is unusable as an arc
    signal. Verified 2026-08-26.

    Returns an empty set on any failure; this runs inside the sweep."""
    url = wiki_api + "?action=parse&prop=wikitext&format=json&page=" + urllib.parse.quote(arc + " Arc")
    # ONLY the "<arc> Arc" page. Falling back to the bare title resolves a page that is not
    # an arc at all and harvests its links: measured 2026-08-26, `Gaimon` -- a season.nfo
    # title that names a CHARACTER -- returned 48 entities that way, which [S-7] requires be
    # treated as no resolution rather than a plausible-looking cast.
    try:
        wt = _http_json(url)["parse"]["wikitext"]["*"]
    except Exception:
        return set()
    return _extract_links(wt)


def fetch_arc_titles(wiki_api: str, arc: str) -> set[str]:
    """Every ns0 page belonging to an arc, unioned across its categories.

    Members come back paged, so continuation is followed -- a truncated union would
    silently under-tag an arc, which is worse than not tagging it at all because the gap
    would be invisible. Bounded at 6 pages per category (3,000 titles), far above the 96
    measured for Dressrosa, so a runaway cannot stall a sweep.

    Returns an empty set on any failure, including an unreachable wiki. This runs inside
    the sweep and must never stall or fail it."""
    titles: set[str] = arc_page_links(wiki_api, arc)
    for cat in arc_categories(wiki_api, arc):
        cont = None
        for _ in range(6):
            url = (
                wiki_api
                + "?action=query&list=categorymembers&cmnamespace=0&cmlimit=500&format=json&cmtitle="
                + urllib.parse.quote(cat)
            )
            if cont:
                url += "&cmcontinue=" + urllib.parse.quote(cont)
            try:
                resp = _http_json(url)
            except Exception:
                break
            titles |= {m["title"] for m in resp.get("query", {}).get("categorymembers", [])}
            cont = resp.get("continue", {}).get("cmcontinue")
            if not cont:
                break
    return titles


def fetch_titles(wiki_api: str, show_key: str) -> list[str]:
    """Cached main-namespace (ns=0) page-title list for the wiki."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, re.sub(r"[^A-Za-z0-9]+", "_", show_key) + ".json")
    try:
        c = json.load(open(cache))
        if c.get("api") == wiki_api and (time.time() - c.get("fetched_at", 0)) < WIKI_TTL:
            return c["titles"]
    except (OSError, ValueError):
        pass
    titles: list[str] = []
    cont = None
    for _ in range(40):  # page cap (40 * 500 = 20k titles)
        try:
            resp = _http_json(allpages_url(wiki_api, cont))
        except Exception:
            break
        ts, cont = parse_allpages(resp)
        titles += ts
        if not cont:
            break
    if titles:
        json.dump({"api": wiki_api, "fetched_at": time.time(), "titles": titles}, open(cache, "w"))
    return titles


_STOPPED = object()  # _one's marker for a term skipped by the soft stop (None is "could not be adjudicated")


# ---- arc tagging (GLOSSARY_ARC_TAGS) -----------------------------------------------------------------------------------------
# [S-11]/[S-5]: ONE arc fetch per distinct arc serves both consumers -- the tags repair weights its prompt by, and the arc
# titles the verify gate (VERIFY_ARC_GATE) checks writes against. Nothing here runs unless gen_loop's GLOSSARY_ARC_TAGS=1
# step or `glossary_verify.py <glossary> --tag-arcs <show dir>` asks for it.


def arcs_in_show(show_dir: str) -> list[str]:
    """The distinct arc names of the show's seasons: every directory under ``show_dir`` holding a season.nfo, read with
    glossary.arc_for (the repair stage's own resolver). Sorted; [] when there are none."""
    import glossary

    arcs = set()
    for root, _dirs, files in os.walk(show_dir):
        if "season.nfo" in files:
            arc = glossary.arc_for(os.path.join(root, "season"))
            if arc:
                arcs.add(arc)
    return sorted(arcs)


def _arc_cache_path(show_key: str) -> str:
    return os.path.join(CACHE_DIR, re.sub(r"[^A-Za-z0-9]+", "_", show_key) + "_arcs.json")


def fetch_arc_titles_cached(wiki_api: str, show_key: str, arc: str) -> tuple[set[str], str]:
    """(titles, 'cached' | 'fetched' | 'empty'). One JSON cache file per show, each arc WIKI_TTL-gated, only POSITIVE results
    cached (the same rules as fetch_episode_titles): an empty result -- a non-arc title [S-7] or an unreachable wiki -- is asked
    again next time."""
    path = _arc_cache_path(show_key)
    try:
        doc = json.load(open(path))
    except (OSError, ValueError):
        doc = {}
    arcs = doc.get("arcs", {}) if doc.get("api") == wiki_api else {}
    entry = arcs.get(arc)
    if entry and (time.time() - entry.get("fetched_at", 0)) < WIKI_TTL:
        return set(entry["titles"]), "cached"
    titles = fetch_arc_titles(wiki_api, arc)
    if not titles:
        return set(), "empty"
    arcs[arc] = {"fetched_at": time.time(), "titles": sorted(titles)}
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        json.dump({"api": wiki_api, "arcs": arcs}, open(path, "w"))
    except OSError:
        pass  # a cache that cannot be written costs a refetch, nothing more
    return titles, "fetched"


def tag_arcs(gloss_path: str, show_dir: str, override: str | None = None) -> dict:
    """Tag the glossary's names with the arcs of the show's seasons and store each arc's titles beside the tags.

    Additive and idempotent: tags are only added (glossary.tag_names_by_arc), an arc's stored titles are only unioned, and an
    unchanged glossary is not rewritten. An arc the wiki gives nothing for changes nothing [S-7] -- it is logged, never fatal,
    and cannot clear what other arcs established. The write is atomic (glossary_acquire._write_json). Returns a report; never
    raises."""
    import glossary

    try:
        gloss = json.load(open(gloss_path))
    except (OSError, ValueError) as e:
        return {"note": f"load-failed: {e}"}
    show = gloss.get("show") or os.path.splitext(os.path.basename(gloss_path))[0]
    rep = {"show": show, "arcs": 0, "fetched": 0, "cached": 0, "empty": 0, "names_tagged": 0, "written": False}
    arcs = arcs_in_show(show_dir)
    rep["arcs"] = len(arcs)
    if not arcs:
        return {**rep, "note": "no arcs"}
    api = resolve_wiki(show, override or gloss.get("wiki"))
    if not api:
        return {**rep, "note": "wiki unresolved (set a 'wiki' override)"}
    before = json.dumps(gloss, sort_keys=True)
    stopped = False
    for arc in arcs:
        if stop_requested():
            stopped = True
            break
        titles, how = fetch_arc_titles_cached(api, show, arc)
        if how == "empty":
            rep["empty"] += 1
            log(f"arc tags: no wiki titles for arc {arc!r} (not an arc, or the wiki is unreachable): nothing changed for it")
            continue
        rep[how] += 1
        glossary.tag_names_by_arc(gloss, arc, titles)
        stored = gloss.setdefault("arc_titles", {})
        stored[arc] = sorted(set(stored.get(arc, [])) | titles)
    rep["names_tagged"] = len(gloss.get("arc_tags") or {})
    if stopped:
        log("stop requested: leaving arc tagging; nothing written")
        return {**rep, "note": "stopped"}
    if json.dumps(gloss, sort_keys=True) == before:
        return rep
    from glossary_acquire import _write_json

    try:
        _write_json(gloss_path, gloss)
    except OSError as e:
        try:
            os.remove(gloss_path + ".tmp")
        except OSError:
            pass
        return {**rep, "note": f"write-failed: {e}"}
    return {**rep, "written": True}


def verify(gloss_path: str, override: str | None = None, force: bool = False) -> dict:
    """Orchestrate verification of one glossary file; returns a report. Resilient — any failure
    leaves the glossary unchanged and is reported in `note`, never raised.

    On a hosted backend the run opens by saying which fields go to which host; on the decision backend it ends with one
    summary line and the report gains `decision` (calls / ok / failures / fallbacks / pending). A term whose decision call
    failed with VERIFY_DECISION_FALLBACK=none stays pending (counted in the report's `pending`), not verified, not flagged."""
    usable = not backend_problem()
    if usable:
        begin_run("verify")
    rep = _verify(gloss_path, override, force)
    return end_run(rep) if usable else rep


def _verify(gloss_path: str, override: str | None = None, force: bool = False) -> dict:
    try:
        gloss = json.load(open(gloss_path))
    except (OSError, ValueError) as e:
        return {"note": f"load-failed: {e}"}
    show = gloss.get("show") or os.path.splitext(os.path.basename(gloss_path))[0]
    if force:
        gloss["verified"] = []
    terms = pending_terms(gloss)
    rep = {"show": show, "checked": 0, "applied": 0, "flagged": 0}
    if not terms:
        return {**rep, "note": "nothing pending"}
    problem = backend_problem()
    if problem:
        log(f"glossary verify refused: {problem}")
        return {**rep, "note": f"refused: {problem}"}
    pinned = override or gloss.get("wiki")
    api = resolve_wiki(show, pinned)
    if not api:
        return {**rep, "note": "wiki unresolved (set a 'wiki' override)"}
    titles = fetch_titles(api, show)
    if not titles:
        return {**rep, "wiki": api, "note": "no titles fetched"}
    # sanity gate (auto-resolved only): if NONE of the known names exist on this wiki, it's
    # almost certainly the wrong wiki — refuse to verify rather than corrupt the glossary.
    if not pinned and len(gloss.get("names", [])) >= 3:
        tl = {t.lower() for t in titles}
        if not any(n.lower() in tl for n in gloss.get("names", [])):
            return {**rep, "wiki": api, "note": "wiki mismatch (no known names found) — set a 'wiki' override"}

    # V2 C2: adjudicate() is one blocking HTTP call to the local Ollama server per term --
    # a glossary with dozens of pending terms serialized those one at a time. Run them
    # concurrently (I/O-bound, so threads are fine); ThreadPoolExecutor.map preserves the
    # input order in its output, so zipping it back onto `terms` keeps the exact same
    # dict ordering/semantics as the old comprehension, just built concurrently.
    # Soft stop (SIGTERM at window close): the flag is checked before each term's adjudication,
    # so a term is either fully adjudicated or skipped. Skipped terms are left out of `results`
    # and therefore stay pending (apply_results marks every term in it as verified); the next
    # sweep picks them up. Everything completed is written once, atomically, below.
    def _one(t):
        if stop_requested():
            return _STOPPED
        return adjudicate(t, candidates(t, titles), show)

    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count()) as ex:
        adjudications = list(ex.map(_one, terms))
    # None = the decision backend could not answer (fallback none): that term stays pending like a stopped one, but is not a stop.
    done = {t: a for t, a in zip(terms, adjudications) if a is not None and a is not _STOPPED}
    stopped = any(a is _STOPPED for a in adjudications)
    pending = sum(1 for a in adjudications if a is None)
    if stopped:
        log(f"stop requested: leaving verify after {len(done)} terms")
        if not done:
            return {**rep, "wiki": api, "note": "stopped"}
    if pending:
        log(f"{pending} of {len(terms)} terms left pending: the decision backend could not answer them")
        if not done:
            return {**rep, "wiki": api, "pending": pending, "note": "no adjudications (decision backend unavailable)"}
    results = done
    new = apply_results(gloss, results)
    new.setdefault("wiki", api)
    # Imported at call time for the same cycle reason as is_expansion below.
    from glossary_acquire import _write_json

    try:
        _write_json(gloss_path, new)
    except OSError as e:
        try:
            os.remove(gloss_path + ".tmp")
        except OSError:
            pass
        return {**rep, "wiki": api, "note": f"write-failed: {e}"}
    # Count what ACTUALLY happened, not what was proposed. Before 2026-08-21 every
    # high-confidence changed term was written straight into names/phrases, so "proposed"
    # and "applied" were the same number. They no longer are: a respelling is escalated,
    # not applied, and reporting it as applied would hide the escalation entirely.
    changed = [t for t, a in results.items() if a["confidence"] == "high" and a["canonical"] and a["canonical"] != t]
    universe = arc_universe(gloss)
    decisions = [write_decision(t, results[t]["canonical"], universe) for t in changed]
    applied = decisions.count("write")
    blocked = decisions.count("not-in-arc-pages")
    return {
        "show": show,
        "wiki": api,
        "checked": len(done),
        "applied": applied,
        "escalated": len(changed) - applied,
        **({"arc_gate": {"blocked": blocked, "universe": len(universe)}} if universe is not None else {}),
        "flagged": len(new.get("flagged", {})),
        **({"pending": pending} if pending else {}),
        **({"note": "stopped"} if stopped else {}),
    }


def main():
    ap = argparse.ArgumentParser(description="Wiki-verify a DubTitlerr glossary.")
    ap.add_argument("glossary", help="path to <show>.json")
    ap.add_argument("--wiki", help="override wiki URL/api.php")
    ap.add_argument("--force", action="store_true", help="re-verify all terms (ignore 'verified')")
    ap.add_argument(
        "--tag-arcs",
        metavar="SHOW_DIR",
        help="only tag the glossary's names with the arcs of SHOW_DIR's seasons (season.nfo) and store the arc titles; no verify",
    )
    a = ap.parse_args()
    if a.tag_arcs:
        log(json.dumps(tag_arcs(a.glossary, a.tag_arcs, a.wiki), ensure_ascii=False))
        sys.exit(0)
    rep = verify(a.glossary, a.wiki, a.force)
    log(json.dumps(rep, ensure_ascii=False))
    refusal_exit(rep)
    sys.exit(0)


if __name__ == "__main__":
    main()
