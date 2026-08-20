#!/usr/bin/env python3
"""Acquire proper nouns for a show whose releases carry no mineable subtitle track.

mine_glossary.py can only learn names from an embedded fansub track. Where a release
ships none, the glossary for that stretch of the show stays empty and every name is left
to Whisper's guessing. This module fills that gap from the opposite direction: the show's
wiki owns the candidate list AND every canonical spelling, and the show's own transcripts
only decide which wiki entities are worth asking about. Our errors can raise a question;
they can never become an answer.

See docs/superpowers/specs/2026-08-19-glossary-name-acquisition-design.md.
Built with help of Claude (Anthropic).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re

import jellyfish

import glossary
import glossary_verify
import mine_glossary
from common import llm_chat, log

_DISAMBIG_RE = re.compile(r"\s*\([^)]*\)\s*$")
_REDUCE_RE = re.compile("[\\s" + chr(0x27) + chr(0x2019) + "-]")


def normalize_title(title: str) -> str:
    """A wiki article title reduced to the name itself.

    Fandom titles carry disambiguators and subpages -- 'Misty (anime)',
    'Ash Ketchum/Sun & Moon'. Both are part of the TITLE, not the name, and emitting one
    as a hard_fix canonical would rewrite dialogue to include it."""
    return _DISAMBIG_RE.sub("", str(title).split("/")[0]).strip()


def reduce_form(s: str) -> str:
    """The form both sides are compared on: lowercase, no spaces/apostrophes/hyphens.

    This is what lets the ASR token 'Vanderdecken' match the title 'Van der Decken'.
    The class is built with chr() rather than written literally: the curly apostrophe
    U+2019 gets silently normalised to U+0027 by editors in this toolchain, which
    silently disables curly-apostrophe stripping and passes a literal-looking review."""
    return _REDUCE_RE.sub("", str(s).lower())


def wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    """Wilson score lower bound on k/n at ~95% confidence.

    Used instead of a bare ratio because a ratio cannot tell 5-vs-1 from 56-vs-2 -- both
    look lopsided, but only one is evidence. Wilson discounts the small sample for us."""
    if n <= 0:
        return 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom


EXPANSION_RATIO = 1.35


def is_expansion(variant: str, canonical: str) -> bool:
    """True if 'correcting' variant->canonical would GROW a word into a longer name.

    A canonical that merely CONTAINS the variant is not a match: the transcript says
    'Warlords', the wiki title is 'Seven Warlords of the Sea', and substituting one for the
    other rewrites the line into nonsense. Length ratio catches the rest ('Ace' ->
    'Portgas D. Ace'), while a true respelling stays about the same length."""
    v, c = reduce_form(variant), reduce_form(canonical)
    if not v or not c:
        return True
    if v == c:
        return False
    if v in c and len(c) > len(v):
        return True
    return len(c) > len(v) * EXPANSION_RATIO


MIN_SIM = float(os.environ.get("ACQUIRE_MIN_SIM", "0.72"))


def similarity(a: str, b: str) -> float:
    """Jaro-Winkler on the reduced forms, nudged when a phonetic key agrees.

    RECALL, not safety. Measured on real data the true and false pairs overlap completely
    (Syrahose/Shirahoshi 0.755 sits BELOW Warlords/Warlord 0.975), so no threshold here can
    separate them and none is asked to -- R2 and R3 do the rejecting. The phonetic key is a
    bonus signal only: exact metaphone bucketing was tried and split Shirahoshi/Syrahose
    into XRHX/SRHS, dropping the case this module exists for."""
    ra, rb = reduce_form(a), reduce_form(b)
    if not ra or not rb:
        return 0.0
    score = jellyfish.jaro_winkler_similarity(ra, rb)
    if jellyfish.metaphone(ra) == jellyfish.metaphone(rb) or jellyfish.soundex(ra) == jellyfish.soundex(rb):
        score = min(1.0, score + 0.02)
    return score


def best_title(token: str, titles: list) -> tuple[str, float]:
    """(normalised title, score) of the closest title above MIN_SIM, else ('', 0.0)."""
    best, best_score = "", 0.0
    for t in titles:
        norm = normalize_title(t)
        if not norm:
            continue
        s = similarity(token, norm)
        if s > best_score:
            best, best_score = norm, s
    return (best, best_score) if best_score >= MIN_SIM else ("", 0.0)


CONF_SUFFIX = ".dubtitles.conf.json"
SRT_SUFFIX = ".eng.dubtitles.srt"


def _conf_text(path: str) -> str:
    """All dialogue text from one conf.json, newline-joined, or '' if unreadable."""
    try:
        rows = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(rows, list):
        return ""
    return "\n".join(str(r.get("text", "")) for r in rows if isinstance(r, dict))


def _srt_text(path: str) -> str:
    """Dialogue lines from an SRT: drop indices and timecodes, keep the rest."""
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
    out = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s or s.isdigit() or "-->" in s:
            continue
        out.append(s)
    return "\n".join(out)


def _iter_episode_texts(show_dir: str):
    """(stem, text) for each episode, conf.json preferred over the SRT fallback.

    One source per episode stem, never both: sorted(fs) puts '.dubtitles.conf.json'
    before '.eng.dubtitles.srt' for a shared stem because 'd' < 'e'."""
    stems_done = set()
    for dp, _dns, fs in os.walk(show_dir):
        for fn in sorted(fs):
            if fn.endswith(CONF_SUFFIX):
                stem, text = os.path.join(dp, fn[:-len(CONF_SUFFIX)]), _conf_text(os.path.join(dp, fn))
            elif fn.endswith(SRT_SUFFIX):
                stem, text = os.path.join(dp, fn[:-len(SRT_SUFFIX)]), _srt_text(os.path.join(dp, fn))
            else:
                continue
            if stem in stems_done or not text:
                continue
            stems_done.add(stem)
            yield stem, text


def harvest(show_dir: str) -> tuple[dict, set, int]:
    """(counts, midsentence, n_files) of capitalised tokens across the show's own output.

    conf.json is preferred; the SRT is the fallback for episodes whose conf is gone (104 of
    696 stamped episodes at time of writing). One source per episode stem, never both."""
    counter: dict = {}
    mid: set = set()
    files = 0
    for _stem, text in _iter_episode_texts(show_dir):
        files += 1
        mine_glossary.mine_text(text, counter, mid)
    return counter, mid, files


CONTEXT_LINES = int(os.environ.get("ACQUIRE_CONTEXT_LINES", "4"))


def context_lines(show_dir: str, tokens: list, limit: int = CONTEXT_LINES) -> dict:
    """Up to `limit` real transcript lines containing each token, whole-word matched.

    Whole-word is required: 'Hoshi' must not match inside 'Shirahoshi', or the evidence
    shown to the model (and to the human) would be about a different name."""
    pats = {t: re.compile(r"\b" + re.escape(t) + r"\b") for t in tokens}
    out: dict = {t: [] for t in tokens}
    for _stem, text in _iter_episode_texts(show_dir):
        for ln in text.splitlines():
            for t, pat in pats.items():
                if len(out[t]) < limit and pat.search(ln):
                    out[t].append(ln.strip())
        if all(len(v) >= limit for v in out.values()):
            return out
    return out


def build_merge_prompt(variant: str, canonical: str, ctx_v: list, ctx_c: list, show: str) -> str:
    """Ask whether two spellings are one entity mis-transcribed or two legitimate forms.

    The model never supplies a spelling -- it answers yes/no about merging. The canonical
    string is already fixed by the wiki, which is what keeps R1 intact at this tier."""
    lines_v = "\n".join(f"  - {ln}" for ln in ctx_v) or "  (none)"
    lines_c = "\n".join(f"  - {ln}" for ln in ctx_c) or "  (none)"
    return (
        f"Two spellings appear in the English dub of {show}. Decide whether they are the SAME "
        f"name mis-transcribed, or two DIFFERENT legitimate forms (a nickname, a title, or a "
        f"separate character).\n\n"
        f'Spelling A: "{variant}"\n{lines_v}\n\n'
        f'Spelling B: "{canonical}"\n{lines_c}\n\n'
        f"A nickname the characters actually use is NOT a mis-transcription.\n"
        f'Answer with JSON only: {{"same_entity": true|false, "confidence": "high"|"low"}}\n')


def adjudicate_merge(variant: str, canonical: str, ctx_v: list, ctx_c: list, show: str) -> dict:
    """LLM merge decision -> {'same_entity': bool, 'confidence': 'high'|'low'|'none'}."""
    none = {"same_entity": False, "confidence": "none"}
    try:
        out = llm_chat(build_merge_prompt(variant, canonical, ctx_v, ctx_c, show),
                       backend=glossary_verify.VERIFY_BACKEND, ollama_url=glossary_verify.OLLAMA,
                       llamacpp_url=glossary_verify.VERIFY_LLAMACPP_URL,
                       model=glossary_verify.VERIFY_MODEL,
                       max_tokens=glossary_verify.VERIFY_MAX_TOKENS, first_line=False)
    except Exception as e:
        log("acquire: merge adjudication failed:", variant, e); return none
    if not out:
        return none
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return none
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return none
    conf = str(d.get("confidence", "none")).lower()
    return {"same_entity": d.get("same_entity") is True,
            "confidence": conf if conf in ("high", "low", "none") else "low"}


def escalate(proposals: list, ctx: dict, show: str) -> list:
    """Re-decide share-too-close proposals with context. Other verdicts pass through.

    ONLY share-too-close escalates. below-floor, sentence-initial-only, already-canonical,
    english-word and short-form never do: none of those verdicts is evidence-shaped, and
    short-form (an expansion) is structurally wrong -- no amount of context evidence redeems it."""
    out = []
    for p in proposals:
        if p.get("reason") != "share-too-close":
            out.append(p); continue
        adj = adjudicate_merge(p["variant"], p["canonical"],
                               ctx.get(p["variant"], []), ctx.get(p["canonical"], []), show)
        if adj["same_entity"] and adj["confidence"] == "high":
            out.append({**p, "verdict": "apply", "reason": "context-merged"})
        elif not adj["same_entity"] and adj["confidence"] == "high":
            out.append({**p, "verdict": "known", "reason": "context-distinct"})
        else:
            out.append(p)
    return out


MIN_COUNT = int(os.environ.get("ACQUIRE_MIN_COUNT", "3"))
MIN_SHARE = float(os.environ.get("ACQUIRE_MIN_SHARE", "0.80"))


def decide(variant: str, variant_count: int, canonical: str, canonical_count: int,
           score: float, midsentence: bool) -> dict:
    """Run the four gates over one variant->canonical proposal.

    Order matters: the cheap structural rejections come first so the report's reason is the
    most specific true one. R2 (expansion) and R3 (dominance) are the only gates carrying
    real safety -- `score` is a recall floor that has already been applied upstream."""
    if variant_count + canonical_count < MIN_COUNT:
        return {"verdict": "flag", "reason": "below-floor", "bound": 0.0}
    if not midsentence:
        return {"verdict": "flag", "reason": "sentence-initial-only", "bound": 0.0}
    if is_expansion(variant, canonical):
        return {"verdict": "known", "reason": "short-form", "bound": 0.0}
    if variant == canonical:
        return {"verdict": "flag", "reason": "already-canonical", "bound": 0.0}
    if canonical_count == 0:
        return {"verdict": "apply", "reason": "canonical-unseen", "bound": 0.0}
    bound = wilson_lower(canonical_count, canonical_count + variant_count)
    if bound > MIN_SHARE:
        return {"verdict": "apply", "reason": "dominant", "bound": bound}
    return {"verdict": "flag", "reason": "share-too-close", "bound": bound}


def propose(counts: dict, midsentence: set, titles: list) -> list:
    """One proposal per harvested token that resolves to a wiki title.

    A token matching no title yields nothing here -- it is the tier-B queue's business
    (see acquire()), not a silent drop. An ordinary English variant is flagged rather than
    applied or dropped: dialogue words like 'name' can score deceptively close to a real
    name (JW('name','nami') = 0.90), but real characters ARE English words too (Brook, Law),
    so a human reviewer -- not a silent drop -- gets the final call. The canonical itself is
    exempt: it comes from the wiki and is authoritative."""
    resolved = {}
    for tok in counts:
        name, score = best_title(tok, titles)
        if name:
            resolved[tok] = (name, score)
    out = []
    for tok, (canon, score) in sorted(resolved.items()):
        canon_count = counts.get(canon, 0)
        d = decide(tok, counts[tok], canon, canon_count, score, tok in midsentence)
        if d["reason"] == "already-canonical":
            continue
        if glossary.is_english(tok.lower()):
            d = {"verdict": "flag", "reason": "english-word", "bound": 0.0}
        out.append({"variant": tok, "canonical": canon, "variant_count": counts[tok],
                    "canonical_count": canon_count, "score": round(score, 3), **d})
    return out


def unmatched(counts: dict, midsentence: set, titles: list) -> list:
    """Frequent, mid-sentence tokens that resolved to no wiki title at all.

    This is the dub-only-name queue: a character the dub renamed outright ('Ash' where the
    wiki is titled in romaji) matches nothing phonetically, which is a MISS, never a
    corruption. Tier B asks the wiki's full-text search about these."""
    return sorted(t for t, c in counts.items()
                  if c >= MIN_COUNT and t in midsentence and not best_title(t, titles)[0])


def apply_proposals(gloss: dict, proposals: list, run_id: str) -> dict:
    """Write applied proposals into hard_fixes + acquired; record the rest in flagged.

    Pure: deep-copies its input the way glossary_verify.apply_results does, so curated
    hard_fixes, names and initial_prompt survive untouched.

    Acquired canonicals deliberately do NOT join `names`, and therefore never reach the
    regenerated initial_prompt. That is the cut that keeps a wrong entry from biasing the
    next transcription into producing more of the same spelling -- which would raise its
    count and reinforce the dominance test that let it in."""
    g = json.loads(json.dumps(gloss))
    fixes = g.setdefault("hard_fixes", {})
    acquired = g.setdefault("acquired", {})
    flagged = g.setdefault("flagged", {})
    known = set(g.get("known", []))
    for p in proposals:
        if p["verdict"] == "known":
            known.add(p["variant"]); continue
        if p["verdict"] != "apply":
            flagged[p["variant"]] = {"reason": p["reason"], "canonical": p["canonical"],
                                     "variant_count": p["variant_count"], "canonical_count": p["canonical_count"],
                                     "score": p["score"], "bound": round(p.get("bound", 0.0), 3),
                                     "context": p.get("context", [])}
            continue
        fixes[p["variant"]] = p["canonical"]
        acquired[p["variant"]] = {"canonical": p["canonical"], "count": p["variant_count"],
                                  "canonical_count": p["canonical_count"],
                                  "score": p["score"], "bound": round(p.get("bound", 0.0), 3),
                                  "reason": p["reason"], "run": run_id}
    if not flagged:
        g.pop("flagged", None)
    if known:
        g["known"] = sorted(known)
    else:
        g.pop("known", None)
    return g


def revert(gloss: dict, run_id: str | None = None) -> dict:
    """Remove hard_fixes this module wrote, restoring the pre-acquisition glossary.

    A fix whose current value no longer matches what we recorded has been edited by hand
    since; leave it alone and drop only our provenance for it."""
    g = json.loads(json.dumps(gloss))
    fixes, acquired = g.get("hard_fixes", {}), g.get("acquired", {})
    for variant, meta in list(acquired.items()):
        if run_id is not None and meta.get("run") != run_id:
            continue
        if fixes.get(variant) == meta.get("canonical"):
            fixes.pop(variant, None)
        acquired.pop(variant, None)
    return g


def review_items(gloss: dict) -> list:
    """The pending review queue, normalised.

    glossary_verify writes bare strings; this module writes objects. Both load, so the
    queue that has been accumulating unread since the verifier shipped is reviewable too."""
    out = []
    for term, meta in sorted((gloss.get("flagged") or {}).items()):
        if isinstance(meta, str):
            meta = {"reason": meta}
        out.append({"term": term, "reason": meta.get("reason", ""),
                    "canonical": meta.get("canonical", ""),
                    "variant_count": meta.get("variant_count", 0),
                    "canonical_count": meta.get("canonical_count", 0),
                    "bound": meta.get("bound", 0.0), "context": meta.get("context", [])})
    return out


def record_decision(gloss: dict, term: str, accept: bool) -> dict:
    """Apply one human decision and drop the term from the queue for good."""
    g = json.loads(json.dumps(gloss))
    meta = (g.get("flagged") or {}).get(term)
    if isinstance(meta, str):
        meta = {"reason": meta}
    meta = meta or {}
    canon = meta.get("canonical", "")
    if accept and canon:
        g.setdefault("hard_fixes", {})[term] = canon
        g.setdefault("acquired", {})[term] = {"canonical": canon, "count": meta.get("variant_count", 0),
                                              "canonical_count": meta.get("canonical_count", 0),
                                              "score": meta.get("score", 0.0), "bound": meta.get("bound", 0.0),
                                              "reason": "human-approved", "run": "review"}
    else:
        g["known"] = sorted(set(g.get("known", [])) | {term})
    g.get("flagged", {}).pop(term, None)
    if not g.get("flagged"):
        g.pop("flagged", None)
    return g


def acquire(gloss_path: str, show_dir: str, apply: bool = False, override: str | None = None) -> dict:
    """Harvest -> score -> gate -> (optionally) write. Returns a report; never raises.

    Resilient by the same contract as glossary_verify.verify(): any wiki, LLM or IO failure
    leaves the glossary untouched and is reported, not raised."""
    try:
        gloss = json.load(open(gloss_path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"note": f"load-failed: {e}"}
    show = gloss.get("show") or os.path.basename(gloss_path)[:-5]
    counts, mid, files = harvest(show_dir)
    api = glossary_verify.resolve_wiki(show, override or gloss.get("wiki"))
    if not api:
        return {"show": show, "note": "wiki unresolved", "files": files}
    if not counts:
        return {"show": show, "wiki": api, "note": "nothing harvested", "files": files}
    try:
        titles = glossary_verify.fetch_titles(api, show)
    except Exception as e:
        return {"show": show, "wiki": api, "note": f"titles-failed: {e}", "files": files}
    if not titles:
        return {"show": show, "wiki": api, "note": "no titles fetched", "files": files}
    proposals = propose(counts, mid, titles)
    close = [p for p in proposals if p.get("reason") == "share-too-close"]
    if close:
        toks = sorted({p["variant"] for p in close} | {p["canonical"] for p in close})
        proposals = escalate(proposals, context_lines(show_dir, toks), show)
    tier_b = {}
    for term in unmatched(counts, mid, titles):
        try:
            adj = glossary_verify.adjudicate(term, glossary_verify.candidates(term, titles), show)
        except Exception as e:
            log("acquire: adjudicate failed:", term, e); continue
        if adj.get("confidence") == "high" and adj.get("canonical"):
            tier_b[term] = adj["canonical"]
    applied = [p for p in proposals if p["verdict"] == "apply"]
    known = [p for p in proposals if p["verdict"] == "known"]
    flagged = [p for p in proposals if p["verdict"] == "flag"]
    digest = hashlib.sha1("|".join(f"{p['variant']}>{p['canonical']}" for p in sorted(
        proposals, key=lambda p: p["variant"])).encode()).hexdigest()[:8]
    run_id = f"{show}:{len(titles)}:{files}:{digest}"
    if apply and (proposals or tier_b):
        tmp = gloss_path + ".tmp"
        try:
            out = apply_proposals(gloss, proposals, run_id)
            if tier_b:
                tctx = context_lines(show_dir, list(tier_b))
                flagged = out.setdefault("flagged", {})
                for term, canon in tier_b.items():
                    flagged[term] = {"reason": "no-wiki-match", "canonical": canon,
                                     "variant_count": counts.get(term, 0), "canonical_count": 0,
                                     "bound": 0.0, "context": tctx.get(term, [])}
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2, ensure_ascii=False)
            os.replace(tmp, gloss_path)
        except Exception as e:
            try: os.remove(tmp)
            except OSError: pass
            return {"show": show, "wiki": api, "note": f"write-failed: {e}", "files": files}
    return {"show": show, "wiki": api, "files": files, "titles": len(titles),
            "proposed": len(proposals), "applied": len(applied), "known": len(known),
            "flagged": len(flagged), "dry_run": not apply,
            "proposals": proposals, "tier_b": tier_b}


def main():
    ap = argparse.ArgumentParser(description="Acquire proper nouns from a show's own output + its wiki.")
    ap.add_argument("glossary", help="path to <show>.json")
    ap.add_argument("show_dir", help="the show's media directory")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--wiki", default=None, help="override the wiki API base")
    ap.add_argument("--revert", action="store_true", help="undo previously acquired fixes and exit")
    ap.add_argument("--review", action="store_true", help="walk the pending queue interactively")
    a = ap.parse_args()
    if a.review:
        g = json.load(open(a.glossary, encoding="utf-8"))
        for item in review_items(g):
            log(f"\n{item['term']}  ->  {item['canonical'] or '(no canonical)'}   [{item['reason']}]")
            log(f"  seen {item['variant_count']}x vs canonical {item['canonical_count']}x, bound {item['bound']:.3f}")
            for ln in item["context"]:
                log(f"    | {ln}")
            ans = input("  accept this fix? [y/N/q] ").strip().lower()
            if ans == "q":
                break
            g = record_decision(g, item["term"], accept=(ans == "y"))
        if a.apply:
            json.dump(g, open(a.glossary, "w"), indent=2, ensure_ascii=False)
        log(json.dumps({"reviewed": True, "written": a.apply, "pending": len(g.get("flagged", {}))}))
        return
    if a.revert:
        g = json.load(open(a.glossary, encoding="utf-8"))
        out = revert(g)
        if a.apply:
            json.dump(out, open(a.glossary, "w"), indent=2, ensure_ascii=False)
        log(json.dumps({"reverted": len(g.get("acquired", {})), "written": a.apply}))
        return
    rep = acquire(a.glossary, a.show_dir, apply=a.apply, override=a.wiki)
    for p in rep.get("proposals", []):
        log(f"{p['verdict']:5} {p['variant']:18} -> {p['canonical']:22} "
            f"seen {p['variant_count']:4}/{p['canonical_count']:<4} sim {p['score']:.3f} "
            f"bound {p.get('bound', 0.0):.3f}  {p['reason']}")
    log(json.dumps({k: v for k, v in rep.items() if k != "proposals"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
