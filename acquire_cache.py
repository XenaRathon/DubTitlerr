#!/usr/bin/env python3
"""Per-pair adjudication cache for glossary_acquire's `escalate()`.

`glossary_acquire.py` re-derives the same conclusions every sweep. Measured on One Pace
(462 episodes): `settled` holds 107 terms against 8,199 harvested, so ~99% of the work
repeats -- including 371 LLM calls in `escalate` at ~1.3s each, 71% of the stage's runtime.
It exceeded a 1800s timeout three sweeps running and has therefore never completed, which
means it has never contributed anything either.

This module remembers what `escalate()`'s LLM adjudication decided for one (variant,
canonical) pair, so the second run pays for the call only once.

WHAT THIS DOES NOT CACHE, AND WHY: an earlier version of this module cached the pipeline's
FINAL verdict per token and folded a cache hit into `settled`, which skipped the token
entirely -- out of `propose()`, out of the report, out of everything. `glossary_acquire`
produces exactly three verdicts (`apply`, `known`, `flag`), and all three write glossary
state, so there is no verdict a dry run may safely skip: a cached `apply` never reaches
`--apply`, and a cached `flag` never reaches the human review queue it exists to feed.
Measured 2026-08-29: two byte-identical dry runs over One Pace reported `proposed 641`
then `proposed 0`, and five accumulated cache files held 10,708 `flag` verdicts that would
never have surfaced for a human to review. See
`.procoder/todo/20260829-acquire-cache-suppresses-every-verdict.md`.

The fix is to cache the expensive INTERMEDIATE instead: `adjudicate_merge()`'s answer to
"are `variant` and `canonical` the same entity", keyed on that pair. Every token still flows
through `propose()`, `escalate()` and `source_gate()` on every run -- the report is always
complete and nothing is suppressed -- while the LLM cost is paid once per pair. A merge
adjudication about two specific strings is also a more stable fact than a frequency-derived
verdict: it does not need the staleness/recycling logic the old per-token cache required,
because it never depended on how many times a token had been seen.

ABSENCE IS THE CACHE MISS. There is no corpus fingerprint, no TTL and no versioned key: a
pair's adjudication does not change because new episodes arrived, and a new pair is simply
not in the file. The failure mode of a fingerprint -- serving a stale answer, or
invalidating everything at once -- is the class of bug this codebase keeps finding, so it
is not built.

Contract, mirroring qc.write and unresolved.record: this is an OPTIMISATION. It must never
raise and never change what the pipeline decides -- only how many LLM calls it takes to
decide it. A corrupt or unreadable cache degrades to a full run.
"""

from __future__ import annotations

import json
import os
import tempfile

from common import SIDECAR_MODE

SUFFIX = ".acquire-cache.json"


def path_for(gloss_path: str) -> str:
    return gloss_path[:-5] + SUFFIX if gloss_path.endswith(".json") else gloss_path + SUFFIX


def load(gloss_path: str) -> dict:
    """Every remembered adjudication. Returns {} rather than raising -- a cache that cannot
    be read is a slow run, never a failed one."""
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
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p) or ".", prefix=os.path.basename(p) + ".", suffix=".tmp")
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


def escalation_for(cache: dict, variant: str, canonical: str) -> dict | None:
    """The remembered `adjudicate_merge(variant, canonical, ...)` result, or None.

    A malformed entry (wrong shape, a stale file from the old per-token cache) is a miss,
    never an error -- the caller just pays for the LLM call again."""
    try:
        entry = cache.get(variant, {}).get(canonical)
    except AttributeError:  # cache[variant] is not a dict -- the old cache's shape
        return None
    if not isinstance(entry, dict) or "same_entity" not in entry or "confidence" not in entry:
        return None
    return {"same_entity": bool(entry["same_entity"]), "confidence": entry["confidence"]}


def remember_escalation(cache: dict, variant: str, canonical: str, adjudication: dict) -> dict:
    """Fold one `adjudicate_merge` answer into the cache. Returns the same dict.

    An `unavailable` result is DROPPED rather than stored. It is not an adjudication -- the
    backend raised, returned nothing, or returned something unparseable -- and this cache
    has no TTL, no failure marker and no invalidation, so storing one would answer
    `escalation_for` forever and `escalate`'s `if not adj` would never call the LLM again.
    A single transient outage would strand the pair permanently, and `ACQUIRE_NO_CACHE=1`
    is an escape hatch an operator has to know to reach for, not recovery.

    The guard lives here, not at the call site, because this is where every path that could
    write a failure converges -- a caller that forgets the check cannot reintroduce the bug."""
    if adjudication.get("unavailable"):
        return cache
    cache.setdefault(variant, {})[canonical] = {
        "same_entity": bool(adjudication.get("same_entity")),
        "confidence": adjudication.get("confidence"),
    }
    return cache
