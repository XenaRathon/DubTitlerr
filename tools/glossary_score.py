#!/usr/bin/env python3
"""Offline scoring for the glossary-stage bake-off (`glossary_bakeoff.py score`).

Reads the item set from `build-set` and the result rows from `run`; no network, no model. The rules below were fixed
in advance by the maintainer's plan and are not softened here.

Latest row per (id, arm, order) wins; an errored latest row is a FAILURE, never a pick. Verify stage only: acquire
items have no gold, their scoring comes from blind judging.

Classes of verify items: exact gold (controls, reported separately and kept out of the headline), expansion gold split by
`incumbent_derived`, negatives (gold none), and ambiguous / no-gold (excluded from accuracy; used for agreement and for
judging). Items with zero candidates are answered locally by production and never scored. Single-candidate items are
split from items with two or more candidates because "always pick candidate 1" cannot fail on the former.

A pick is a title or "none". A pick is correct when it is in the item's `gold_accept` set (negatives: when it is none).
HIGH-CONFIDENCE false accept: of the labelled items where the arm picked a non-none title at high confidence, the share
that is wrong (a wrong title on a gold item; ANY non-none on a negative). High is the word "high" for text arms and a
numeric confidence >= tau for decision arms; tau is SWEPT (never fixed), giving an operating curve. The matched operating
point finds, for each decision arm, the smallest tau whose false-accept rate is no higher than the baseline's and reports
true-accept there next to the baseline's. The floor arm `always-candidate-1` is computed from the items alone.

A per-candidate noul arm (Span-01 Lite) scores each candidate alone: its pick is the highest-scoring candidate and its
confidence that candidate's score; it never says none, the tau sweep decides when it abstains. A per-candidate noul is
NOT a choice probability: the scores of the candidates of one item need not sum to anything.

THE METRIC FOLLOWS glossary_verify.apply_results (see glossary_consequences): rules (a) and (b) compare what actually lands in
the glossary. (a) is the WRONG-WRITE rate (wrong writes / writes); (b) is the GOOD-WRITE rate (good writes / expansion-gold
items). The earlier all-class high-confidence false-accept rate stays as a secondary column.

Rates carry n and a Wilson 95% interval. Arm vs arm comparisons are made on the items BOTH ran, and say "within noise"
when the intervals overlap. The verdict table applies the five rules and declares no winner."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

FLOOR_ARM = "always-candidate-1"
V2_SUFFIX = (
    "@v2"  # a post-hoc question framing (see glossary_bakeoff.V2_INSTRUCTION): every pick is a title, tau decides abstention
)


def is_v2(arm):
    return arm.endswith(V2_SUFFIX)


def _disp(arm):
    return f"{arm} (post-hoc framing)" if is_v2(arm) else arm


ORDER_LIMIT = 0.05
MIN_COMMON_N = 100  # common labelled items needed (capped at the item set's own size) before a rule can be decided
MIN_COMMON_FRAC = 0.9  # ...and this share of the item set's non-trivial items, and of each expansion class, and of the negatives
MIN_REVERSED_PAIRS = 100  # forward/reversed pairs needed before rule (c) can be decided
FAILURE_LIMIT = 0.02
CLASS_ORDER = ("exact", "expansion_independent", "expansion_incumbent", "negative")
NON_TRIVIAL = ("expansion_independent", "expansion_incumbent", "negative")
CLASS_LABEL = {
    "exact": "exact gold (controls, not in the headline)",
    "expansion_independent": "expansion gold, independent",
    "expansion_incumbent": "expansion gold, incumbent-derived",
    "negative": "negatives (answer: none)",
}


def wilson(k, n, z=1.96):
    """Wilson score interval for k successes in n trials, or None when n is 0."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _overlap(a, b):
    return a is not None and b is not None and a[0] <= b[1] and b[0] <= a[1]


def _rate(k, n):
    return (k / n) if n else None


def _fmt(x, digits=3):
    return "n/a" if x is None else f"{x:.{digits}f}"


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


# ---- loading ----------------------------------------------------------------------------------------------


def load_items(path):
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                it = json.loads(line)
            except ValueError:
                continue
            if isinstance(it, dict) and it.get("stage") == "verify" and isinstance(it.get("id"), str):
                items.append(it)
    return items


def load_results(paths):
    """{(id, arm, order): row}, the latest row winning (later lines, later files). Torn / foreign lines are skipped."""
    rows = {}
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    key = (r["id"], r["arm"], r["order"])
                except (ValueError, KeyError, TypeError):
                    continue
                rows[key] = r
    return rows


# ---- picks -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Pick:
    title: str  # "" means none
    conf: float | None = None  # numeric confidence (decision arms)
    word: str | None = None  # "high" | "low" | "none" (text arms)

    def high(self, tau=None):
        if not self.title:
            return False
        if self.word is not None:
            return self.word == "high"
        return self.conf is not None and tau is not None and self.conf >= tau


def _num(x):
    if isinstance(x, dict):
        x = x.get("probability", x.get("score"))
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def row_pick(row):
    """The Pick in a result row, or None when the row is a failure (an error, or nothing parseable)."""
    if row.get("error"):
        return None
    p = row.get("parsed")
    if not isinstance(p, dict):
        return None
    if "choice" in p:  # a decision arm (framing v2 Span rows also land here: their pick is the best title, tau decides later)
        title = p.get("canonical") or ""
        conf = p.get("confidence")
        return Pick(title, conf=float(conf) if isinstance(conf, (int, float)) and not isinstance(conf, bool) else None)
    if "scores" in p and isinstance(p["scores"], dict):  # Span-01 Lite, framing v1: per-candidate probabilities
        scored = [(t, _num(v)) for t, v in p["scores"].items()]
        scored = [(t, v) for t, v in scored if v is not None]
        if not scored:
            return None
        best_t, best_v = max(scored, key=lambda tv: tv[1])  # ties: first in the order the candidates were shown
        return Pick(best_t, conf=best_v)  # always a title: whether to abstain is the tau sweep's job
    if "canonical" in p:  # a text arm: production's parse
        word = str(p.get("confidence") or "none").lower()
        title = p["canonical"] or ""
        return Pick("" if word == "none" else title, word=word)
    return None


def failure_kind(error):
    e = str(error)
    if re.search(r"\b429\b", e) or "rate-limited" in e:
        return "rate-limit"
    if re.search(r"HTTP 5\d\d", e):
        return "http-5xx"
    if re.search(r"HTTP 4\d\d", e):
        return "http-4xx"
    if "imeout" in e or "deadline" in e:
        return "timeout"
    if "bad response" in e or "DecisionError" in e or "unparseable" in e or "allowlist" in e:
        return "bad-response"
    if "EMPTY" in e or "no answer" in e or "truncated" in e or "no content" in e:
        return "empty"
    return "other"


# ---- item classes -------------------------------------------------------------------------------------------


def item_class(item):
    """exact | expansion_independent | expansion_incumbent | negative | ambiguous | None (a no-call control)."""
    if item.get("no_call") or not item.get("candidates"):
        return None
    if item.get("negative"):
        return "negative"
    if item.get("gold"):
        if item.get("gold_kind") == "exact":
            return "exact"
        return "expansion_incumbent" if item.get("incumbent_derived") else "expansion_independent"
    return "ambiguous"


def _accept(item):
    if item.get("negative"):
        return set()
    return {a.casefold() for a in (item.get("gold_accept") or [item["gold"]])}


def correct(item, pick):
    if item.get("negative"):
        return pick.title == ""
    return bool(pick.title) and pick.title.casefold() in _accept(item)


# ---- metrics ------------------------------------------------------------------------------------------------


def _percentile(sorted_values, q):
    if not sorted_values:
        return None
    return sorted_values[min(len(sorted_values) - 1, max(0, math.ceil(q * len(sorted_values)) - 1))]


def _median(sorted_values):
    n = len(sorted_values)
    if not n:
        return None
    return sorted_values[n // 2] if n % 2 else (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2


def _accuracy(pairs):
    """pairs: [(item, pick-or-None)] -> {n, correct, accuracy, wilson}; a failure (None) is a miss."""
    n = len(pairs)
    k = sum(1 for it, pk in pairs if pk is not None and correct(it, pk))
    return {"n": n, "correct": k, "accuracy": _rate(k, n), "wilson": wilson(k, n)}


def _hc(pairs, tau=None, only=None):
    """High-confidence accepts over labelled items. pairs: [(item, pick-or-None, class)]."""
    accepted = wrong = positives = true_accepts = 0
    for it, pk, cls in pairs:
        if cls not in CLASS_ORDER or (only and cls not in only):
            continue
        if cls != "negative":
            positives += 1
        if pk is not None and pk.high(tau):
            accepted += 1
            if correct(it, pk):
                true_accepts += 1
            else:
                wrong += 1
    return {
        "accepted": accepted,
        "wrong": wrong,
        "false_accept_rate": _rate(wrong, accepted),
        "false_accept_wilson": wilson(wrong, accepted),
        "true_accepts": true_accepts,
        "positives": positives,
        "true_accept_rate": _rate(true_accepts, positives),
        "true_accept_wilson": wilson(true_accepts, positives),
    }


def _taus(step):
    n = int(round(1 / step))
    return sorted({round(i * step, 10) for i in range(n + 1)} | {1.0})


def _is_decision(picks):
    return any(p.conf is not None and p.word is None for p in picks if p is not None)


def _failures(rows):
    sent = [r for r in rows if not r.get("local")]
    errs = [r for r in sent if r.get("error")]
    kinds = {}
    for r in errs:
        k = failure_kind(r["error"])
        kinds[k] = kinds.get(k, 0) + 1
    return {"total": len(errs), "n_rows": len(sent), "rate": _rate(len(errs), len(sent)), "by_kind": kinds}


def _labelled_pairs(items_by_id, classes, picks, item_order):
    return [(items_by_id[i], picks[i], classes[i]) for i in item_order if i in picks and classes.get(i) in CLASS_ORDER]


def _median_or_none(values):
    return _median(sorted(values)) if values else None


def _calibration(items_by_id, labelled, fwd_rows):
    """Score distributions: the median confidence of the arm's correct vs wrong picks on gold items, and for a per-candidate noul
    arm the median score of the correct title(s) vs the other candidates."""
    right, wrong = [], []
    score_right, score_other = [], []
    for it, pk, cls in labelled:
        if cls == "negative" or pk is None or pk.conf is None:
            continue
        (right if correct(it, pk) else wrong).append(pk.conf)
    for it, _pk, cls in labelled:
        row = (fwd_rows or {}).get(it["id"])
        scores = (row or {}).get("parsed", {}).get("scores") if isinstance((row or {}).get("parsed"), dict) else None
        if cls == "negative" or not isinstance(scores, dict):
            continue
        accepted = _accept(it)
        for title, v in scores.items():
            v = _num(v)
            if v is not None:
                (score_right if title.casefold() in accepted else score_other).append(v)
    out = {
        "pick_conf": {
            "correct_median": _median_or_none(right),
            "wrong_median": _median_or_none(wrong),
            "n_correct": len(right),
            "n_wrong": len(wrong),
        },
        "scores": None,
    }  # fmt: skip
    if score_right or score_other:
        out["scores"] = {
            "correct_median": _median_or_none(score_right), "other_median": _median_or_none(score_other),
            "n_correct": len(score_right), "n_other": len(score_other),
        }  # fmt: skip
    return out


def _arm_metrics(arm, items_by_id, classes, fwd, rev, arm_rows, tau_step, item_order, fwd_rows=None):
    """Everything about one arm, over the items it ran."""
    ids = [i for i in item_order if i in fwd and classes.get(i) is not None]  # items with a forward row
    pairs = [(items_by_id[i], fwd[i], classes[i]) for i in ids]
    out = {"classes": {}, "by_candidates": {}, "accept_choices": {}, "accept_counts": {"exact": 0, "expansion": 0}}
    for cls in CLASS_ORDER:
        sel = [(it, pk) for it, pk, c in pairs if c == cls]
        if sel:
            out["classes"][cls] = _accuracy(sel)
    picks = [pk for _, pk, _ in pairs]
    decision = _is_decision(picks)
    # An arm that can only answer with a title (framing v2, a per-candidate noul arm) abstains by confidence, so "right iff none"
    # has no tau-free meaning for its negatives: they are judged on the operating curve instead.
    by_confidence = decision and (is_v2(arm) or all(p is None or p.title for p in picks))
    if by_confidence and "negative" in out["classes"]:
        out["classes"]["negative"] = {
            "n": out["classes"]["negative"]["n"], "correct": None, "accuracy": None, "wilson": None,
            "note": "abstention is by confidence: see the operating curve",
        }  # fmt: skip
    labelled = [(it, pk) for it, pk, c in pairs if c in CLASS_ORDER and not (by_confidence and c == "negative")]
    for name, test in (("single", lambda it: len(it["candidates"]) == 1), ("multi", lambda it: len(it["candidates"]) >= 2)):
        out["by_candidates"][name] = _accuracy([(it, pk) for it, pk in labelled if test(it)])
    for it, pk in labelled:
        if pk is not None and not it.get("negative") and len(_accept(it)) > 1 and correct(it, pk):
            out["accept_choices"][pk.title] = out["accept_choices"].get(pk.title, 0) + 1
            out["accept_counts"]["exact" if pk.title.casefold() == it["term"].casefold() else "expansion"] += 1
    out["kind"] = "decision" if decision else "text"
    out["framing"] = "v2" if is_v2(arm) else "v1"
    out["abstains_by_confidence"] = by_confidence
    out["hc"] = None if decision else _hc(pairs)
    if not decision:
        out["hc"]["non_trivial"] = _hc(pairs, only=NON_TRIVIAL)
    out["curve"] = out["curve_nt"] = out["consequences"] = None
    if decision:
        import tools.glossary_consequences as gc

        out["curve"] = [{"tau": t, **_hc(pairs, tau=t)} for t in _taus(tau_step)]
        nt_pairs = [p for p in pairs if p[2] in NON_TRIVIAL]
        out["curve_nt"] = []
        for t, legacy in zip(_taus(tau_step), out["curve"], strict=True):
            c = gc.tally(nt_pairs, tau=t)
            out["curve_nt"].append(
                {
                    "tau": t,
                    "writes": c["writes"],
                    "wrong": c["wrong"],
                    "wrong_write_rate": c["wrong_write_rate"],
                    "good_write_rate": c["good_write_rate"],
                    "all_class_false_accept": legacy["false_accept_rate"],
                    "all_class_accepted": legacy["accepted"],
                }  # fmt: skip
            )
    else:
        import tools.glossary_consequences as gc

        out["consequences"] = gc.tally(pairs)
    # order sensitivity: items with >= 2 candidates that have both a forward and a reverse pick
    n = changed = 0
    for i in ids:
        if len(items_by_id[i]["candidates"]) >= 2 and fwd.get(i) is not None and rev.get(i) is not None:
            n += 1
            changed += fwd[i].title.casefold() != rev[i].title.casefold()
    out["order"] = {"n": n, "changed": changed, "rate": _rate(changed, n), "wilson": wilson(changed, n)}
    # answers outside the item's candidate list (a text arm's free-form spelling): how often, so its cost is visible
    answered = [(it, pk) for it, pk, _ in pairs if pk is not None]
    off = sum(
        1 for it, pk in answered if pk.title and pk.title.casefold() not in {c["title"].casefold() for c in it["candidates"]}
    )
    out["off_list"] = {"n": off, "of": len(answered)}
    out["calibration"] = _calibration(items_by_id, [(it, pk, c) for it, pk, c in pairs if c in CLASS_ORDER], fwd_rows)
    out["failures"] = _failures(arm_rows)
    lat = sorted(
        r["latency_s"]
        for r in arm_rows
        if not r.get("local") and not r.get("error") and isinstance(r.get("latency_s"), (int, float))
    )
    out["latency"] = {"n": len(lat), "median": _median(lat), "p95": _percentile(lat, 0.95)}
    tokens = {}
    for r in arm_rows:
        for k, v in (r.get("usage") or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                tokens[k] = tokens.get(k, 0) + v
    out["tokens"] = tokens
    out["n_items"] = len(ids)
    return out


def _floor_picks(items, classes):
    return {it["id"]: Pick(it["candidates"][0]["title"], conf=1.0, word="high") for it in items if classes[it["id"]] is not None}


def _common_pairs(items_by_id, classes, a, b, order):
    return [(items_by_id[i], a.get(i), classes[i]) for i in order if i in a and i in b and classes.get(i) is not None], [
        (items_by_id[i], b.get(i), classes[i]) for i in order if i in a and i in b and classes.get(i) is not None
    ]


def load_judged(path):
    """Rows written by import-judge (one per item and arm); torn lines are skipped."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and {"item", "arm", "stage", "best", "worst"} <= set(r):
                rows.append(r)
    return rows


def judged_table(rows):
    """{stage: {arm: {judged, best, worst, net, sole}}} from import-judge rows: the blind-judged headline."""
    table = {}
    for r in rows:
        t = table.setdefault(r["stage"], {}).setdefault(r["arm"], {"judged": 0, "best": 0, "worst": 0, "net": 0, "sole": 0})
        t["judged"] += 1
        t["best"] += bool(r["best"])
        t["worst"] += bool(r["worst"])
        t["sole"] += bool(r.get("sole_best"))
    for stage in table.values():
        for t in stage.values():
            t["net"] = t["best"] - t["worst"]
    return table


def build_report(items, rows, baseline="qwen-local", tau_step=0.05, judged=None):
    import tools.glossary_consequences as gc

    items_by_id = {i["id"]: i for i in items}
    classes = {i["id"]: item_class(i) for i in items}
    order = [i["id"] for i in items]
    counts = {"verify": len(items), "no_call": sum(1 for c in classes.values() if c is None)}
    for cls in (*CLASS_ORDER, "ambiguous"):
        counts[cls] = sum(1 for c in classes.values() if c == cls)
    counts["single_candidate"] = sum(1 for i in items if classes[i["id"]] and len(i["candidates"]) == 1)
    counts["multi_candidate"] = sum(1 for i in items if classes[i["id"]] and len(i["candidates"]) >= 2)
    totals = {
        "labelled": sum(counts[c] for c in CLASS_ORDER),
        "nt": sum(counts[c] for c in NON_TRIVIAL),
        **{c: counts[c] for c in CLASS_ORDER},
    }

    by_arm = {}
    for (rid, arm, ordr), row in rows.items():
        if rid in items_by_id:
            by_arm.setdefault(arm, []).append((ordr, rid, row))
    picks = {}  # arm -> {"fwd": {id: Pick|None}, "rev": {...}}
    fwd_rows = {}
    arm_rows = {}
    for arm, entries in by_arm.items():
        picks[arm] = {"fwd": {}, "rev": {}}
        fwd_rows[arm] = {}
        arm_rows[arm] = [r for _, _, r in entries]
        for ordr, rid, row in entries:
            if ordr in ("fwd", "rev"):
                picks[arm][ordr][rid] = row_pick(row)
            if ordr == "fwd":
                fwd_rows[arm][rid] = row
    floor = _floor_picks(items, classes)

    arms = {}
    for arm in sorted(by_arm):
        arms[arm] = _arm_metrics(
            arm, items_by_id, classes, picks[arm]["fwd"], picks[arm]["rev"], arm_rows[arm], tau_step, order, fwd_rows[arm]
        )
    arms[FLOOR_ARM] = _arm_metrics(FLOOR_ARM, items_by_id, classes, floor, {}, [], tau_step, order)
    fwd_all = {a: picks[a]["fwd"] for a in picks} | {FLOOR_ARM: floor}

    names = list(arms)
    agreement = {a: {} for a in names}
    for a in names:
        for b in names:
            both = [i for i in order if fwd_all[a].get(i) is not None and fwd_all[b].get(i) is not None]
            agreement[a][b] = {
                "agree": sum(fwd_all[a][i].title.casefold() == fwd_all[b][i].title.casefold() for i in both),
                "n": len(both),
            }

    present = baseline in picks
    report = {
        "baseline": baseline,
        "baseline_present": present,
        "tau_step": tau_step,
        "items": counts,
        "arms": arms,
        "agreement": agreement,
        "verdicts": {},
        "judged": judged_table(judged) if judged is not None else None,
    }
    for arm in arms:
        if arm == FLOOR_ARM or arm == baseline:
            continue
        v = _verdict(arm, report, items_by_id, classes, fwd_all, order, baseline, present, floor, tau_step, totals)
        report["verdicts"][arm] = v
        if arms[arm]["kind"] == "decision":
            arms[arm]["matched"] = v.get("matched")
    # consequences of every decision arm at its matched tau and at tau 0.5 and 0.8, over the items it ran
    for arm, m in arms.items():
        if m["kind"] != "decision":
            continue
        labelled = _labelled_pairs(items_by_id, classes, fwd_all[arm], order)
        points = {}
        matched = m.get("matched") or {}
        if matched.get("tau") is not None:
            points["matched"] = {"tau": matched["tau"], **gc.tally(labelled, tau=matched["tau"])}
        for t in (0.5, 0.8):
            points[f"{t:.2f}"] = {"tau": t, **gc.tally(labelled, tau=t)}
        m["consequence_points"] = points
    return report


def _incomplete(note, below_floor=False):
    r = {"ok": None, "note": note}
    if below_floor:
        r["below_floor"] = True
    return r


def _coverage_notes(classes, order, armp, base, totals):
    """The sample-size floor for the comparisons against the baseline, counted on the NON-TRIVIAL items: the arm and the baseline
    must both have run at least 90% of the item set's non-trivial items and of each expansion class, and the common labelled
    count must reach MIN_COMMON_N (capped at the item set's size). The exact controls never satisfy the floor on their own."""
    common_all = [i for i in order if i in armp and i in base and classes.get(i) in CLASS_ORDER]
    common_nt = [i for i in common_all if classes[i] in NON_TRIVIAL]
    parts = []
    need_nt = math.ceil(MIN_COMMON_FRAC * totals["nt"])
    if len(common_nt) < need_nt:
        parts.append(f"{len(common_nt)} common non-trivial items (need 90% of the item set's {totals['nt']} = {need_nt})")
    for cls in ("expansion_independent", "expansion_incumbent"):
        tot = totals[cls]
        have = sum(1 for i in common_nt if classes[i] == cls)
        if tot and have < math.ceil(MIN_COMMON_FRAC * tot):
            parts.append(f"{cls}: {have} of {tot} covered (need 90%)")
    need_abs = min(MIN_COMMON_N, totals["labelled"])
    if len(common_all) < need_abs:
        parts.append(f"{len(common_all)} common labelled items (floor {need_abs})")
    return common_all, common_nt, parts


def _best_tau(nt_pairs, taus, base_rate):
    """The smallest tau whose wrong-write rate is defined (at least one write) and not above the baseline's."""
    import tools.glossary_consequences as gc

    for tau in taus:
        t = gc.tally(nt_pairs, tau=tau)
        if t["writes"] and t["wrong_write_rate"] <= base_rate:
            return tau, t
    return None, None


def _held_out(arm_nt, base_nt, taus, base_tau):
    """Pick tau on half of the common items (a seeded split by item id) and report both rates on the OTHER half."""
    import tools.glossary_consequences as gc

    a = [p for p in arm_nt if gc.half(p[0]["id"]) == 0]
    b = [p for p in arm_nt if gc.half(p[0]["id"]) == 1]
    out = {"n_a": len(a), "n_b": len(b), "tau_a": None}
    base_a = gc.tally([p for p in base_nt if gc.half(p[0]["id"]) == 0], tau=base_tau)
    if not a or not b or base_a["wrong_write_rate"] is None:
        return out
    tau, _ = _best_tau(a, taus, base_a["wrong_write_rate"])
    out["tau_a"] = tau
    if tau is not None:
        arm_b = gc.tally(b, tau=tau)
        base_b = gc.tally([p for p in base_nt if gc.half(p[0]["id"]) == 1], tau=base_tau)
        out.update(
            arm_wrong_write_rate_b=arm_b["wrong_write_rate"],
            arm_good_write_rate_b=arm_b["good_write_rate"],
            baseline_wrong_write_rate_b=base_b["wrong_write_rate"],
            baseline_good_write_rate_b=base_b["good_write_rate"],
            arm_writes_b=arm_b["writes"],
        )
    return out


def _verdict(arm, report, items_by_id, classes, fwd_all, order, baseline, present, floor, tau_step, totals):
    """The five rules for one arm. Each rule is ok True / False, or None when it cannot be evaluated (INCOMPLETE).

    Rules (a), (b), (d) and the matched tau are decided on the common NON-TRIVIAL items (expansions + negatives), INCOMPLETE
    below the sample-size floor, (a) and (b) also for a failed baseline, one that made no writes, or one that has not run the
    negatives. (a) is the wrong-write rate, (b) the good-write rate (see glossary_consequences). (c) and (e) have their own sample
    floors. A rule that holds only within noise is ok True with within_noise set ("not demonstrated"); a failure within noise
    reads "FAIL (within noise)". The overall verdict is INCOMPLETE while any rule is below its floor."""
    import tools.glossary_consequences as gc

    a = report["arms"][arm]
    armp = fwd_all[arm]
    rules = {k: _incomplete("no baseline results" if not present else "") for k in "abcde"}
    out = {"rules": rules, "matched": None}

    # (c) order sensitivity and (e) failure rate need no baseline, but they need a sample
    o = a["order"]
    if o["n"] < max(MIN_REVERSED_PAIRS, 1):
        rules["c"] = _incomplete(
            f"only {o['n']} reversed pairs (floor {MIN_REVERSED_PAIRS})", below_floor=o["n"] < MIN_REVERSED_PAIRS
        )
        rules["c"].update(n=o["n"], rate=o["rate"], limit=ORDER_LIMIT)
    else:
        ok = o["rate"] <= ORDER_LIMIT
        rules["c"] = {
            "ok": ok,
            "n": o["n"],
            "rate": o["rate"],
            "limit": ORDER_LIMIT,
            "within_noise": (not ok) and o["wilson"][0] <= ORDER_LIMIT,
        }
    f = a["failures"]
    if f["n_rows"] < max(MIN_COMMON_N, 1):
        rules["e"] = _incomplete(f"only {f['n_rows']} requests (floor {MIN_COMMON_N})", below_floor=f["n_rows"] < MIN_COMMON_N)
        rules["e"].update(n=f["n_rows"], rate=f["rate"], limit=FAILURE_LIMIT)
    else:
        ok = f["rate"] <= FAILURE_LIMIT
        lo = wilson(f["total"], f["n_rows"])[0]
        rules["e"] = {
            "ok": ok,
            "n": f["n_rows"],
            "rate": f["rate"],
            "limit": FAILURE_LIMIT,
            "within_noise": (not ok) and lo <= FAILURE_LIMIT,
        }

    base = fwd_all[baseline] if present else {}
    common_all, common_nt, floor_parts = _coverage_notes(classes, order, armp, base, totals) if present else ([], [], [])
    notes = []
    if floor_parts:
        notes.append("below the sample-size floor: " + "; ".join(floor_parts))
    if present:
        neg_total = totals["negative"]
        ran = sum(1 for i in order if classes.get(i) == "negative" and i in base)
        if neg_total and ran < math.ceil(MIN_COMMON_FRAC * neg_total):
            notes.append(f"the baseline has run only {ran} of {neg_total} negatives (need 90%)")
    floor_blocked = bool(notes)

    # (d) beats always-candidate-1 on the POOLED expansion classes; the per-class split is reporting only
    d = {"ok": None, "classes": {}, "n": 0}
    for cls in ("expansion_independent", "expansion_incumbent"):
        ids = [i for i in order if i in armp and classes.get(i) == cls]
        if ids:
            arm_acc = _accuracy([(items_by_id[i], armp[i]) for i in ids])
            floor_acc = _accuracy([(items_by_id[i], floor.get(i)) for i in ids])
            d["classes"][cls] = {
                "n": len(ids),
                "arm": arm_acc["accuracy"],
                "floor": floor_acc["accuracy"],
                "within_noise": _overlap(arm_acc["wilson"], floor_acc["wilson"]),
            }
    exp_ids = [i for i in order if i in armp and classes.get(i) in ("expansion_independent", "expansion_incumbent")]
    d["n"] = len(exp_ids)
    if exp_ids:
        arm_acc = _accuracy([(items_by_id[i], armp[i]) for i in exp_ids])
        floor_acc = _accuracy([(items_by_id[i], floor.get(i)) for i in exp_ids])
        d.update(arm=arm_acc["accuracy"], floor=floor_acc["accuracy"], pooled_n=len(exp_ids))
    neg_ids = [i for i in order if i in armp and classes.get(i) == "negative"]
    if exp_ids and neg_ids and not a["abstains_by_confidence"]:
        arm_bal = (d["arm"] + _accuracy([(items_by_id[i], armp[i]) for i in neg_ids])["accuracy"]) / 2
        floor_bal = (d["floor"] + _accuracy([(items_by_id[i], floor.get(i)) for i in neg_ids])["accuracy"]) / 2
        d["balanced"] = {"arm": arm_bal, "floor": floor_bal}
    if present and floor_blocked:
        d.update(ok=None, below_floor=True, note="; ".join(notes))
    elif not exp_ids:
        d.update(ok=False, note="no expansion items were run")
    else:
        # `>=` is "no worse than the floor"; the intervals decide whether it is demonstrated. A perfect floor cannot be beaten.
        d["ok"] = d["arm"] >= d["floor"]
        d["within_noise"] = _overlap(arm_acc["wilson"], floor_acc["wilson"])
        if d["floor"] == 1.0:
            d["within_noise"] = True
            d["note"] = "the floor is already perfect on the expansion items, so it cannot be beaten"
    rules["d"] = d

    if present:
        base_decision = report["arms"][baseline]["kind"] == "decision"
        base_tau = 0.5 if base_decision else None
        nt_ids = common_nt
        base_fail = sum(1 for i in nt_ids if base[i] is None)
        if nt_ids and base_fail / len(nt_ids) > FAILURE_LIMIT:
            notes.append(
                f"the baseline's failure rate on the common items is {_pct(base_fail / len(nt_ids))} (limit "
                f"{_pct(FAILURE_LIMIT)})"
            )
        arm_nt = [(items_by_id[i], armp[i], classes[i]) for i in nt_ids]
        base_nt = [(items_by_id[i], base[i], classes[i]) for i in nt_ids]
        bt = gc.tally(base_nt, tau=base_tau)
        if nt_ids and bt["writes"] == 0 and not notes:
            notes.append("the baseline made no writes, so its wrong-write rate is undefined")
        if not nt_ids:
            notes.append("no non-trivial items were run by both")
        if notes:
            for k in "ab":
                rules[k] = _incomplete("; ".join(notes), below_floor=floor_blocked)
            out["matched"] = {"tau": None, "n_common": len(nt_ids), "note": "; ".join(notes)}
        else:
            all_arm = [(items_by_id[i], armp[i], classes[i]) for i in common_all]
            all_base = [(items_by_id[i], base[i], classes[i]) for i in common_all]
            taus = _taus(tau_step)
            if a["kind"] == "decision":
                tau, at = _best_tau(arm_nt, taus, bt["wrong_write_rate"])
                ever = any(gc.tally(arm_nt, tau=t)["writes"] for t in taus)
                out["matched"] = {
                    "tau": tau,
                    "n_common": len(nt_ids),
                    "baseline_wrong_write_rate": bt["wrong_write_rate"],
                    "baseline_good_write_rate": bt["good_write_rate"],
                    "arm_wrong_write_rate": at["wrong_write_rate"] if at else None,
                    "arm_good_write_rate": at["good_write_rate"] if at else None,
                    "ever_writes": ever,
                    "held_out": _held_out(arm_nt, base_nt, taus, base_tau),
                }
                if at is None and not ever:
                    at = gc.tally(arm_nt, tau=1.0)
                    at["writes"] = 0
            else:
                tau, at = None, gc.tally(arm_nt)
            sec_arm = _hc(all_arm, tau=tau)
            sec_base = _hc(all_base, tau=base_tau)
            secondary = {"n": len(common_all), "arm": sec_arm["false_accept_rate"], "baseline": sec_base["false_accept_rate"]}
            rules["a"], rules["b"] = _rules_ab(at, bt, len(nt_ids), secondary, a["kind"] == "decision", out["matched"])
    oks = [r["ok"] for r in rules.values()]
    noisy = any(r["ok"] and r.get("within_noise") for r in rules.values())
    if any(r.get("below_floor") for r in rules.values()):
        out["verdict"] = "INCOMPLETE"
    elif any(o is False for o in oks):
        out["verdict"] = "FAIL"
    elif any(o is None for o in oks):
        out["verdict"] = "INCOMPLETE"
    else:
        out["verdict"] = "NOT DEMONSTRATED" if noisy else "PASS"
    return out


def _rules_ab(at, bt, n_common, secondary, decision, matched):
    """(a) wrong-write rate <= the baseline's; (b) good-write rate >= the baseline's. `at` is the arm's tally at its matched tau
    (decision arms) or at its word-high point (text arms); None means no tau reaches the baseline's wrong-write rate."""
    if at is None:
        if decision and matched and not matched["ever_writes"]:
            a = _incomplete("the arm made no writes at any tau, so its wrong-write rate is undefined")
            b = {
                "ok": False, "metric": "good-write rate", "n": bt["n_expansion"], "arm": 0.0, "baseline": bt["good_write_rate"],
                "common_n": n_common, "all_class": secondary,
            }  # fmt: skip
            return a, b
        note = "no tau reaches the baseline's wrong-write rate"
        return ({"ok": False, "note": note, "common_n": n_common, "all_class": secondary},) * 2
    if at["writes"] == 0:
        a = _incomplete("the arm made no writes, so its wrong-write rate is undefined")
    else:
        a = {
            "ok": at["wrong_write_rate"] <= bt["wrong_write_rate"],
            "metric": "wrong-write rate",
            "n": at["writes"],
            "baseline_n": bt["writes"],
            "common_n": n_common,
            "arm": at["wrong_write_rate"],
            "baseline": bt["wrong_write_rate"],
            "all_class": secondary,
            "within_noise": _overlap(at["wrong_write_wilson"], bt["wrong_write_wilson"]),
        }
    if at["n_expansion"] == 0 or bt["good_write_rate"] is None:
        b = _incomplete("no expansion gold items among the common non-trivial items, so the good-write rate is undefined")
    else:
        b = {
            "ok": at["good_write_rate"] >= bt["good_write_rate"],
            "metric": "good-write rate",
            "n": at["n_expansion"],
            "common_n": n_common,
            "arm": at["good_write_rate"],
            "baseline": bt["good_write_rate"],
            "all_class": secondary,
            "within_noise": _overlap(at["good_write_wilson"], bt["good_write_wilson"]),
        }
    return a, b


# ---- rendering ------------------------------------------------------------------------------------------------


def _ci(w):
    return "" if w is None else f" [{w[0]:.2f}, {w[1]:.2f}]"


def _cell(c):
    if c.get("note"):
        return f"n={c['n']}; {c['note']}"
    return f"{_pct(c['accuracy'])} ({c['correct']}/{c['n']}){_ci(c['wilson'])}" if c["n"] else "n/a (n=0)"


def _md_row(*cells):
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _md_table(header, rows):
    return [_md_row(*header), "|" + "---|" * len(header), *[_md_row(*r) for r in rows]]


def _section_items(rep):
    it = rep["items"]
    base = f"`{rep['baseline']}`" + ("" if rep["baseline_present"] else " (NO RESULTS FOUND: comparisons are unavailable)")
    return [
        "## Items",
        "",
        f"- verify items: {it['verify']} (no-call controls, never scored: {it['no_call']})",
        f"- exact gold (controls): {it['exact']}; expansion gold: {it['expansion_independent']} independent + "
        f"{it['expansion_incumbent']} incumbent-derived; negatives: {it['negative']}",
        f"- ambiguous / no gold (excluded from accuracy): {it['ambiguous']}",
        f"- single-candidate items: {it['single_candidate']}; items with 2+ candidates: {it['multi_candidate']}",
        "- acquire pairs are judged-only: they have no gold, so `score` ignores their result rows (see export-judge)",
        f"- baseline: {base}",
        *(
            [
                "- post-hoc framing: arms ending in @v2 were asked with a question framing chosen AFTER the v1 results "
                "were seen. They are "
                "reported next to v1, never instead of it; every v2 pick is a title and abstention is by confidence (tau)."
            ]
            if any(is_v2(a) for a in rep["arms"])
            else []
        ),
        "",
    ]


def _section_accuracy(names, arms):
    header = ["arm", *[CLASS_LABEL[c] for c in CLASS_ORDER], "single-candidate", "2+ candidates"]
    rows = []
    for a in names:
        m = arms[a]
        cells = [_cell(m["classes"][c]) if c in m["classes"] else "n/a (n=0)" for c in CLASS_ORDER]
        rows.append([_disp(a), *cells, _cell(m["by_candidates"]["single"]), _cell(m["by_candidates"]["multi"])])
    out = [
        "## Accuracy by class",
        "",
        "A failure counts as a miss. A pick is correct when it is in the item's accepted set (negatives: none).",
        "",
        *_md_table(header, rows),
    ]
    counts = [
        f"{_disp(a)}: {arms[a]['accept_counts']['exact']} chose the exact title, "
        f"{arms[a]['accept_counts']['expansion']} an accepted expansion"
        for a in names
        if arms[a]["accept_counts"]["exact"] or arms[a]["accept_counts"]["expansion"]
    ]
    if counts:
        out += ["", "On items with more than one accepted answer: " + "; ".join(counts)]
    return [*out, ""]


def _wl(t):
    return f"{_pct(t['wrong_write_rate'])} ({t['wrong']}/{t['writes']}){_ci(t['wrong_write_wilson'])}"


def _gl(t):
    return f"{_pct(t['good_write_rate'])} ({t['good_expansion']}/{t['n_expansion']}){_ci(t['good_write_wilson'])}"


def _missed(t):
    m = t["missed"]
    return ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in m.items() if v) or "-"


def _review(t):
    r = t["review"]
    return "; ".join(f"{c.replace('expansion_', 'exp-')} {v['per_100']:.0f}/100" for c, v in r.items()) or "-"


def _consequence_rows(label, t):
    return [
        label,
        f"{t['good']}",
        _wl(t),
        _gl(t),
        _missed(t),
        _review(t),
        t["harmful_flags"],
        f"{t['exact']['correct']}/{t['exact']['n']}" if t["exact"]["n"] else "-",
    ]


def _section_consequences(names, arms):
    intro = (
        "What actually lands in the glossary, the way `glossary_verify.apply_results` acts on an answer: a high-confidence "
        "expansion of the term is WRITTEN (a good write if it is in the accepted set, otherwise a wrong "
        "write); a high-confidence "
        "respelling is flagged for review; low confidence and no answer are flagged; the term itself writes "
        "nothing. The synthetic "
        "negatives have every expansion candidate removed, so a wrong pick there is review time, never a wrong write unless the "
        "arm invents an expansion. Decision arms are shown at their matched tau and at tau 0.50 and 0.80, "
        "over the items the arm ran."
    )
    header = [
        "arm",
        "good writes",
        "wrong-write rate",
        "good-write rate (expansion gold)",
        "missed writes",
        "review load",
        "harmful flags",
        "exact controls right",
    ]
    rows = []
    for a in names:
        m = arms[a]
        if m["consequences"] is not None:
            rows.append(_consequence_rows(_disp(a), m["consequences"]))
        for key, t in (m.get("consequence_points") or {}).items():
            label = f"{_disp(a)} at tau {t['tau']:.2f}" + (" (matched)" if key == "matched" else "")
            rows.append(_consequence_rows(label, t))
    return ["## Consequences", "", intro, "", *_md_table(header, rows), ""]


def _section_hc(names, arms):
    header = [
        "arm",
        "accepted",
        "wrong",
        "false-accept rate",
        "true-accept (right accepted / gold positives)",
        "non-trivial false-accept",
    ]
    rows = []
    for a in names:
        h = arms[a]["hc"]
        if h is None:
            rows.append([_disp(a), "see operating curve", "", "", "", ""])
            continue
        nt = h["non_trivial"]
        rows.append(
            [
                _disp(a),
                h["accepted"],
                h["wrong"],
                f"{_pct(h['false_accept_rate'])} (n={h['accepted']}){_ci(h['false_accept_wilson'])}",
                f"{_pct(h['true_accept_rate'])} ({h['true_accepts']}/{h['positives']})",
                f"{_pct(nt['false_accept_rate'])} (n={nt['accepted']})",
            ]
        )
    intro = (
        "Secondary, the earlier measure: of the labelled items where the arm picked a non-none title at high confidence, the "
        "share that is wrong. It counts harmless review noise (a wrong pick that apply_results would only flag) as an error, so "
        "it no longer decides rule (a)."
    )
    return ["## High-confidence false accepts (secondary)", "", intro, "", *_md_table(header, rows), ""]


def _section_curves(names, arms):
    out = [
        "## Operating curve",
        "",
        "The primary table is the NON-TRIVIAL curve (expansions + negatives), the one the rules use: for "
        "each tau, the writes the "
        "arm would make, its wrong-write rate and its good-write rate. The last column is the secondary "
        "all-class (exact controls "
        "included) false-accept rate.",
        "",
    ]
    curves = [a for a in names if arms[a]["curve_nt"]]
    if not curves:
        out.append("No decision-arm results yet.")
    for a in curves:
        rows = []
        for p in arms[a]["curve_nt"]:
            wl = f"{_pct(p['wrong_write_rate'])} ({p['wrong']}/{p['writes']})"
            rows.append(
                [
                    f"{p['tau']:.2f}",
                    p["writes"],
                    wl,
                    _pct(p["good_write_rate"]),
                    f"{_pct(p['all_class_false_accept'])} ({p['all_class_accepted']} accepted)",
                ]
            )
        header = ["tau", "writes (non-trivial)", "wrong-write rate", "good-write rate", "all-class false-accept (secondary)"]
        out += [f"### {_disp(a)}", "", *_md_table(header, rows), ""]
    return out


def _section_matched(rep, names, arms):
    out = [
        "## Matched operating point",
        "",
        "For each decision arm: the smallest tau whose wrong-write rate is no higher than the baseline's, on "
        "the non-trivial items "
        "(expansions + negatives) both ran. **The matched tau is chosen on the same data it is scored on, so the in-sample rates "
        "are optimistic.** The held-out line picks tau on a deterministic half of the common items (a seeded "
        "split by item id) and "
        "reports the rates on the other half.",
        "",
    ]
    found = False
    for a in names:
        m = arms[a].get("matched")
        if arms[a]["kind"] != "decision" or not m:
            continue
        found = True
        if m.get("note"):
            out.append(f"- {_disp(a)}: not evaluated: {m['note']}")
            continue
        if m["tau"] is None:
            out.append(
                f"- {_disp(a)}: no tau reaches the baseline's wrong-write rate "
                f"({_pct(m['baseline_wrong_write_rate'])}; n={m['n_common']} common items)"
            )
        else:
            out.append(
                f"- {_disp(a)}: tau {m['tau']:.2f}; wrong-write {_pct(m['arm_wrong_write_rate'])} vs baseline "
                f"{_pct(m['baseline_wrong_write_rate'])}; good-write {_pct(m['arm_good_write_rate'])} vs baseline "
                f"{_pct(m['baseline_good_write_rate'])} (n={m['n_common']} common items, in-sample)"
            )
        ho = m.get("held_out") or {}
        if ho.get("tau_a") is not None and "arm_wrong_write_rate_b" in ho:
            out.append(
                f"  - held-out: tau {ho['tau_a']:.2f} chosen on {ho['n_a']} items, scored on the other {ho['n_b']}: wrong-write "
                f"{_pct(ho['arm_wrong_write_rate_b'])} vs baseline {_pct(ho['baseline_wrong_write_rate_b'])}; good-write "
                f"{_pct(ho['arm_good_write_rate_b'])} vs baseline {_pct(ho['baseline_good_write_rate_b'])}"
            )
        elif ho:
            out.append(
                f"  - held-out: no tau on the first half ({ho.get('n_a', 0)} items) reaches the baseline's rate, or a "
                f"half is empty"
            )
    if not found:
        out.append("No decision arm to match." if rep["baseline_present"] else "No baseline results: nothing to match against.")
    return [*out, ""]


def _section_calibration(names, arms):
    rows = []
    for a in names:
        cal = arms[a]["calibration"]
        pc = cal["pick_conf"]
        sc = cal["scores"]
        rows.append(
            [
                _disp(a),
                f"{_fmt(pc['correct_median'], 3)} (n={pc['n_correct']}) vs {_fmt(pc['wrong_median'], 3)} (n={pc['n_wrong']})"
                if arms[a]["kind"] == "decision"
                else "-",
                f"{_fmt(sc['correct_median'], 3)} (n={sc['n_correct']}) vs {_fmt(sc['other_median'], 3)} (n={sc['n_other']})"
                if sc
                else "-",
            ]
        )
    out = [
        "## Score distributions",
        "",
        "Calibration made visible: the median confidence of an arm's correct vs wrong picks on gold items, "
        "and for a per-candidate "
        "noul arm the median score of the correct title(s) vs the other candidates. A per-candidate noul is not a choice "
        "probability: the scores of one item's candidates need not sum to anything.",
        "",
        *_md_table(
            ["arm", "pick confidence: correct vs wrong (median)", "candidate score: correct title vs others (median)"], rows
        ),
        "",
    ]
    return out


def _section_order(names, arms):
    rows = []
    for a in names:
        o = arms[a]["order"]
        rows.append([_disp(a), o["n"], o["changed"], f"{_pct(o['rate'])}{_ci(o['wilson'])}"])
    intro = "Items with 2+ candidates that have both a forward and a reversed pick."
    return ["## Order sensitivity", "", intro, "", *_md_table(["arm", "n", "pick changed", "rate"], rows), ""]


def _section_failures(names, arms):
    rows = []
    for a in names:
        m = arms[a]
        f, lat = m["failures"], m["latency"]
        kinds = ", ".join(f"{k}: {n}" for k, n in sorted(f["by_kind"].items())) or "-"
        tokens = ", ".join(f"{k}: {v}" for k, v in sorted(m["tokens"].items())) or "-"
        latency = f"{_fmt(lat['median'], 2)} / {_fmt(lat['p95'], 2)} (n={lat['n']})"
        off = m["off_list"]
        off_cell = f"{_pct(_rate(off['n'], off['of']))} ({off['n']}/{off['of']})" if off["of"] else "-"
        rows.append([_disp(a), f["n_rows"], f["total"], _pct(f["rate"]), kinds, off_cell, latency, tokens])
    header = [
        "arm",
        "rows",
        "failures",
        "rate",
        "by kind",
        "answers outside the candidate list",
        "latency median / p95 (s)",
        "tokens",
    ]
    return ["## Failures, latency, tokens", "", *_md_table(header, rows), ""]


def _section_agreement(rep, names):
    rows = []
    for a in names:
        cells = []
        for b in names:
            g = rep["agreement"][a][b]
            cells.append(f"{_pct(_rate(g['agree'], g['n']))} (n={g['n']})")
        rows.append([_disp(a), *cells])
    intro = "Share of items on which two arms' forward picks are the same title (n = items both answered)."
    return ["## Agreement", "", intro, "", *_md_table(["", *map(_disp, names)], rows), ""]


def _state(r):
    if r["ok"] is None:
        return "incomplete"
    if not r["ok"]:
        return "FAIL (within noise)" if r.get("within_noise") else "NO"
    return "not demonstrated" if r.get("within_noise") else "ok"


def _rule_cell(r, text):
    return f"{_state(r)}: {text}" + ("; within noise" if r.get("within_noise") and r["ok"] else "")


def _rate_cell(r, what):
    """Rules (a) and (b): the non-trivial headline, with the all-class figure as the secondary part of the cell."""
    if r["ok"] is None or "arm" not in r:
        return r.get("note") or "-"
    sec = r.get("all_class") or {}
    sec_arm, sec_base = sec.get("arm"), sec.get("baseline")
    head = f"{_pct(r['arm'])} vs baseline {_pct(r['baseline'])} (n={r['n']} {what}, {r['common_n']} common items)"
    return head + f"; all classes: {_pct(sec_arm)} vs {_pct(sec_base)} (n={sec.get('n', 0)})"


def _d_cell(d):
    if d["ok"] is None or not d["classes"]:
        return d.get("note") or "-"
    names = {"expansion_independent": "independent", "expansion_incumbent": "incumbent-derived"}
    parts = [f"pooled {_pct(d['arm'])} vs floor {_pct(d['floor'])} (n={d['pooled_n']})"]
    parts += [f"{names[c]} {_pct(v['arm'])} vs floor {_pct(v['floor'])} (n={v['n']})" for c, v in d["classes"].items()]
    if "balanced" in d:
        parts.append(f"balanced accuracy {_pct(d['balanced']['arm'])} vs floor {_pct(d['balanced']['floor'])}")
    return "; ".join(parts)


def _section_verdicts(rep):
    intro = (
        "(a) WRONG-WRITE rate (wrong writes / writes, as `apply_results` would make them) <= baseline's; (b) GOOD-WRITE rate "
        "(good writes / expansion-gold items) at the matched tau >= baseline's; (c) order sensitivity <= 5%; (d) beats "
        "always-candidate-1 on the expansion items pooled (the per-class split is reporting only; `>=` is no worse, "
        "overlapping intervals are not demonstrated; balanced accuracy shown); (e) failure rate <= 2%. Rules "
        "(a), (b) and (d) are "
        "decided on the non-trivial items (expansions + negatives); the all-class figure is secondary and the exact controls "
        "never carry a rule.",
        "",
        "Verdicts: **PASS** every rule holds and none of them only within noise. **FAIL** at least one rule does not hold "
        "(`FAIL (within noise)` when the point estimate misses but the interval reaches the limit). **NOT DEMONSTRATED** no rule "
        "fails but at least one holds only within noise (the intervals overlap), so the simpler existing option stays. "
        "**INCOMPLETE** a rule could not be evaluated, or a rule is below its sample-size floor (rules a, b, d: 90% of the item "
        "set's non-trivial items, of each expansion class and of the negatives, plus "
        f"{MIN_COMMON_N} common labelled items; rule c: {MIN_REVERSED_PAIRS} reversed pairs; rule e: {MIN_COMMON_N} requests): "
        "a floor shortfall outranks a FAIL. No winner is declared.",
        "",
    )
    rows = []
    for a, v in rep["verdicts"].items():
        r = v["rules"]
        c, e = r["c"], r["e"]
        cells = [
            _rule_cell(r["a"], _rate_cell(r["a"], "writes")),
            _rule_cell(r["b"], _rate_cell(r["b"], "expansion gold items")),
            _rule_cell(c, f"{_pct(c['rate'])} (n={c['n']})" if c.get("n") else "no reversed rows (n=0)")
            if c.get("rate") is not None
            else _rule_cell(c, c.get("note") or "-"),
            _rule_cell(r["d"], _d_cell(r["d"])),
            _rule_cell(e, f"{_pct(e['rate'])} (n={e['n']})")
            if e.get("rate") is not None
            else _rule_cell(e, e.get("note") or "no rows"),
        ]
        rows.append([_disp(a), *cells, f"**{v['verdict']}**"])
    if not rows:
        rows = [["(no arm other than the baseline and the floor)", "", "", "", "", "", ""]]
    return ["## Rule verdicts", "", *intro, *_md_table(["arm", "(a)", "(b)", "(c)", "(d)", "(e)", "verdict"], rows)]


def _section_judged(rep):
    table = rep.get("judged")
    if table is None:
        return []
    out = [
        "## Blind-judged accuracy (headline)",
        "",
        "From blind judging of the items on which arms disagreed: how often an arm's answer was judged best or worst. "
        "`sole` counts the items where the arm alone gave the answer judged best. This is the headline table; the gold-based "
        "tables below are secondary.",
        "",
    ]
    if not table:
        return [*out, "No judged items yet.", ""]
    for stage in sorted(table):
        rows = []
        for arm, t in sorted(table[stage].items(), key=lambda kv: (-kv[1]["net"], kv[0])):
            rows.append([arm, t["judged"], t["best"], t["worst"], f"{t['net']:+d}", t["sole"]])
        out += [f"### {stage}", "", *_md_table(["arm", "judged items", "best", "worst", "net", "sole winner"], rows), ""]
    return out


def render_markdown(rep):
    arms = rep["arms"]
    names = [*(a for a in arms if a != FLOOR_ARM), FLOOR_ARM]
    head = [
        "# Glossary bake-off: verify-stage scores",
        "",
        "Offline scoring of `run` results against the item set. Rates show n and a Wilson 95% interval. "
        "No winner is declared; the verdict table applies the maintainer's rules.",
        "",
    ]
    parts = [
        head,
        _section_items(rep),
        _section_judged(rep),
        _section_accuracy(names, arms),
        _section_consequences(names, arms),
        _section_hc(names, arms),
        _section_curves(names, arms),
        _section_matched(rep, names, arms),
        _section_calibration(names, arms),
        _section_order(names, arms),
        _section_failures(names, arms),
        _section_agreement(rep, names),
        _section_verdicts(rep),
    ]
    return "\n".join(line for part in parts for line in part) + "\n"
