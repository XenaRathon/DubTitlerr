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

Span-01 Lite rows carry per-candidate scores: its pick is the highest-scoring candidate when that score is at least 0.5
(else none) and its confidence is that score.

Rates carry n and a Wilson 95% interval. Arm vs arm comparisons are made on the items BOTH ran, and say "within noise"
when the intervals overlap. The verdict table applies the five rules and declares no winner."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

FLOOR_ARM = "always-candidate-1"
ORDER_LIMIT = 0.05
FAILURE_LIMIT = 0.02
SPAN_PICK_MIN = 0.5
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
    if "scores" in p and isinstance(p["scores"], dict):  # Span-01 Lite: per-candidate probabilities
        scored = [(t, _num(v)) for t, v in p["scores"].items()]
        scored = [(t, v) for t, v in scored if v is not None]
        if not scored:
            return None
        best_t, best_v = max(scored, key=lambda tv: tv[1])  # ties: first in the order the candidates were shown
        return Pick(best_t if best_v >= SPAN_PICK_MIN else "", conf=best_v)
    if "choice" in p:  # a decision arm
        title = p.get("canonical") or ""
        conf = p.get("confidence")
        return Pick(title, conf=float(conf) if isinstance(conf, (int, float)) and not isinstance(conf, bool) else None)
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


def _arm_metrics(arm, items_by_id, classes, fwd, rev, arm_rows, tau_step, item_order):
    """Everything about one arm, over the items it ran."""
    ids = [i for i in item_order if i in fwd and classes.get(i) is not None]  # items with a forward row
    pairs = [(items_by_id[i], fwd[i], classes[i]) for i in ids]
    out = {"classes": {}, "by_candidates": {}, "accept_choices": {}}
    for cls in CLASS_ORDER:
        sel = [(it, pk) for it, pk, c in pairs if c == cls]
        if sel:
            out["classes"][cls] = _accuracy(sel)
    labelled = [(it, pk) for it, pk, c in pairs if c in CLASS_ORDER]
    for name, test in (("single", lambda it: len(it["candidates"]) == 1), ("multi", lambda it: len(it["candidates"]) >= 2)):
        out["by_candidates"][name] = _accuracy([(it, pk) for it, pk in labelled if test(it)])
    for it, pk in labelled:
        if pk is not None and not it.get("negative") and len(_accept(it)) > 1 and correct(it, pk):
            out["accept_choices"][pk.title] = out["accept_choices"].get(pk.title, 0) + 1
    picks = [pk for _, pk, _ in pairs]
    decision = _is_decision(picks)
    out["kind"] = "decision" if decision else "text"
    out["hc"] = None if decision else _hc(pairs)
    if not decision:
        out["hc"]["non_trivial"] = _hc(pairs, only=NON_TRIVIAL)
    out["curve"] = None
    if decision:
        out["curve"] = [{"tau": t, **_hc(pairs, tau=t)} for t in _taus(tau_step)]
    # order sensitivity: items with >= 2 candidates that have both a forward and a reverse pick
    n = changed = 0
    for i in ids:
        if len(items_by_id[i]["candidates"]) >= 2 and fwd.get(i) is not None and rev.get(i) is not None:
            n += 1
            changed += fwd[i].title.casefold() != rev[i].title.casefold()
    out["order"] = {"n": n, "changed": changed, "rate": _rate(changed, n), "wilson": wilson(changed, n)}
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


def build_report(items, rows, baseline="qwen-local", tau_step=0.05):
    items_by_id = {i["id"]: i for i in items}
    classes = {i["id"]: item_class(i) for i in items}
    order = [i["id"] for i in items]
    counts = {"verify": len(items), "no_call": sum(1 for c in classes.values() if c is None)}
    for cls in (*CLASS_ORDER, "ambiguous"):
        counts[cls] = sum(1 for c in classes.values() if c == cls)
    counts["single_candidate"] = sum(1 for i in items if classes[i["id"]] and len(i["candidates"]) == 1)
    counts["multi_candidate"] = sum(1 for i in items if classes[i["id"]] and len(i["candidates"]) >= 2)

    by_arm = {}
    for (rid, arm, ordr), row in rows.items():
        if rid in items_by_id:
            by_arm.setdefault(arm, []).append((ordr, rid, row))
    picks = {}  # arm -> {"fwd": {id: Pick|None}, "rev": {...}}
    arm_rows = {}
    for arm, entries in by_arm.items():
        picks[arm] = {"fwd": {}, "rev": {}}
        arm_rows[arm] = [r for _, _, r in entries]
        for ordr, rid, row in entries:
            if ordr in ("fwd", "rev"):
                picks[arm][ordr][rid] = row_pick(row)
    floor = _floor_picks(items, classes)

    arms = {}
    for arm in sorted(by_arm):
        arms[arm] = _arm_metrics(arm, items_by_id, classes, picks[arm]["fwd"], picks[arm]["rev"], arm_rows[arm], tau_step, order)
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
        "baseline": baseline, "baseline_present": present, "tau_step": tau_step, "items": counts, "arms": arms,
        "agreement": agreement, "verdicts": {}, "matched_note": None,
    }  # fmt: skip
    for arm in arms:
        if arm == FLOOR_ARM or arm == baseline:
            continue
        report["verdicts"][arm] = _verdict(arm, report, items_by_id, classes, fwd_all, order, baseline, present, floor, tau_step)
        if arms[arm]["kind"] == "decision":
            arms[arm]["matched"] = report["verdicts"][arm].get("matched")
    return report


def _verdict(arm, report, items_by_id, classes, fwd_all, order, baseline, present, floor, tau_step):
    a = report["arms"][arm]
    rules = {k: {"ok": None, "note": "no baseline results" if not present else ""} for k in "abcde"}
    out = {"rules": rules, "matched": None}
    # (c) order sensitivity and (e) failure rate do not need the baseline
    o = a["order"]
    rules["c"] = {"ok": None if o["n"] == 0 else o["rate"] <= ORDER_LIMIT, "n": o["n"], "rate": o["rate"], "limit": ORDER_LIMIT}
    f = a["failures"]
    rules["e"] = {
        "ok": None if f["n_rows"] == 0 else f["rate"] <= FAILURE_LIMIT,
        "n": f["n_rows"],
        "rate": f["rate"],
        "limit": FAILURE_LIMIT,
    }
    # (d) beats the floor on non-trivial gold, on the items this arm ran
    nt = [i for i in order if i in fwd_all[arm] and classes.get(i) in NON_TRIVIAL]
    if not nt:
        rules["d"] = {"ok": False, "n": 0, "note": "no non-trivial items were run"}
    else:
        arm_acc = _accuracy([(items_by_id[i], fwd_all[arm][i]) for i in nt])
        floor_acc = _accuracy([(items_by_id[i], floor.get(i)) for i in nt])
        rules["d"] = {
            "ok": arm_acc["accuracy"] > floor_acc["accuracy"],
            "n": len(nt),
            "arm": arm_acc["accuracy"],
            "floor": floor_acc["accuracy"],
            "within_noise": _overlap(arm_acc["wilson"], floor_acc["wilson"]),
        }
    if present:
        base = fwd_all[baseline]
        common = [i for i in order if i in fwd_all[arm] and i in base and classes.get(i) is not None]
        arm_pairs = [(items_by_id[i], fwd_all[arm][i], classes[i]) for i in common]
        base_pairs = [(items_by_id[i], base[i], classes[i]) for i in common]
        bh = _hc(base_pairs)
        base_fa = bh["false_accept_rate"] or 0.0
        if a["kind"] == "decision":
            match = None
            for tau in _taus(tau_step) if common else ():
                h = _hc(arm_pairs, tau=tau)
                if (h["false_accept_rate"] or 0.0) <= base_fa:
                    match = (tau, h)
                    break
            hit = match[1] if match else None
            out["matched"] = {
                "tau": match[0] if match else None,
                "n_common": len(common),
                "baseline_false_accept": base_fa,
                "baseline_true_accept": bh["true_accept_rate"],
                "arm_false_accept": (hit["false_accept_rate"] or 0.0) if hit else None,
                "arm_true_accept": hit["true_accept_rate"] if hit else None,
            }
            ah = match[1] if match else None
        else:
            ah = _hc(arm_pairs)
        if ah is None:
            rules["a"] = {"ok": False, "n": len(common), "note": "no tau reaches the baseline's false-accept rate"}
            rules["b"] = {"ok": False, "n": len(common), "note": "no matched operating point"}
        else:
            arm_fa = ah["false_accept_rate"] or 0.0
            rules["a"] = {
                "ok": arm_fa <= base_fa, "n": ah["accepted"], "arm": arm_fa, "baseline": base_fa, "baseline_n": bh["accepted"],
                "within_noise": _overlap(ah["false_accept_wilson"], bh["false_accept_wilson"]),
            }  # fmt: skip
            rules["b"] = {
                "ok": (ah["true_accept_rate"] or 0.0) >= (bh["true_accept_rate"] or 0.0), "n": ah["positives"],
                "arm": ah["true_accept_rate"], "baseline": bh["true_accept_rate"],
                "within_noise": _overlap(ah["true_accept_wilson"], bh["true_accept_wilson"]),
            }  # fmt: skip
    oks = [r["ok"] for r in rules.values()]
    out["verdict"] = "FAIL" if any(o is False for o in oks) else ("INCOMPLETE" if any(o is None for o in oks) else "PASS")
    return out


# ---- rendering ------------------------------------------------------------------------------------------------


def _ci(w):
    return "" if w is None else f" [{w[0]:.2f}, {w[1]:.2f}]"


def _cell(c):
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
        f"- baseline: {base}",
        "",
    ]


def _section_accuracy(names, arms):
    header = ["arm", *[CLASS_LABEL[c] for c in CLASS_ORDER], "single-candidate", "2+ candidates"]
    rows = []
    for a in names:
        m = arms[a]
        cells = [_cell(m["classes"][c]) if c in m["classes"] else "n/a (n=0)" for c in CLASS_ORDER]
        rows.append([a, *cells, _cell(m["by_candidates"]["single"]), _cell(m["by_candidates"]["multi"])])
    out = [
        "## Accuracy by class",
        "",
        "A failure counts as a miss. A pick is correct when it is in the item's accepted set (negatives: none).",
        "",
        *_md_table(header, rows),
    ]
    chosen = {a: arms[a]["accept_choices"] for a in names if arms[a]["accept_choices"]}
    if chosen:
        parts = [f"{a}: " + ", ".join(f"{t}: {n}" for t, n in sorted(ch.items())) for a, ch in chosen.items()]
        out += ["", "Accepted answer chosen on items that have more than one: " + "; ".join(parts)]
    return [*out, ""]


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
            rows.append([a, "see operating curve", "", "", "", ""])
            continue
        nt = h["non_trivial"]
        rows.append(
            [
                a,
                h["accepted"],
                h["wrong"],
                f"{_pct(h['false_accept_rate'])} (n={h['accepted']}){_ci(h['false_accept_wilson'])}",
                f"{_pct(h['true_accept_rate'])} ({h['true_accepts']}/{h['positives']})",
                f"{_pct(nt['false_accept_rate'])} (n={nt['accepted']})",
            ]
        )
    intro = (
        "Of the labelled items where the arm picked a non-none title at high confidence, the share that is wrong. "
        "Text arms: the word high. Decision arms: see the operating curve."
    )
    return ["## High-confidence false accepts", "", intro, "", *_md_table(header, rows), ""]


def _section_curves(names, arms):
    out = ["## Operating curve", ""]
    curves = [a for a in names if arms[a]["curve"]]
    if not curves:
        out.append("No decision-arm results yet.")
    for a in curves:
        rows = []
        for p in arms[a]["curve"]:
            rate = f"{_pct(p['false_accept_rate'])} ({p['wrong']}/{p['accepted']})"
            rows.append([f"{p['tau']:.2f}", p["accepted"], rate, _pct(p["true_accept_rate"])])
        out += [f"### {a}", "", *_md_table(["tau", "accepted", "false-accept rate", "true-accept rate"], rows), ""]
    return out


def _section_matched(rep, names, arms):
    out = [
        "## Matched operating point",
        "",
        "For each decision arm: the smallest tau whose false-accept rate is no higher than the baseline's, "
        "on the items both ran.",
        "",
    ]
    found = False
    for a in names:
        m = arms[a].get("matched")
        if arms[a]["kind"] != "decision" or not m:
            continue
        found = True
        if m["tau"] is None:
            out.append(
                f"- {a}: no tau reaches the baseline's false-accept rate "
                f"({_pct(m['baseline_false_accept'])}; n={m['n_common']} common items)"
            )
        else:
            out.append(
                f"- {a}: tau {m['tau']:.2f}; false-accept {_pct(m['arm_false_accept'])} vs baseline "
                f"{_pct(m['baseline_false_accept'])}; true-accept {_pct(m['arm_true_accept'])} vs baseline "
                f"{_pct(m['baseline_true_accept'])} (n={m['n_common']} common items)"
            )
    if not found:
        out.append("No decision arm to match." if rep["baseline_present"] else "No baseline results: nothing to match against.")
    return [*out, ""]


def _section_order(names, arms):
    rows = []
    for a in names:
        o = arms[a]["order"]
        rows.append([a, o["n"], o["changed"], f"{_pct(o['rate'])}{_ci(o['wilson'])}"])
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
        rows.append([a, f["n_rows"], f["total"], _pct(f["rate"]), kinds, latency, tokens])
    header = ["arm", "rows", "failures", "rate", "by kind", "latency median / p95 (s)", "tokens"]
    return ["## Failures, latency, tokens", "", *_md_table(header, rows), ""]


def _section_agreement(rep, names):
    rows = []
    for a in names:
        cells = []
        for b in names:
            g = rep["agreement"][a][b]
            cells.append(f"{_pct(_rate(g['agree'], g['n']))} (n={g['n']})")
        rows.append([a, *cells])
    intro = "Share of items on which two arms' forward picks are the same title (n = items both answered)."
    return ["## Agreement", "", intro, "", *_md_table(["", *names], rows), ""]


def _rule_cell(r, text):
    tag = "n/a" if r["ok"] is None else ("ok" if r["ok"] else "NO")
    return f"{tag}: {text}" + ("; within noise" if r.get("within_noise") else "")


def _vs(r, label="baseline"):
    if "arm" not in r:
        return r.get("note") or "-"
    other = r.get("baseline", r.get("floor"))
    return f"{_pct(r['arm'])} vs {label} {_pct(other)} (n={r.get('n', 0)})"


def _section_verdicts(rep):
    intro = (
        "(a) high-confidence false-accept <= baseline's; (b) true-accept at the matched point >= baseline's; "
        "(c) order sensitivity <= 5%; (d) beats always-candidate-1 on non-trivial gold (expansion + negatives); "
        "(e) failure rate <= 2%. PASS needs all five. INCOMPLETE means a rule could not be evaluated. No winner is declared."
    )
    rows = []
    for a, v in rep["verdicts"].items():
        r = v["rules"]
        c, e = r["c"], r["e"]
        cells = [
            _rule_cell(r["a"], _vs(r["a"])),
            _rule_cell(r["b"], _vs(r["b"])),
            _rule_cell(c, f"{_pct(c['rate'])} (n={c['n']})" if c["n"] else "no reversed rows (n=0)"),
            _rule_cell(r["d"], _vs(r["d"], "floor") if r["d"]["n"] else r["d"].get("note", "-")),
            _rule_cell(e, f"{_pct(e['rate'])} (n={e['n']})" if e["n"] else "no rows"),
        ]
        rows.append([a, *cells, f"**{v['verdict']}**"])
    if not rows:
        rows = [["(no arm other than the baseline and the floor)", "", "", "", "", "", ""]]
    return ["## Rule verdicts", "", intro, "", *_md_table(["arm", "(a)", "(b)", "(c)", "(d)", "(e)", "verdict"], rows)]


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
        _section_accuracy(names, arms),
        _section_hc(names, arms),
        _section_curves(names, arms),
        _section_matched(rep, names, arms),
        _section_order(names, arms),
        _section_failures(names, arms),
        _section_agreement(rep, names),
        _section_verdicts(rep),
    ]
    return "\n".join(line for part in parts for line in part) + "\n"
