#!/usr/bin/env python3
"""Glossary wiki-verifier — make any glossary's proper-noun spellings as accurate as the
hand-tuned One Pace one, automatically.

Hybrid approach: fetch the show's wiki main-namespace page index (Fandom MediaWiki API),
pre-match each glossary term to the top-K similar titles (deterministic), then a local LLM
(qwen3:8b) picks the canonical entity and prefers the DUB spelling. High-confidence matches
are applied to the glossary; low-confidence / no-match terms are kept and flagged for review.
Incremental (a ``verified`` set skips re-checks) and cached (page index per show). Resilient:
any wiki/LLM failure is a no-op, never stalls the pipeline.

Reusable module + CLI — called by the mining hook in gen_loop, a standalone command, and
future community-repo front-ends. Source of truth = wiki/publisher (dub-preferred). See
specs/glossary-wiki-verify/spec.md.  Built with help of Claude (Anthropic).
"""
from __future__ import annotations

import difflib
import json
import os
import re
import time
import urllib.parse
import urllib.request

TOPK = 6                  # candidate titles per term handed to the LLM
CAND_CUTOFF = 0.5         # min similarity for a title to be a candidate
VERIFY_MODEL = os.environ.get("VERIFY_MODEL", "qwen3:8b")
OLLAMA = os.environ.get("OLLAMA_URL", "http://ollama.local:11434/api/generate")
CACHE_DIR = os.environ.get("WIKI_CACHE_DIR", "/config/wiki_cache")
HTTP_TIMEOUT = int(os.environ.get("WIKI_HTTP_TIMEOUT", "20"))
WIKI_TTL = int(os.environ.get("WIKI_CACHE_TTL", str(30 * 24 * 3600)))   # refresh index monthly


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
        "spelling and say so in dub_note. If no candidate is the same entity, return no match.\n"
        'Reply ONLY as JSON: {"canonical": "<spelling or empty>", '
        '"confidence": "high|low|none", "dub_note": "<short or empty>"}')


def adjudicate(term: str, cands: list[str], show: str) -> dict:
    """LLM pick -> {'canonical': str, 'confidence': 'high'|'low'|'none', 'dub_note': str}."""
    raise NotImplementedError


def apply_results(gloss: dict, results: dict) -> dict:
    """Apply per-term adjudications: write high-confidence canonical (dub-preferred) spellings into
    names/phrases, flag low/no-match, mark every processed term `verified`. Pure; preserves unknown
    fields (curated hard_fixes, initial_prompt, wiki, …) by deep-copying the input."""
    g = json.loads(json.dumps(gloss))
    names, phrases = g.setdefault("names", []), g.setdefault("phrases", [])
    verified = set(g.get("verified", []))
    flagged = dict(g.get("flagged", {}))
    for term, adj in results.items():
        verified.add(term)
        canon = (adj or {}).get("canonical") or ""
        conf = (adj or {}).get("confidence", "none")
        if conf == "high" and canon and canon != term:
            for lst in (names, phrases):
                for i, x in enumerate(lst):
                    if x == term:
                        lst[i] = canon
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
    u = (api + "?action=query&list=allpages&apnamespace=0&aplimit=500"
         "&apfilterredir=nonredirects&format=json")
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
    for _ in range(40):                          # page cap (40 * 500 = 20k titles)
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


def verify(gloss_path: str, override: str | None = None, force: bool = False) -> dict:
    """Orchestrate verification of one glossary file; returns a report. Resilient."""
    raise NotImplementedError
