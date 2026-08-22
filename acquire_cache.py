#!/usr/bin/env python3
"""Per-token decision cache for glossary_acquire.

`glossary_acquire.py` re-derives the same conclusions every sweep. Measured on One Pace
(462 episodes): `settled` holds 107 terms against 8,199 harvested, so ~99% of the work
repeats -- including 371 LLM calls in `escalate` at ~1.3s each, 71% of the stage's runtime.
It exceeded a 1800s timeout three sweeps running and has therefore never completed, which
means it has never contributed anything either.

This module remembers what was decided, so the second run costs only what is new.

ABSENCE IS THE CACHE MISS. There is no corpus fingerprint, no TTL and no versioned key: a
token's verdict does not change because new episodes arrived, and a new token is simply not
in the file. The failure mode of a fingerprint -- serving a stale answer, or invalidating
everything at once -- is the class of bug this codebase keeps finding, so it is not built.

Two things ARE conditional, and both get a per-token guard rather than a global one:

  the canonical    An `apply` verdict's canonical is resolved against today's wiki titles,
                   and glossary_verify.fetch_titles re-fetches on a 30-day TTL. A page
                   rename would leave a cache hit writing a dead title into hard_fixes
                   forever. `stale_canonical()` checks membership in the caller's
                   norm_titles -- O(1), and only the affected entry misses.
  the floor        A `below-floor` verdict depends on whether a near-miss sits in
                   anchor_terms, and that set grows as applies accumulate. The anchor the
                   floor rested on is stored and compared.

Contract, mirroring qc.write and unresolved.record: this is an OPTIMISATION. It must never
raise and never change what the pipeline decides. A corrupt or unreadable cache degrades to
a full run.
"""
from __future__ import annotations

import json
import os
import tempfile

from common import SIDECAR_MODE

SUFFIX = ".acquire-cache.json"

# How much a token's occurrence count must grow before a frequency-derived junk verdict is
# reconsidered. One Pace is the show that punishes a permanent junk ruling: a token seen
# twice in 20 episodes can be a real name that recurs heavily 200 episodes later.
JUNK_RECHECK_GROWTH = 3

# Reasons whose facts CANNOT change with more data, so their verdicts never recycle:
# wordlist membership, exact-match equality, and positional distribution respectively.
# Everything else -- below-floor, unseen-needs-evidence, share-too-close, transcript-new-term,
# growth-over-cap -- is conditional on corpus size or coverage and does recycle. Naming only
# `below-floor` (as the first draft of the spec did) would have permanently junked four other
# corpus-derived verdicts, defeating the recycling rule for exactly the long-tail names it
# exists to rescue.
STRUCTURAL_REASONS = frozenset({"english-word", "already-canonical", "sentence-initial-only"})


def path_for(gloss_path: str) -> str:
    return gloss_path[:-5] + SUFFIX if gloss_path.endswith(".json") else gloss_path + SUFFIX


def load(gloss_path: str) -> dict:
    """Every remembered verdict. Returns {} rather than raising -- a cache that cannot be
    read is a slow run, never a failed one."""
    try:
        with open(path_for(gloss_path), encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def save(gloss_path: str, cache: dict) -> bool:
    """Atomic replace, group-writable so a non-root writer can update it later."""
    p = path_for(gloss_path)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p) or ".",
                                   prefix=os.path.basename(p) + ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.chmod(tmp, SIDECAR_MODE)
        os.replace(tmp, p)
        return True
    except (OSError, ValueError, TypeError):
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


def recycles(reason: str) -> bool:
    """True if this junk reason could flip given a bigger corpus."""
    return reason not in STRUCTURAL_REASONS


def stale_canonical(entry: dict, norm_titles: set, normalize) -> bool:
    """True if the entry's canonical is no longer a wiki title.

    The one thing `absence is the cache miss` does not cover: the verdict label is stable,
    the canonical it carries is not. Checked per token against a set the caller already
    built -- a title-set hash was rejected because it re-runs the whole escalate cost on any
    rename anywhere, which is the other half of the failure this design avoids.

    Detects DISAPPEARANCE, not re-resolution. A canonical that changes to a different valid
    title is a case a human should re-litigate, not one the cache should quietly swap."""
    canon = entry.get("canonical")
    if not canon or not norm_titles:
        return False
    return normalize(canon) not in norm_titles


def is_fresh(entry: dict, count: int, floor_anchor, norm_titles: set, normalize) -> bool:
    """Whether a cached verdict may be served for a token seen `count` times this run."""
    if not isinstance(entry, dict) or "verdict" not in entry:
        return False
    if stale_canonical(entry, norm_titles, normalize):
        return False
    if entry["verdict"] != "junk":
        return True
    reason = entry.get("reason", "")
    if not recycles(reason):
        return True                        # structural: the fact cannot change
    if count > int(entry.get("count", 0)) * JUNK_RECHECK_GROWTH:
        return False                       # materially more evidence than last time
    if entry.get("floor_anchor") != floor_anchor:
        return False                       # the anchor its floor rested on moved
    return True


def skippable(cache: dict, counts: dict, anchor_for, norm_titles: set, normalize) -> set:
    """Tokens whose cached verdict still stands -- the caller folds these into `settled`.

    `anchor_for(token)` returns the token's current settled_target, so a junk verdict whose
    floor rested on an anchor that has since moved is not served."""
    out = set()
    for tok, entry in cache.items():
        try:
            if is_fresh(entry, counts.get(tok, 0), anchor_for(tok), norm_titles, normalize):
                out.add(tok)
        except Exception:                  # a malformed entry costs that token, not the run
            continue
    return out


def remember(cache: dict, proposals: list, counts: dict) -> dict:
    """Fold this run's finished proposals into the cache. Returns the same dict.

    Called AFTER source_gate, so what is stored is the verdict the pipeline actually reached
    -- including the post-escalate outcome, which is the 71% this exists to stop repaying."""
    for p in proposals:
        tok = p.get("variant")
        if not tok:
            continue
        verdict = p.get("verdict")
        entry = {"verdict": "junk" if verdict == "flag" else verdict,
                 "count": int(counts.get(tok, p.get("variant_count", 0)) or 0)}
        if p.get("reason"):
            entry["reason"] = p["reason"]
        if p.get("canonical"):
            entry["canonical"] = p["canonical"]
        if p.get("settled_target") is not None:
            entry["floor_anchor"] = p["settled_target"]
        cache[tok] = entry
    return cache
