#!/usr/bin/env python3
"""Score an answer by what it does to the glossary, the way glossary_verify.apply_results acts on it.

apply_results treats an adjudication {canonical, confidence} like this:
  * HIGH confidence, canonical != the term, and glossary_acquire.is_expansion(term, canonical): WRITTEN (added to the
    names / phrases; additive, the term stays);
  * HIGH confidence, canonical != the term, not an expansion (a respelling): FLAGGED "respelling-needs-review";
  * not high with a canonical and conf "low": FLAGGED "low-confidence"; no canonical or conf none: FLAGGED "no-match";
  * HIGH with canonical == the term: nothing.
`classify` mirrors that for one pick (is_expansion is imported at call time, as production does). A decision arm's "high" is
confidence >= tau; a text arm's is the word high.

Against the item's gold the outcomes are: GOOD WRITE (an expansion in the item's accepted set), WRONG WRITE (an expansion
that is not accepted, or any expansion write on an item whose gold is none), the review-only flags, "nothing" (the term itself:
correct on an exact-gold item) and "failure" (the request failed). The synthetic negatives have every expansion candidate
removed by construction, so a wrong pick there can only cost review time, never a wrong write unless the arm invents an
expansion; the old all-class false-accept rate mixed that harmless noise into its number."""

from __future__ import annotations

import hashlib

import tools.glossary_score as glossary_score

_is_expansion = None


def _expansion(term, title):
    global _is_expansion
    if _is_expansion is None:
        from glossary_acquire import (
            is_expansion,
        )  # at call time, as glossary_verify.apply_results does (an import cycle otherwise)

        _is_expansion = is_expansion
    return _is_expansion(term, title)


def classify(item, pick, tau=None):
    """good_write | wrong_write | nothing | flag_respelling | flag_low | flag_nomatch | failure."""
    if pick is None:
        return "failure"
    title = pick.title
    if not title:
        return "flag_nomatch"
    if not pick.high(tau):
        return "flag_low" if pick.word != "none" else "flag_nomatch"
    if title.casefold() == item["term"].casefold():
        return "nothing"
    if not _expansion(item["term"], title):
        return "flag_respelling"
    accepted = not item.get("negative") and title.casefold() in glossary_score._accept(item)
    return "good_write" if accepted else "wrong_write"


EXPANSION_CLASSES = ("expansion_independent", "expansion_incumbent")
FLAGS = ("flag_respelling", "flag_low", "flag_nomatch")
MISSED_KEY = {
    "flag_nomatch": "none",
    "flag_low": "low",
    "flag_respelling": "respelling",
    "wrong_write": "wrong_write",
    "nothing": "term_itself",
    "failure": "failure",
}


def tally(pairs, tau=None):
    """Consequence counts over [(item, pick-or-None, class)]; ambiguous / no-call items are ignored by the caller."""
    t = {
        "good": 0, "good_expansion": 0, "wrong": 0, "n_expansion": 0, "harmful_flags": 0,
        "exact": {"n": 0, "correct": 0, "wrong_writes": 0},
        "missed": dict.fromkeys(MISSED_KEY.values(), 0),
        "review": {}, "n": 0,
    }  # fmt: skip
    review = {}
    for item, pick, cls in pairs:
        if cls not in glossary_score.CLASS_ORDER:
            continue
        t["n"] += 1
        outcome = classify(item, pick, tau)
        r = review.setdefault(cls, {"n": 0, "flagged": 0})
        r["n"] += 1
        r["flagged"] += outcome in FLAGS
        if outcome == "good_write":
            t["good"] += 1
            t["good_expansion"] += cls in EXPANSION_CLASSES
        elif outcome == "wrong_write":
            t["wrong"] += 1
        if cls == "exact":
            t["exact"]["n"] += 1
            t["exact"]["correct"] += outcome in ("nothing", "good_write")
            t["exact"]["wrong_writes"] += outcome == "wrong_write"
            t["harmful_flags"] += outcome == "flag_respelling"
        if cls in EXPANSION_CLASSES:
            t["n_expansion"] += 1
            if outcome != "good_write":
                t["missed"][MISSED_KEY[outcome]] += 1
    t["writes"] = t["good"] + t["wrong"]
    t["wrong_write_rate"] = glossary_score._rate(t["wrong"], t["writes"])
    t["wrong_write_wilson"] = glossary_score.wilson(t["wrong"], t["writes"])
    t["good_write_rate"] = glossary_score._rate(t["good_expansion"], t["n_expansion"])
    t["good_write_wilson"] = glossary_score.wilson(t["good_expansion"], t["n_expansion"])
    t["review"] = {c: {**v, "per_100": round(100 * v["flagged"] / v["n"], 1)} for c, v in review.items()}
    return t


HELD_OUT_SEED = "heldout-v1"


def half(item_id):
    """0 or 1: a deterministic split of the items by a hash of their id (tau is chosen on half 0, then checked on half 1)."""
    return hashlib.sha256(f"{HELD_OUT_SEED}|{item_id}".encode()).digest()[0] & 1
