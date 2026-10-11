#!/usr/bin/env python3
"""Score an answer by what it does to the glossary, the way glossary_verify.apply_results acts on it.

Supports two policies:

  * PRODUCTION (default): mirrors production write guards by calling the real guard path
    (glossary_verify.write_decision / apply_results: whole-word guard, common-word guard,
    arc-gate / rescue guards with current environment defaults). High-confidence answers that
    pass all guards are WRITTEN; terms blocked by guards or with lower confidence are QUEUED
    for human review or RECORDED-NOT-QUEUED (following queue_blocked_expansions and queue_no_match).
  * LEGACY: the old mode that scores using the plain substring expansion rule
    (glossary_acquire.is_expansion) without write guards. Labeled clearly as LEGACY in output.

apply_results treats an adjudication {canonical, confidence} like this:
  * HIGH confidence, canonical != the term, and write_decision(...) == "write": WRITTEN (added to
    names / phrases; additive, the term stays);
  * HIGH confidence, canonical != the term, blocked by guards: FLAGGED (e.g. "respelling-needs-review",
    "common-word", "not-in-arc-pages") or recorded when blocked expansion queueing is off;
  * not high with a canonical and conf "low": FLAGGED "low-confidence"; no canonical or conf none:
    recorded (or flagged "no-match" when queue_no_match is on);
  * HIGH with canonical == the term: nothing (recorded in verified, not queued).

Against the item's gold the outcomes are: GOOD WRITE (an accepted expansion), WRONG WRITE (an expansion
that is not accepted, or any expansion write on a gold-none/negative item), review flags (QUEUED),
RECORDED-NOT-QUEUED, nothing, and failure.
"""

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


def classify(item, pick, tau=None, policy="legacy", universe=None, mode=None):
    """good_write | wrong_write | nothing | flag_respelling | flag_common_word | flag_not_in_arc | flag_low | flag_nomatch
    | failure.

    policy can be 'production' (mirrors real production guards) or 'legacy' (the old plain substring expansion rule).
    """
    if mode is not None:
        policy = mode
    if pick is None:
        return "failure"
    title = pick.title
    if not title:
        return "flag_nomatch"
    if not pick.high(tau):
        return "flag_low" if pick.word != "none" else "flag_nomatch"
    if title == item["term"]:
        return "nothing"  # EXACT equality, as apply_results compares: a case-only difference is a respelling flag in production

    if policy == "legacy":
        if not _expansion(item["term"], title):
            return "flag_respelling"
        accepted = not item.get("negative") and title.casefold() in glossary_score._accept(item)
        return "good_write" if accepted else "wrong_write"

    # Production policy: call the real guard path (glossary_verify.write_decision)
    import glossary_verify as gv

    u = universe if universe is not None else item.get("universe")
    decision = gv.write_decision(item["term"], title, u)
    if decision == "write":
        accepted = not item.get("negative") and title.casefold() in glossary_score._accept(item)
        return "good_write" if accepted else "wrong_write"
    if decision == "respelling":
        return "flag_respelling"
    if decision == "common-word":
        return "flag_common_word"
    if decision == "not-in-arc-pages":
        return "flag_not_in_arc"
    return f"flag_{decision}"


def outcome_action(outcome, term=None, canon=None, decision=None, policy="production"):
    """Map outcome to 'WRITTEN', 'QUEUED', or 'RECORDED-NOT-QUEUED'."""
    if outcome in ("good_write", "wrong_write"):
        return "WRITTEN"
    if outcome == "failure":
        return "FAILURE"
    if outcome == "nothing":
        return "RECORDED-NOT-QUEUED"
    if outcome == "flag_nomatch":
        if policy == "legacy":
            return "RECORDED-NOT-QUEUED"
        import glossary_verify as gv

        return "QUEUED" if gv.queue_no_match() else "RECORDED-NOT-QUEUED"
    if outcome == "flag_low":
        if policy == "legacy":
            return "RECORDED-NOT-QUEUED"
        return "QUEUED"
    # Blocked write decisions (flag_respelling, flag_common_word, flag_not_in_arc):
    if policy == "production" and term and canon and decision:
        import glossary_verify as gv

        if gv.blocked_kind(term, canon, decision) in gv.BLOCKED_EXPANSION_KINDS and not gv.queue_blocked_expansions():
            return "RECORDED-NOT-QUEUED"
    return "QUEUED"


EXPANSION_CLASSES = ("expansion_independent", "expansion_incumbent")
FLAGS = ("flag_respelling", "flag_common_word", "flag_not_in_arc", "flag_low", "flag_nomatch")
LEGACY_MISSED_KEY = {
    "flag_nomatch": "none",
    "flag_low": "low",
    "flag_respelling": "respelling",
    "wrong_write": "wrong_write",
    "nothing": "term_itself",
    "failure": "failure",
}
MISSED_KEY = {
    **LEGACY_MISSED_KEY,
    "flag_common_word": "common_word",
    "flag_not_in_arc": "not_in_arc",
}


def tally(pairs, tau=None, policy="legacy", universe=None, mode=None):
    """Consequence counts over [(item, pick-or-None, class)]; ambiguous / no-call items are ignored by the caller.

    policy can be 'production' (mirrors real production guards) or 'legacy' (the old plain substring expansion rule).
    """
    if mode is not None:
        policy = mode
    mode_label = "LEGACY" if policy == "legacy" else "PRODUCTION"
    missed_map = LEGACY_MISSED_KEY if policy == "legacy" else MISSED_KEY
    t = {
        "mode": mode_label,
        "policy": policy,
        "good": 0, "good_expansion": 0, "good_exact": 0, "wrong": 0, "n_expansion": 0, "harmful_flags": 0,
        "exact": {"n": 0, "correct": 0, "wrong_writes": 0},
        "missed": dict.fromkeys(missed_map.values(), 0),
        "review": {}, "n": 0,
        "outcomes": {
            "WRITTEN": {"total": 0, "right": 0, "wrong": 0},
            "QUEUED": {"total": 0, "right": 0, "wrong": 0},
            "RECORDED-NOT-QUEUED": {"total": 0, "right": 0, "wrong": 0},
        },
    }  # fmt: skip

    review = {}
    for item, pick, cls in pairs:
        if cls not in glossary_score.CLASS_ORDER:
            continue
        t["n"] += 1
        outcome = classify(item, pick, tau, policy=policy, universe=universe)
        title = pick.title if pick else ""

        # Determine the action (WRITTEN / QUEUED / RECORDED-NOT-QUEUED)
        dec = None
        if policy == "production" and pick and pick.high(tau) and title and title != item["term"]:
            import glossary_verify as gv

            u = universe if universe is not None else item.get("universe")
            dec = gv.write_decision(item["term"], title, u)

        action = outcome_action(outcome, item.get("term"), title, dec, policy=policy)

        # Right/wrong split when audited labels exist
        if action in t["outcomes"]:
            t["outcomes"][action]["total"] += 1
            is_right = bool(pick and glossary_score.correct(item, pick))
            if is_right:
                t["outcomes"][action]["right"] += 1
            else:
                t["outcomes"][action]["wrong"] += 1

        r = review.setdefault(cls, {"n": 0, "flagged": 0, "recorded": 0})
        r["n"] += 1
        if policy == "legacy":
            r["flagged"] += outcome == "flag_respelling"  # the one flag a human reviews (glossary_acquire --review)
            r["recorded"] += outcome in ("flag_low", "flag_nomatch")  # recorded in the glossary's flagged map
        else:
            r["flagged"] += action == "QUEUED"
            r["recorded"] += action == "RECORDED-NOT-QUEUED"

        if outcome == "good_write":
            t["good"] += 1
            t["good_expansion"] += cls in EXPANSION_CLASSES
            t["good_exact"] += cls == "exact"  # right, but not a gain: the term was already correct
        elif outcome == "wrong_write":
            t["wrong"] += 1
        if cls == "exact":
            t["exact"]["n"] += 1
            t["exact"]["correct"] += outcome in ("nothing", "good_write")
            t["exact"]["wrong_writes"] += outcome == "wrong_write"
            t["harmful_flags"] += outcome == "flag_respelling" if policy == "legacy" else (action == "QUEUED")
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

    t["WRITTEN"] = t["outcomes"]["WRITTEN"]
    t["QUEUED"] = t["outcomes"]["QUEUED"]
    t["RECORDED-NOT-QUEUED"] = t["outcomes"]["RECORDED-NOT-QUEUED"]
    t["written"] = t["outcomes"]["WRITTEN"]
    t["queued"] = t["outcomes"]["QUEUED"]
    t["recorded_not_queued"] = t["outcomes"]["RECORDED-NOT-QUEUED"]
    return t


HELD_OUT_SEED = "heldout-v1"


def half(item_id):
    """0 or 1: a deterministic split of the items by a hash of their id (tau is chosen on half 0, then checked on half 1)."""
    return hashlib.sha256(f"{HELD_OUT_SEED}|{item_id}".encode()).digest()[0] & 1

