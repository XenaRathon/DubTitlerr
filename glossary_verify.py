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

from common import llm_chat


def log(*a):
    print(*a, flush=True)


TOPK = 6  # candidate titles per term handed to the LLM
CAND_CUTOFF = 0.62  # min similarity for a candidate (0.5 let junk like blarghxyzqq->Largo in)
VERIFY_MODEL = os.environ.get("VERIFY_MODEL", "qwen3:8b")
OLLAMA = os.environ.get("OLLAMA_URL", "http://ollama.local:11434/api/generate")
# VERIFY_BACKEND (ollama|llamacpp) lets adjudication run on the same server as repair, so
# the whole pipeline can sit on one model instead of keeping a second one resident on a
# shared 8 GB GPU. Defaults follow REPAIR_* so setting the repair backend moves this too,
# unless it is overridden explicitly.
VERIFY_BACKEND = os.environ.get("VERIFY_BACKEND", os.environ.get("REPAIR_BACKEND", "ollama"))
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


def adjudicate(term: str, cands: list[str], show: str) -> dict:
    """LLM pick -> {'canonical': str, 'confidence': 'high'|'low'|'none', 'dub_note': str}."""
    if not cands:
        return {"canonical": "", "confidence": "none", "dub_note": ""}
    out = llm_chat(
        build_adjudication_prompt(term, cands, show),
        backend=VERIFY_BACKEND,
        ollama_url=OLLAMA,
        llamacpp_url=VERIFY_LLAMACPP_URL,
        model=VERIFY_MODEL,
        max_tokens=VERIFY_MAX_TOKENS,
        first_line=False,
    )
    if not out:
        return {"canonical": "", "confidence": "none", "dub_note": ""}
    return parse_adjudication(out)


def _shape_list(names: list, phrases: list, term: str) -> list:
    """Which list a term belongs in BY SHAPE. `names` feeds glossary.correct()'s per-token
    tiers (`_TOKEN_RE` matches one token), so a multi-word string there can never match; the
    multi-word path is `phrases`, which feeds repair's term list."""
    return phrases if " " in term.strip() else names


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
    for term, adj in results.items():
        verified.add(term)
        canon = (adj or {}).get("canonical") or ""
        conf = (adj or {}).get("confidence", "none")
        if conf == "high" and canon and canon != term:
            # Imported at call time, NOT at module scope: glossary_acquire imports this
            # module, so a top-level import is a hard cycle (ImportError on the
            # acquire-first order only -- verify-first appears to work, which is exactly
            # how it would reach production unnoticed).
            from glossary_acquire import is_expansion

            if is_expansion(term, canon):
                dest = _shape_list(names, phrases, canon)
                if canon not in dest:
                    dest.append(canon)  # ADD -- the term itself is left in place
            else:
                flagged[term] = {"reason": "respelling-needs-review", "canonical": canon}
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


def verify(gloss_path: str, override: str | None = None, force: bool = False) -> dict:
    """Orchestrate verification of one glossary file; returns a report. Resilient — any failure
    leaves the glossary unchanged and is reported in `note`, never raised."""
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
    with concurrent.futures.ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as ex:
        adjudications = ex.map(lambda t: adjudicate(t, candidates(t, titles), show), terms)
        results = dict(zip(terms, adjudications))
    new = apply_results(gloss, results)
    new.setdefault("wiki", api)
    try:
        with open(gloss_path, "w", encoding="utf-8") as f:
            json.dump(new, f, indent=2, ensure_ascii=False)
            f.write("\n")  # POSIX line: prettier flags a glossary without it
    except OSError as e:
        return {**rep, "wiki": api, "note": f"write-failed: {e}"}
    # Count what ACTUALLY happened, not what was proposed. Before 2026-08-21 every
    # high-confidence changed term was written straight into names/phrases, so "proposed"
    # and "applied" were the same number. They no longer are: a respelling is escalated,
    # not applied, and reporting it as applied would hide the escalation entirely.
    from glossary_acquire import is_expansion

    changed = [t for t, a in results.items() if a["confidence"] == "high" and a["canonical"] and a["canonical"] != t]
    applied = sum(1 for t in changed if is_expansion(t, results[t]["canonical"]))
    return {
        "show": show,
        "wiki": api,
        "checked": len(terms),
        "applied": applied,
        "escalated": len(changed) - applied,
        "flagged": len(new.get("flagged", {})),
    }


def main():
    ap = argparse.ArgumentParser(description="Wiki-verify a DubTitlerr glossary.")
    ap.add_argument("glossary", help="path to <show>.json")
    ap.add_argument("--wiki", help="override wiki URL/api.php")
    ap.add_argument("--force", action="store_true", help="re-verify all terms (ignore 'verified')")
    a = ap.parse_args()
    rep = verify(a.glossary, a.wiki, a.force)
    log(json.dumps(rep, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
