#!/usr/bin/env python3
"""Glossary-stage bake-off, phase 1: build the offline item set.

Two glossary stages ask a local LLM one small question per term: `glossary_verify.adjudicate` (which
wiki title is the same entity as this mined term) and `glossary_acquire.adjudicate_merge` (are these two
spellings one entity). This tool turns a COPY of the glossaries, the acquire caches and the wiki title
caches into `items.jsonl`, the fixed question set a later `run` / `score` will put to other models. See
specs/glossary-decision-bakeoff/spec.md.

  python3 tools/glossary_bakeoff.py build-set --glossaries DIR --wiki-cache DIR --out items.jsonl [--show TEXT ...]

Offline by construction: no network, no model, no production module changed. The candidate list of every
verify item is recomputed with the production `glossary_verify.candidates` (TOPK 6, cutoff 0.62), so what a
model is asked is what production would have asked.

What counts as a verify item. Production (`glossary_verify.verify`) adjudicates `pending_terms(gloss)`: every
name and phrase not yet in `verified`, or all of them under `--force`. A live glossary has mostly been verified
already, so the set takes ALL names and phrases (what --force sends) and records `verified` and `flagged` on
each item; the term's origin is its `list` ("names" or "phrases"). A term with no candidates is kept with
`no_call: true`: production returns "none" for it without a model call, so it is a control, not a question.

Gold. Only for shows with `_curated` true, and only where a curated spelling (any name, phrase or hard_fixes
target of that glossary) equals, casefolded, one of the item's candidate titles. If several candidates
qualify the exact term wins, otherwise the one production ranked first, and `gold_ambiguous` is set.
Everything else has `gold: null`. No label is invented.

Acquire items are the cached pairs of `<show>.acquire-cache.json`: the two spellings and the local model's
historical verdict. The transcript quotes are not available offline, so `quotes` is null.

Re-running on the same input gives byte-identical output."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys

sys.path.insert(0, ".")
import acquire_cache  # noqa: E402
import glossary_verify  # noqa: E402

LASTRUN = ".lastrun.json"
GLOSSARY_GLOB_EXCLUDE = (LASTRUN, acquire_cache.SUFFIX)


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


def _curated_spellings(gloss):
    spellings = [*gloss.get("names", []), *gloss.get("phrases", [])]
    hard = gloss.get("hard_fixes")
    if isinstance(hard, dict):
        spellings += [v for v in hard.values() if isinstance(v, str)]
    return {s.casefold() for s in spellings if isinstance(s, str)}


def _gold(term, cand_titles, gloss):
    """(gold title, ambiguous) for a curated glossary, else (None, False)."""
    if not gloss.get("_curated"):
        return None, False
    canon = _curated_spellings(gloss)
    hits = [t for t in cand_titles if t.casefold() in canon]
    if not hits:
        return None, False
    exact = [t for t in hits if t.casefold() == term.casefold()]
    return (exact or hits)[0], len(hits) > 1


def verify_items(gloss, show, titles):
    """One item per name/phrase, candidates from the PRODUCTION function in production order."""
    names, phrases = gloss.get("names", []), gloss.get("phrases", [])
    verified = set(gloss.get("verified", []) if isinstance(gloss.get("verified"), list) else [])
    flagged = gloss.get("flagged") if isinstance(gloss.get("flagged"), dict) else {}
    acquired = gloss.get("acquired") or ()
    items = []
    # pending_terms with nothing verified == names then phrases, deduplicated: what `verify --force` sends.
    for term in glossary_verify.pending_terms({"names": names, "phrases": phrases}):
        cand_titles = glossary_verify.candidates(term, titles)
        gold, ambiguous = _gold(term, cand_titles, gloss)
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
            "gold": gold,
        }
        if gold is not None:
            item["gold_source"] = "curated"
            if ambiguous:
                item["gold_ambiguous"] = True
        items.append(item)
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


def build_set(gloss_dir, wiki_dir, filters=()):
    """(items, per-show stats, skipped notes). Pure with respect to its inputs; never raises on bad data."""
    items, stats, skipped = [], {}, []
    stems_with_glossary = set()
    for fname in _glossary_files(gloss_dir):
        stem = fname[: -len(".json")]
        stems_with_glossary.add(stem)
        gloss, err = _read_json(os.path.join(gloss_dir, fname))
        if err or not isinstance(gloss, dict):
            if _wanted(stem, stem, filters):
                skipped.append((stem, f"glossary skipped: {err or 'not a JSON object'}"))
            continue
        show = gloss.get("show") if isinstance(gloss.get("show"), str) and gloss.get("show") else stem
        if not _wanted(show, stem, filters):
            continue
        row = stats.setdefault(show, {"verify": 0, "with_candidates": 0, "no_call": 0, "with_gold": 0, "acquire": 0})
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
                    vi = verify_items(gloss, show, titles)
                    items += vi
                    row["verify"] = len(vi)
                    row["with_candidates"] = sum(1 for i in vi if not i["no_call"])
                    row["no_call"] = sum(1 for i in vi if i["no_call"])
                    row["with_gold"] = sum(1 for i in vi if i["gold"] is not None)
        _acquire_for(os.path.join(gloss_dir, stem + acquire_cache.SUFFIX), show, row, items, skipped)
    # acquire caches whose glossary file is missing: the show is the file stem
    for fname in sorted(os.listdir(gloss_dir)):
        if fname.endswith(acquire_cache.SUFFIX):
            stem = fname[: -len(acquire_cache.SUFFIX)]
            if stem not in stems_with_glossary and _wanted(stem, stem, filters):
                row = stats.setdefault(stem, {"verify": 0, "with_candidates": 0, "no_call": 0, "with_gold": 0, "acquire": 0})
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


def _summary(stats, skipped, n_items):
    cols = ("verify", "with_candidates", "no_call", "with_gold", "acquire")
    head = f"{'show':<44} {'verify':>7} {'w/cands':>8} {'no_call':>8} {'w/gold':>7} {'acquire':>8}"
    lines = [head, "-" * len(head)]
    for show in sorted(stats):
        r = stats[show]
        lines.append(f"{show[:44]:<44} " + " ".join(f"{r[c]:>{w}}" for c, w in zip(cols, (7, 8, 8, 7, 8), strict=True)))
    tot = {c: sum(r[c] for r in stats.values()) for c in cols}
    lines.append("-" * len(head))
    lines.append(f"{'TOTAL':<44} " + " ".join(f"{tot[c]:>{w}}" for c, w in zip(cols, (7, 8, 8, 7, 8), strict=True)))
    lines.append(f"{n_items} items written")
    lines.append(f"skipped: {len(skipped)}")
    lines += [f"  - {show}: {why}" for show, why in skipped]
    return "\n".join(lines)


def cmd_build_set(a):
    items, stats, skipped = build_set(a.glossaries, a.wiki_cache, a.show or ())
    text = "".join(json.dumps(i, ensure_ascii=False, sort_keys=False) + "\n" for i in items)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(_summary(stats, skipped, len(items)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Glossary-stage bake-off (phase 1: build the offline item set).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    bs = sub.add_parser("build-set", help="write items.jsonl from copies of the glossaries and wiki caches")
    bs.add_argument("--glossaries", required=True, help="directory of <show>.json and <show>.acquire-cache.json copies")
    bs.add_argument("--wiki-cache", required=True, help="directory of wiki title caches (<show_key>.json)")
    bs.add_argument("--out", required=True, help="items.jsonl to write")
    bs.add_argument("--show", nargs="+", metavar="SUBSTRING", help="only shows whose name contains one of these (casefolded)")
    a = ap.parse_args(argv)
    for flag in ("glossaries", "wiki_cache"):
        if not os.path.isdir(getattr(a, flag)):
            ap.error(f"--{flag.replace('_', '-')}: {getattr(a, flag)!r} is not a directory")
    return cmd_build_set(a)


if __name__ == "__main__":
    sys.exit(main())
