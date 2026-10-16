"""`glossary_bakeoff score`: the offline scorer for the glossary-stage bake-off. Synthetic items and result rows only;
no network, no model. The rules are the maintainer's, fixed in advance (see tools/glossary_score.py)."""

import json

import pytest

import tools.glossary_bakeoff as gb
import tools.glossary_score as gs

# ---- fixtures ----------------------------------------------------------------------------------


def _item(term, titles, gold=None, kind=None, accept=None, incumbent=False, ambiguous=False, negative=False, no_call=False):
    it = {
        "id": f"verify:S:{term}", "stage": "verify", "show": "S", "term": term, "list": "names", "verified": False,
        "candidates": [{"title": t, "score": 0.9 - i * 0.01} for i, t in enumerate(titles)], "no_call": no_call, "gold": gold,
    }  # fmt: skip
    if negative:
        it.update(id=f"verify-neg:S:{term}", negative=True, gold="none", gold_kind="negative", source_id=f"verify:S:{term}")
    elif gold:
        it.update(gold_kind=kind, gold_accept=accept or [gold], incumbent_derived=incumbent, gold_source="curated")
    elif ambiguous:
        it["gold_ambiguous"] = True
    return it


ITEMS = [
    _item("Ex1", ["Ex1"], "Ex1", "exact"),  # single-candidate exact
    _item("Ex2", ["Ex2", "Ex2 Jr"], "Ex2", "exact", ["Ex2", "Ex2 Jr"]),
    _item("Xa", ["Xa Prime", "Xa Zed"], "Xa Prime", "expansion", incumbent=False),
    _item("Xb", ["Xb Prime", "Xb Alt"], "Xb Prime", "expansion", incumbent=True),
    _item("Xc", ["Xc Prime"], "Xc Prime", "expansion", incumbent=False),  # single-candidate
    _item("Ng1", ["Ng1x", "Ng1y"], negative=True),
    _item("Ng2", ["Ng2x", "Ng2y"], negative=True),
    _item("Am", ["Am One", "Am Two"], ambiguous=True),
    _item("Nc", [], no_call=True),
]


def _write_items(tmp_path, items=ITEMS, name="items.jsonl"):
    p = tmp_path / name
    p.write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    return p


def _t(item_id, arm, canonical, conf="high", order="fwd", **kw):
    """A text-arm row (production parse shape)."""
    return {"id": item_id, "arm": arm, "order": order, "raw": "x", "parsed": {"canonical": canonical, "confidence": conf},
            "latency_s": kw.get("lat", 1.0), "usage": kw.get("usage"), "error": None}  # fmt: skip


def _d(item_id, arm, title, conf, order="fwd", **kw):
    """A decision-arm row: choice mapped to a title (or none), numeric confidence."""
    parsed = {"choice": "c1" if title else "none", "canonical": title, "probabilities": None, "confidence": conf}
    return {
        "id": item_id, "arm": arm, "order": order, "raw": {}, "latency_s": kw.get("lat", 0.5), "usage": kw.get("usage"),
        "error": None, "parsed": parsed,
    }  # fmt: skip


def _e(item_id, arm, error="HTTP 429", order="fwd"):
    return {
        "id": item_id,
        "arm": arm,
        "order": order,
        "raw": None,
        "parsed": None,
        "latency_s": 0.0,
        "usage": None,
        "error": error,
    }


def _write_rows(tmp_path, rows, name="res.jsonl"):
    p = tmp_path / name
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


IDS = {i["term"]: i["id"] for i in ITEMS}
NEG = {"Ng1": "verify-neg:S:Ng1", "Ng2": "verify-neg:S:Ng2"}


def _perfect(arm, text=True, conf=1.0):
    mk = (lambda i, t: _t(i, arm, t)) if text else (lambda i, t: _d(i, arm, t, conf))
    return [
        mk(IDS["Ex1"], "Ex1"), mk(IDS["Ex2"], "Ex2"), mk(IDS["Xa"], "Xa Prime"), mk(IDS["Xb"], "Xb Prime"),
        mk(IDS["Xc"], "Xc Prime"), mk(NEG["Ng1"], ""), mk(NEG["Ng2"], ""),
    ]  # fmt: skip


def _report(tmp_path, rows, baseline="qwen-local", tau_step=0.25, items=ITEMS, policy="legacy"):
    return gs.build_report(
        gs.load_items(str(_write_items(tmp_path, items))),
        gs.load_results([str(_write_rows(tmp_path, rows))]),
        baseline,
        tau_step,
        policy=policy,
    )


@pytest.fixture
def small_floors(monkeypatch):
    """The sample-size floors (100 common labelled items, 90% of the baseline's) off, for tests of one rule on a tiny set."""
    monkeypatch.setattr(gs, "MIN_COMMON_N", 1)
    monkeypatch.setattr(gs, "MIN_COMMON_FRAC", 0.0)
    monkeypatch.setattr(gs, "MIN_REVERSED_PAIRS", 0)


# ---- wilson ------------------------------------------------------------------------------------


def test_wilson_interval_values():
    assert gs.wilson(0, 0) is None
    lo, hi = gs.wilson(5, 10)
    assert (round(lo, 4), round(hi, 4)) == (0.2366, 0.7634)
    lo, hi = gs.wilson(0, 10)
    assert (round(lo, 4), round(hi, 4)) == (0.0, 0.2775)
    lo, hi = gs.wilson(10, 10)
    assert (round(lo, 4), round(hi, 4)) == (0.7225, 1.0)
    assert gs.wilson(50, 100)[0] > gs.wilson(5, 10)[0]  # more data, a narrower interval


# ---- loading -----------------------------------------------------------------------------------


def test_the_latest_row_per_key_wins_across_lines_and_files(tmp_path):
    a = _write_rows(tmp_path, [_t("i", "m", "Old"), _t("i", "m", "Newer")], "a.jsonl")
    b = _write_rows(tmp_path, [_t("i", "m", "Newest"), _t("j", "m", "J")], "b.jsonl")
    rows = gs.load_results([str(a), str(b)])
    assert rows[("i", "m", "fwd")]["parsed"]["canonical"] == "Newest" and len(rows) == 2


def test_a_latest_error_row_beats_an_earlier_good_one_and_is_a_failure_not_a_pick(tmp_path):
    rows = _perfect("m") + [_e(IDS["Ex1"], "m", "HTTP 500")]
    rep = _report(tmp_path, rows, baseline="m")
    arm = rep["arms"]["m"]
    assert arm["failures"]["total"] == 1 and arm["failures"]["by_kind"] == {"http-5xx": 1}
    ex = arm["classes"]["exact"]
    assert ex["n"] == 2 and ex["correct"] == 1  # the errored item counts as a miss, never a pick


def test_torn_and_foreign_lines_are_skipped(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text(json.dumps(_t("i", "m", "A")) + "\n" + '{"id": "x", "arm": "m", "ord\n' + "[1,2]\n", encoding="utf-8")
    assert list(gs.load_results([str(p)])) == [("i", "m", "fwd")]


# ---- classes and accuracy ------------------------------------------------------------------------


def test_classes_are_split_exact_expansion_by_incumbent_negatives_and_ambiguous_is_excluded(tmp_path):
    rep = _report(tmp_path, _perfect("m") + [_t(IDS["Am"], "m", "Am One")], baseline="m")
    c = rep["arms"]["m"]["classes"]
    assert c["exact"]["n"] == 2 and c["expansion_independent"]["n"] == 2 and c["expansion_incumbent"]["n"] == 1
    assert c["negative"]["n"] == 2 and "ambiguous" not in c
    assert rep["items"]["ambiguous"] == 1 and rep["items"]["no_call"] == 1  # reported, never scored
    assert all(c[k]["accuracy"] == 1.0 for k in c)
    assert rep["arms"]["m"]["classes"]["exact"]["wilson"] is not None


def test_a_pick_in_gold_accept_is_correct_and_the_chosen_one_is_recorded(tmp_path):
    rep = _report(tmp_path, [_t(IDS["Ex2"], "m", "Ex2 Jr")], baseline="m")
    assert rep["arms"]["m"]["classes"]["exact"]["correct"] == 1
    assert rep["arms"]["m"]["accept_choices"] == {
        "Ex2 Jr": 1
    }  # which accepted answer was chosen (here: the expansion, not the exact title)


def test_negatives_are_right_only_for_none(tmp_path):
    rows = [_t(NEG["Ng1"], "m", ""), _t(NEG["Ng2"], "m", "Ng2x", "low")]
    n = _report(tmp_path, rows, baseline="m")["arms"]["m"]["classes"]["negative"]
    assert (n["n"], n["correct"]) == (2, 1)


def test_single_candidate_items_are_reported_apart_from_multi_candidate_ones(tmp_path):
    rep = _report(tmp_path, _perfect("m"), baseline="m")
    by = rep["arms"]["m"]["by_candidates"]
    assert by["single"]["n"] == 2 and by["multi"]["n"] == 5  # Ex1, Xc / Ex2, Xa, Xb, Ng1, Ng2


# ---- high-confidence false accept, tau sweep, matched point, floor ------------------------------------


def test_hc_false_accept_for_a_text_arm_uses_the_word_high(tmp_path):
    rows = [
        _t(IDS["Ex1"], "m", "Ex1"),  # right, high
        _t(IDS["Xa"], "m", "Xa Zed"),  # wrong, high  -> false accept
        _t(IDS["Xb"], "m", "Xb Alt", "low"),  # wrong but LOW: not accepted
        _t(NEG["Ng1"], "m", "Ng1x"),  # any non-none on a negative, high -> false accept
        _t(NEG["Ng2"], "m", ""),  # none: not an accept at all
    ]
    hc = _report(tmp_path, rows, baseline="m")["arms"]["m"]["hc"]
    assert (hc["accepted"], hc["wrong"]) == (3, 2) and hc["false_accept_rate"] == pytest.approx(2 / 3)
    assert hc["true_accepts"] == 1 and hc["positives"] == 3  # gold positives among the items the arm ran: Ex1, Xa, Xb
    assert hc["false_accept_wilson"][0] < 2 / 3 < hc["false_accept_wilson"][1]


def test_hc_false_accept_for_a_decision_arm_follows_the_numeric_confidence(tmp_path):
    rows = [_d(IDS["Ex1"], "d", "Ex1", 0.9), _d(IDS["Xa"], "d", "Xa Zed", 0.6), _d(NEG["Ng1"], "d", "Ng1x", 0.2)]
    arm = _report(tmp_path, rows, baseline="d", tau_step=0.1)["arms"]["d"]
    curve = {round(p["tau"], 2): p for p in arm["curve"]}
    assert (curve[0.0]["accepted"], curve[0.0]["wrong"]) == (3, 2)
    assert (curve[0.5]["accepted"], curve[0.5]["wrong"]) == (2, 1)
    assert (curve[0.7]["accepted"], curve[0.7]["wrong"]) == (1, 0) and curve[0.7]["false_accept_rate"] == 0.0
    assert curve[0.7]["true_accept_rate"] == pytest.approx(1 / 2)  # of the 2 gold positives it ran, 1 right and accepted


def test_the_tau_sweep_is_monotone_and_covers_zero_to_one(tmp_path):
    rows = [_d(IDS["Ex1"], "d", "Ex1", 0.95), _d(IDS["Xa"], "d", "Xa Zed", 0.55), _d(IDS["Xb"], "d", "Xb Prime", 0.35)]
    curve = _report(tmp_path, rows, baseline="d", tau_step=0.05)["arms"]["d"]["curve"]
    taus = [p["tau"] for p in curve]
    assert taus[0] == 0.0 and taus[-1] == 1.0 and len(curve) == 21
    accepted = [p["accepted"] for p in curve]
    assert accepted == sorted(accepted, reverse=True)
    assert [p["true_accept_rate"] for p in curve] == sorted((p["true_accept_rate"] for p in curve), reverse=True)


def test_text_arms_have_no_tau_curve(tmp_path):
    assert _report(tmp_path, _perfect("m"), baseline="m")["arms"]["m"]["curve"] is None


def test_matched_operating_point_is_the_smallest_tau_not_above_the_baselines_wrong_write_rate(tmp_path, small_floors):
    base = [_t(IDS["Xa"], "qwen-local", "Xa Zed"), _t(IDS["Xc"], "qwen-local", "Xc Prime"), _t(NEG["Ng1"], "qwen-local", "")]
    # on the 3 shared non-trivial items the baseline writes 2, 1 wrong: wrong-write 1/2; gold Xa, Xc -> good-write 1/2
    dec = [
        _d(IDS["Xa"], "d", "Xa Zed", 0.4),
        _d(IDS["Xb"], "d", "Xb Prime", 0.8),  # not shared
        _d(IDS["Xc"], "d", "Xc Prime", 0.7),
        _d(NEG["Ng1"], "d", "", 0.9),
    ]
    m = _report(tmp_path, base + dec, tau_step=0.1)["arms"]["d"]["matched"]
    assert (
        m["n_common"] == 3
        and m["baseline_wrong_write_rate"] == pytest.approx(0.5)
        and m["baseline_good_write_rate"] == pytest.approx(0.5)
    )
    assert m["tau"] == pytest.approx(0.0)  # wrong-write 1/2 already at tau 0, which is not above the baseline's


def test_a_tau_above_zero_is_chosen_when_low_confidence_picks_are_the_wrong_ones(tmp_path, small_floors):
    base = [
        _t(IDS["Xa"], "qwen-local", "Xa Prime"),
        _t(IDS["Xc"], "qwen-local", "Xc Prime"),
        _t(NEG["Ng1"], "qwen-local", ""),
    ]  # FA 0
    dec = [_d(IDS["Xa"], "d", "Xa Zed", 0.4), _d(IDS["Xc"], "d", "Xc Prime", 0.7), _d(NEG["Ng1"], "d", "", 0.9)]
    m = _report(tmp_path, base + dec, tau_step=0.1)["arms"]["d"]["matched"]
    assert (
        m["tau"] == pytest.approx(0.5) and m["arm_wrong_write_rate"] == 0.0 and m["arm_good_write_rate"] == pytest.approx(1 / 2)
    )


def test_no_matched_point_when_no_tau_reaches_the_baselines_false_accept(tmp_path, small_floors):
    base = [_t(IDS["Xa"], "qwen-local", "Xa Prime")]  # baseline FA 0.0
    dec = [_d(IDS["Xa"], "d", "Xa Zed", 1.0)]  # wrong at every tau up to 1.0
    m = _report(tmp_path, base + dec, tau_step=0.5)["arms"]["d"]["matched"]
    assert m["tau"] is None and m["n_common"] == 1


def test_no_shared_non_trivial_items_means_no_matched_point(tmp_path, small_floors):
    rows = [_t(IDS["Ex1"], "qwen-local", "Ex1"), _d(IDS["Xa"], "d", "Xa Zed", 1.0)]
    m = _report(tmp_path, rows, tau_step=0.5)["arms"]["d"]["matched"]
    assert m["tau"] is None and m["n_common"] == 0


def test_the_always_candidate_1_floor_arm_is_computed_from_the_items_alone(tmp_path):
    rep = _report(tmp_path, [_t(IDS["Ex1"], "m", "Ex1")], baseline="m")
    f = rep["arms"]["always-candidate-1"]
    assert f["classes"]["exact"]["correct"] == 2  # candidate 1 is the exact title for both exact items
    assert f["classes"]["negative"]["correct"] == 0  # a candidate is never the right answer to a negative
    assert f["classes"]["expansion_independent"]["correct"] == 2  # Xa Prime and Xc Prime are candidate 1
    assert f["classes"]["expansion_incumbent"]["correct"] == 1
    assert f["hc"]["accepted"] == 7 and f["hc"]["wrong"] == 2  # both negatives are false accepts


# ---- order sensitivity, failures, latency, tokens, agreement ---------------------------------------


def test_order_sensitivity_counts_only_multi_candidate_items_with_both_orders(tmp_path):
    rows = [
        _t(IDS["Ex2"], "m", "Ex2"), _t(IDS["Ex2"], "m", "Ex2", order="rev"),  # stable
        _t(IDS["Xa"], "m", "Xa Prime"), _t(IDS["Xa"], "m", "Xa Zed", order="rev"),  # changed
        _t(IDS["Xb"], "m", "Xb Prime"),  # no rev row: not counted
        _t(IDS["Ex1"], "m", "Ex1"), _t(IDS["Ex1"], "m", "Ex1", order="rev"),  # single candidate: not counted
    ]  # fmt: skip
    o = _report(tmp_path, rows, baseline="m")["arms"]["m"]["order"]
    assert o["n"] == 2 and o["changed"] == 1 and o["rate"] == 0.5


def test_failures_are_classified_and_latency_and_tokens_summarised(tmp_path):
    rows = [
        _t(IDS["Ex1"], "m", "Ex1", lat=1.0, usage={"prompt_tokens": 10, "completion_tokens": 2}),
        _t(IDS["Ex2"], "m", "Ex2", lat=3.0, usage={"prompt_tokens": 20, "completion_tokens": 4, "cached_tokens": 8}),
        _e(IDS["Xa"], "m", "HTTP 429"), _e(IDS["Xb"], "m", "rate-limited (HTTP 429)"), _e(IDS["Xc"], "m", "TimeoutError"),
        _e(NEG["Ng1"], "m", "bad response: no answers object"), _e(NEG["Ng2"], "m", "EMPTY no content"),
    ]  # fmt: skip
    a = _report(tmp_path, rows, baseline="m")["arms"]["m"]
    assert a["failures"]["by_kind"] == {"rate-limit": 2, "timeout": 1, "bad-response": 1, "empty": 1}
    assert a["failures"]["total"] == 5 and a["failures"]["rate"] == pytest.approx(5 / 7)
    assert a["latency"]["median"] == pytest.approx(2.0) and a["latency"]["n"] == 2
    assert a["tokens"] == {"prompt_tokens": 30, "completion_tokens": 6, "cached_tokens": 8}


def test_pairwise_agreement_uses_forward_picks_on_shared_items(tmp_path):
    rows = (
        [_t(IDS["Ex1"], "a", "Ex1"), _t(IDS["Ex2"], "a", "Ex2"), _t(IDS["Xa"], "a", "Xa Prime")]
        + [_t(IDS["Ex1"], "b", "Ex1"), _t(IDS["Ex2"], "b", "Ex2 Jr"), _t(IDS["Xa"], "b", "Xa Zed")]
    )  # fmt: skip
    ag = _report(tmp_path, rows, baseline="a")["agreement"]
    assert ag["a"]["b"] == {"agree": 1, "n": 3}
    assert ag["b"]["a"] == ag["a"]["b"] and ag["a"]["a"]["n"] == 3


# ---- the rule verdict ----------------------------------------------------------------------------


def _both(tmp_path, arm_rows, base_rows):
    return _report(tmp_path, base_rows + arm_rows, tau_step=0.25)


def test_an_arm_that_loses_to_the_baseline_on_false_accepts_fails(tmp_path, small_floors):
    base = _perfect("qwen-local")
    arm = [_t(IDS["Ex1"], "t", "Ex1"), _t(IDS["Xa"], "t", "Xa Zed"), _t(NEG["Ng1"], "t", "Ng1x")] + _perfect("t")[3:]
    v = _both(tmp_path, arm, base)["verdicts"]["t"]
    assert v["verdict"] == "FAIL" and v["rules"]["a"]["ok"] is False


def test_order_sensitivity_above_5_percent_fails_rule_c(tmp_path, small_floors):
    base = _perfect("qwen-local")
    arm = _perfect("t") + [_t(IDS["Xa"], "t", "Xa Zed", order="rev"), _t(IDS["Ex2"], "t", "Ex2", order="rev")]
    v = _both(tmp_path, arm, base)["verdicts"]["t"]
    assert v["rules"]["c"]["ok"] is False and v["rules"]["c"]["n"] == 2 and v["verdict"] == "FAIL"


def test_a_failure_rate_above_2_percent_fails_rule_e(tmp_path, small_floors):
    base = _perfect("qwen-local")
    arm = _perfect("t")[:-1] + [_e(NEG["Ng2"], "t")]
    v = _both(tmp_path, arm, base)["verdicts"]["t"]
    assert v["rules"]["e"]["ok"] is False and v["verdict"] == "FAIL"


def test_missing_data_is_incomplete_not_pass(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + _big_rows("t", _right)  # no reversed rows for t: order sensitivity unmeasured
    v = _big_report(tmp_path, rows)["verdicts"]["t"]
    assert v["rules"]["c"]["ok"] is None and v["verdict"] == "INCOMPLETE"


def test_within_noise_is_stated_when_the_intervals_overlap(tmp_path):
    md = gs.render_markdown(_big_report(tmp_path, _with_rev("qwen-local", _mediocre) + _with_rev("t", _mediocre)))
    assert "within noise" in md and "n=" in md and "not demonstrated" in md


# ---- report and CLI ----------------------------------------------------------------------------------


def test_the_markdown_report_has_every_section_and_names_no_winner(tmp_path):
    rows = _perfect("qwen-local") + _perfect("d", text=False, conf=0.9)
    md = gs.render_markdown(_report(tmp_path, rows))
    headings = [
        "## Items",
        "## Accuracy by class",
        "## High-confidence false accepts",
        "## Operating curve",
        "## Matched operating point",
        "## Order sensitivity",
        "## Failures",
        "## Agreement",
        "## Rule verdicts",
    ]
    for heading in headings:
        assert heading in md, heading
    assert "always-candidate-1" in md and "winner" not in md.lower().replace("no winner", "")


def test_the_cli_writes_markdown_and_json(tmp_path, capsys):
    items, res = _write_items(tmp_path), _write_rows(tmp_path, _perfect("qwen-local") + _perfect("t"))
    out, js = tmp_path / "r.md", tmp_path / "r.json"
    code = gb.main(
        ["score", "--items", str(items), "--results", str(res), "--out", str(out), "--json", str(js), "--tau-step", "0.25"]
    )
    assert code == 0 and "## Rule verdicts" in out.read_text(encoding="utf-8") and "## Rule verdicts" in capsys.readouterr().out
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["baseline"] == "qwen-local" and "t" in data["arms"] and "verdicts" in data


def test_a_missing_baseline_is_reported_not_crashed(tmp_path):
    rep = _big_report(tmp_path, _with_rev("t", _right))
    assert rep["baseline_present"] is False and rep["verdicts"]["t"]["verdict"] == "INCOMPLETE"
    assert rep["verdicts"]["t"]["rules"]["a"]["ok"] is None and rep["verdicts"]["t"]["rules"]["d"]["ok"] is True


def test_score_bad_arguments_exit_2(tmp_path):
    items = _write_items(tmp_path)
    for argv in (["score", "--items", str(items)], ["score", "--items", str(tmp_path / "no"), "--results", str(items)],
                 ["score", "--items", str(items), "--results", str(items), "--tau-step", "0"]):  # fmt: skip
        with pytest.raises(SystemExit) as e:
            gb.main(argv)
        assert e.value.code == 2, argv


def test_acquire_rows_are_ignored_by_score_and_stated_to_be_judged_only(tmp_path):
    acquire_rows = [
        {
            "id": "acquire:S:A|B",
            "arm": "m",
            "order": "fwd",
            "raw": {},
            "latency_s": 0.1,
            "usage": None,
            "error": None,
            "parsed": {"same_entity": True, "noul": 0.9, "confidence": 0.9},
        },  # fmt: skip
    ]
    rep = _report(tmp_path, _perfect("m") + acquire_rows, baseline="m")
    assert rep["arms"]["m"]["failures"]["n_rows"] == 7 and rep["arms"]["m"]["n_items"] == 7  # nothing from the acquire row
    assert "acquire pairs are judged-only" in gs.render_markdown(rep)


# ---- verdict floors, failed baselines, non-trivial headline, rule (d), the four verdict values ------------------------
#
# A synthetic show big enough to clear the sample-size floor: 40 exact controls, 20 + 20 expansion golds (gold is the SECOND
# candidate for three quarters of them, so "always candidate 1" mostly misses) and 60 negatives.
# Labelled = 140, non-trivial = 100.


def _big_items():
    items = []
    for k in range(40):
        items.append(_item(f"E{k}", [f"E{k}", f"E{k} Jr"], f"E{k}", "exact"))
    for cls_name, incumbent in (("I", False), ("N", True)):
        for k in range(20):
            other = f"{cls_name}{k} " + ("Abe" if k % 2 else "Zed")  # "Abe" sorts before "Prime": a string rule misses those
            titles = [f"{cls_name}{k} Prime", other] if k < 5 else [other, f"{cls_name}{k} Prime"]
            items.append(_item(f"{cls_name}{k}", titles, f"{cls_name}{k} Prime", "expansion", incumbent=incumbent))
    for k in range(60):
        items.append(_item(f"G{k}", [f"G{k}x", f"G{k}y"], negative=True))
    return items


BIG = _big_items()


def _big_rows(arm, picker, order="fwd", conf="high"):
    rows = []
    for it in BIG:
        title = picker(it)
        rows.append(_t(it["id"], arm, title, conf if title else "none", order))
    return rows


def _right(it):
    return "" if it.get("negative") else it["gold"]


def _none(it):
    return ""


def _exact_only(it):  # accept the title that equals the term, else say none
    return it["gold"] if it.get("gold_kind") == "exact" else ""


def _mediocre(it):  # right on the controls and half the expansions; wrong (a title, high) on 40% of the negatives
    if it["id"].startswith("verify-neg:"):
        return it["candidates"][0]["title"] if int(it["term"][1:]) % 5 < 2 else ""
    if it.get("gold_kind") == "exact" or int(it["term"][1:]) < 10:
        return it["gold"]
    return [c["title"] for c in it["candidates"] if c["title"] != it["gold"]][0]


def _big_report(tmp_path, rows, baseline="qwen-local"):
    return _report(tmp_path, rows, baseline=baseline, items=BIG)


def _with_rev(arm, picker):
    return _big_rows(arm, picker) + [r for r in _big_rows(arm, picker, order="rev") if len(BIG[0]["candidates"]) >= 2]


def test_a_clearly_better_arm_on_a_big_enough_sample_passes_every_rule(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + _with_rev("t", _right)
    v = _big_report(tmp_path, rows)["verdicts"]["t"]
    assert v["verdict"] == "PASS", v["rules"]
    assert all(v["rules"][k]["ok"] is True and not v["rules"][k].get("within_noise") for k in "abcde")


def test_an_arm_that_ran_only_two_items_cannot_pass(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + [_t(BIG[0]["id"], "t", "E0"), _t("verify-neg:S:G0", "t", "", "none")]
    v = _big_report(tmp_path, rows)["verdicts"]["t"]
    assert v["verdict"] == "INCOMPLETE"
    for k in "abd":
        assert v["rules"][k]["ok"] is None and "floor" in v["rules"][k]["note"]


def test_an_arm_that_ran_less_than_90_percent_of_the_baselines_labelled_items_is_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "MIN_COMMON_N", 10)
    rows = _with_rev("qwen-local", _mediocre) + _big_rows("t", _right)[:110]  # 110 of 140: ~79% of the baseline's labelled items
    v = _big_report(tmp_path, rows)["verdicts"]["t"]
    assert v["rules"]["a"]["ok"] is None and "90%" in v["rules"]["a"]["note"]


def test_a_result_within_noise_reads_not_demonstrated_and_cannot_pass(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + _with_rev("t", _mediocre)  # the same behaviour, so every comparison overlaps
    v = _big_report(tmp_path, rows)["verdicts"]["t"]
    assert v["verdict"] == "NOT DEMONSTRATED"
    assert any(r.get("within_noise") and r["ok"] for r in v["rules"].values())


def test_the_four_verdict_values_are_documented_in_the_report_header(tmp_path):
    md = gs.render_markdown(_big_report(tmp_path, _with_rev("qwen-local", _mediocre) + _with_rev("t", _right)))
    for word in ("PASS", "FAIL", "NOT DEMONSTRATED", "INCOMPLETE"):
        assert word in md.split("## Rule verdicts")[1].split("| arm |")[0], word


def test_a_failed_baseline_cannot_let_an_always_none_arm_pass(tmp_path):
    errored = [_e(it["id"], "qwen-local") for it in BIG]
    v = _big_report(tmp_path, errored + _with_rev("t", _none))["verdicts"]["t"]
    assert v["verdict"] != "PASS"
    assert v["rules"]["a"]["ok"] is None and v["rules"]["b"]["ok"] is None
    assert "failure rate" in v["rules"]["a"]["note"]


def test_a_baseline_that_accepted_nothing_leaves_a_and_b_incomplete(tmp_path):
    rows = _with_rev("qwen-local", _none) + _with_rev("t", _right)
    v = _big_report(tmp_path, rows)["verdicts"]["t"]
    assert v["rules"]["a"]["ok"] is None and v["rules"]["b"]["ok"] is None and "no writes" in v["rules"]["a"]["note"]
    assert v["verdict"] == "INCOMPLETE"


def test_no_undefined_rate_is_turned_into_zero_inside_a_rule():
    import inspect

    assert "or 0.0" not in inspect.getsource(gs._verdict)


def test_the_baseline_must_have_run_the_negatives(tmp_path):
    no_negs = [r for r in _with_rev("qwen-local", _mediocre) if not r["id"].startswith("verify-neg:")]
    v = _big_report(tmp_path, no_negs + _with_rev("t", _right))["verdicts"]["t"]
    assert v["rules"]["a"]["ok"] is None and "negatives" in v["rules"]["a"]["note"] and v["verdict"] == "INCOMPLETE"


def test_rules_a_and_b_are_decided_on_the_non_trivial_items_with_the_all_class_figure_as_secondary(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + _with_rev("t", _right)
    a = _big_report(tmp_path, rows)["verdicts"]["t"]["rules"]["a"]
    assert a["common_n"] == 100 and a["baseline_n"] == 64  # the 100 non-trivial items, not the 140 labelled ones
    assert a["baseline"] == pytest.approx(44 / 64) and "all_class" in a
    assert a["all_class"]["baseline"] == pytest.approx(44 / 104)  # the 40 exact controls dilute the all-class figure


def test_the_exact_controls_cannot_carry_rules_a_and_b(tmp_path):
    """A baseline that is perfect on controls but bad on the hard items, against an arm bad on the same hard items."""
    rows = _with_rev("qwen-local", _mediocre) + _with_rev("t", _mediocre)
    v = _big_report(tmp_path, rows)["verdicts"]["t"]
    assert v["rules"]["a"]["all_class"]["n"] == 140 and v["rules"]["a"]["common_n"] == 100


@pytest.mark.parametrize("picker", [_none, _exact_only], ids=["always-none", "exact-only"])
def test_abstaining_or_exact_only_heuristics_fail_rule_d(tmp_path, picker):
    rows = _with_rev("qwen-local", _mediocre) + _with_rev("t", picker)
    v = _big_report(tmp_path, rows)["verdicts"]["t"]
    assert v["rules"]["d"]["ok"] is False and v["verdict"] == "FAIL"
    assert v["rules"]["d"]["balanced"]["arm"] < v["rules"]["d"]["balanced"]["floor"] or v["rules"]["d"]["balanced"]["arm"] <= 0.5


def test_rule_d_reports_the_two_expansion_classes_separately_and_balanced_accuracy(tmp_path):
    d = _big_report(tmp_path, _with_rev("qwen-local", _mediocre) + _with_rev("t", _right))["verdicts"]["t"]["rules"]["d"]
    assert set(d["classes"]) == {"expansion_independent", "expansion_incumbent"}
    assert d["classes"]["expansion_independent"]["n"] == 20 and d["classes"]["expansion_incumbent"]["n"] == 20
    # the stronger floor here is the string rule (right on the even-numbered items), not candidate 1 (right on 5 of 20)
    assert d["floor_arm"] == "expansion-heuristic"
    assert d["classes"]["expansion_independent"]["arm"] == 1.0 and d["classes"]["expansion_independent"][
        "floor"
    ] == pytest.approx(0.5)
    assert d["balanced"]["arm"] == 1.0 and d["balanced"]["floor"] == pytest.approx((0.5 + 1.0) / 2)


def test_the_report_shows_the_secondary_all_class_column_and_the_expansion_split(tmp_path):
    md = gs.render_markdown(_big_report(tmp_path, _with_rev("qwen-local", _mediocre) + _with_rev("t", _right)))
    verdicts = md.split("## Rule verdicts")[1]
    assert "all classes" in verdicts and "independent" in verdicts and "incumbent" in verdicts and "balanced" in verdicts


# ---- v2 (post-hoc framing) arms: every pick is a title, abstention is by confidence ------------------------------------------


def _v2(item_id, arm, title, conf, order="fwd"):
    row = _d(item_id, arm, title, conf, order)
    row["framing"] = "v2"
    return row


def test_a_v2_arm_with_no_none_answers_is_scored_through_the_tau_sweep(tmp_path):
    rows = [
        _v2(IDS["Xa"], "d@v2", "Xa Prime", 0.9),  # right
        _v2(IDS["Xb"], "d@v2", "Xb Alt", 0.4),  # wrong, low confidence
        _v2(NEG["Ng1"], "d@v2", "Ng1x", 0.8),  # a negative can only be answered with a title: a false accept if accepted
        _v2(NEG["Ng2"], "d@v2", "Ng2x", 0.3),
    ]
    arm = _report(tmp_path, rows, baseline="d@v2", tau_step=0.25)["arms"]["d@v2"]
    curve = {round(p["tau"], 2): p for p in arm["curve"]}
    assert (curve[0.0]["accepted"], curve[0.0]["wrong"]) == (4, 3)
    assert (curve[0.5]["accepted"], curve[0.5]["wrong"]) == (2, 1)  # Xa right, Ng1x a false accept
    assert (curve[1.0]["accepted"], curve[1.0]["wrong"]) == (0, 0)
    assert arm["kind"] == "decision" and arm["framing"] == "v2"


def test_negatives_are_never_scored_by_tau_free_accuracy_for_a_v2_arm(tmp_path):
    rows = [_v2(NEG["Ng1"], "d@v2", "Ng1x", 0.9)]
    arm = _report(tmp_path, rows, baseline="d@v2")["arms"]["d@v2"]
    assert arm["classes"]["negative"]["accuracy"] is None and arm["classes"]["negative"]["note"].startswith(
        "abstention is by confidence"
    )


def test_v2_arms_are_labelled_post_hoc_framing_in_the_report(tmp_path):
    rows = _perfect("qwen-local") + [_v2(IDS["Xa"], "d@v2", "Xa Prime", 0.9)]
    md = gs.render_markdown(_report(tmp_path, rows, tau_step=0.25))
    assert "d@v2 (post-hoc framing)" in md and "post-hoc" in md.split("## Items")[1].split("##")[0]


def test_a_v1_arm_is_not_labelled_post_hoc(tmp_path):
    """GUARD: passes on the old code."""
    md = gs.render_markdown(_report(tmp_path, _perfect("qwen-local"), baseline="qwen-local"))
    assert "post-hoc" not in md


# =====================================================================================
# Phase 5: arms are scored by their consequences for the glossary (apply_results), plus the reviewer's scorer fixes
# =====================================================================================


def _big_items_n(n_exact, n_exp, n_neg, mixed=False):
    """``mixed``: odd-numbered expansions have a distractor that sorts before the gold, so a string rule misses them."""
    items = [_item(f"E{k}", [f"E{k}", f"E{k} Jr"], f"E{k}", "exact") for k in range(n_exact)]
    for cls_name, incumbent in (("I", False), ("N", True)):
        for k in range(n_exp):
            other = f"{cls_name}{k} " + ("Abe" if mixed and k % 2 else "Zed")
            titles = [f"{cls_name}{k} Prime", other] if k < 5 else [other, f"{cls_name}{k} Prime"]
            items.append(_item(f"{cls_name}{k}", titles, f"{cls_name}{k} Prime", "expansion", incumbent=incumbent))
    items += [_item(f"G{k}", [f"G{k}x", f"G{k}y"], negative=True) for k in range(n_neg)]
    return items


def _rows_for(items, arm, picker, order="fwd", conf="high"):
    out = []
    for it in items:
        title = picker(it)
        out.append(_t(it["id"], arm, title, conf if title else "none", order))
    return out


def _report_for(tmp_path, items, rows, baseline="qwen-local", tau_step=0.25, policy="legacy"):
    return gs.build_report(
        gs.load_items(str(_write_items(tmp_path, items))),
        gs.load_results([str(_write_rows(tmp_path, rows))]),
        baseline,
        tau_step,
        policy=policy,
    )


def _both_orders(items, arm, picker):
    return _rows_for(items, arm, picker) + _rows_for(items, arm, picker, order="rev")


# ---- the metric: wrong writes and good writes, with the old false-accept rate as the secondary column ------------------------


def test_rule_a_is_the_wrong_write_rate_and_the_old_false_accept_rate_is_secondary(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + _with_rev("t", _right)
    a = _big_report(tmp_path, rows)["verdicts"]["t"]["rules"]["a"]
    assert a["metric"] == "wrong-write rate" and a["baseline"] == pytest.approx(44 / 64) and a["arm"] == 0.0
    assert a["all_class"]["baseline"] == pytest.approx(44 / 104)  # the legacy all-class false-accept rate, kept as a column


def test_rule_b_is_the_good_write_rate_over_the_expansion_gold_items(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + _with_rev("t", _right)
    b = _big_report(tmp_path, rows)["verdicts"]["t"]["rules"]["b"]
    assert b["metric"] == "good-write rate" and b["baseline"] == pytest.approx(20 / 40) and b["arm"] == 1.0 and b["n"] == 40


def test_an_arm_that_always_says_none_makes_no_wrong_writes_but_cannot_pass_rule_b(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + _with_rev("t", _none)
    v = _big_report(tmp_path, rows)["verdicts"]["t"]
    assert v["rules"]["b"]["ok"] is False and v["rules"]["b"]["arm"] == 0.0 and v["verdict"] == "FAIL"
    assert v["rules"]["a"]["ok"] is None  # no writes at all: its wrong-write rate is undefined, never zero


def test_an_arm_right_only_on_the_exact_controls_cannot_pass(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + _with_rev("t", _exact_only)
    v = _big_report(tmp_path, rows)["verdicts"]["t"]
    assert v["verdict"] == "FAIL" and v["rules"]["b"]["ok"] is False


def test_an_arm_whose_false_accepts_are_all_on_exact_controls_does_not_decide_rule_a(tmp_path):
    """Exact items are controls: wrong high-confidence picks there show only in the all-class secondary column."""

    def picker(it):
        if it.get("gold_kind") == "exact":
            return "Q" + it["term"][1:]  # a respelling of a correct term, at high confidence
        return _right(it)

    rows = _with_rev("qwen-local", _mediocre) + _with_rev("t", picker)
    a = _big_report(tmp_path, rows)["verdicts"]["t"]["rules"]["a"]
    assert a["ok"] is True and a["arm"] == 0.0  # decided on the 100 non-trivial items, where the arm is perfect
    assert a["all_class"]["arm"] == pytest.approx(40 / 80)  # 40 harmless-to-the-rule but wrong accepts among 80 accepted overall


# ---- floors: non-trivial coverage, each expansion class, negatives, the absolute labelled floor ----------------------------


def test_an_arm_on_all_exact_controls_but_few_non_trivial_items_is_incomplete(tmp_path):
    rows = (
        _with_rev("qwen-local", _mediocre) + [r for r in _with_rev("t", _right) if not r["id"].startswith("verify-neg:G")][:100]
    )
    rows = _with_rev("qwen-local", _mediocre) + [
        r for r in _with_rev("t", _right) if r["id"].startswith("verify:S:E") or "I1" in r["id"] or "N1" in r["id"]
    ]
    v = _big_report(tmp_path, rows)["verdicts"]["t"]
    assert v["verdict"] == "INCOMPLETE" and v["rules"]["a"]["ok"] is None and "90%" in v["rules"]["a"]["note"]


def test_each_expansion_class_must_be_90_percent_covered(tmp_path):
    only_some_incumbent = lambda r: not (r["id"].startswith("verify:S:N") and int(r["id"].rsplit("N", 1)[1]) >= 12)  # noqa: E731
    rows = _with_rev("qwen-local", _mediocre) + [r for r in _with_rev("t", _right) if only_some_incumbent(r)]
    v = _big_report(tmp_path, rows)["verdicts"]["t"]
    assert v["rules"]["a"]["ok"] is None and "expansion_incumbent" in v["rules"]["a"]["note"]


def test_the_baseline_must_have_run_90_percent_of_the_negatives_not_just_one(tmp_path):
    base = [r for r in _with_rev("qwen-local", _mediocre) if not r["id"].startswith("verify-neg:") or r["id"].endswith("G0")]
    v = _big_report(tmp_path, base + _with_rev("t", _right))["verdicts"]["t"]
    assert v["rules"]["a"]["ok"] is None and "1 of 60 negatives" in v["rules"]["a"]["note"]


def test_the_absolute_labelled_floor_still_bites_when_the_90_percent_share_is_met(tmp_path, monkeypatch):
    items = _big_items_n(20, 15, 50)  # 100 labelled, 80 non-trivial
    base = _both_orders(items, "qwen-local", _mediocre)
    arm = [
        r for r in _both_orders(items, "t", _right) if not r["id"].startswith("verify:S:E") or int(r["id"].rsplit("E", 1)[1]) >= 5
    ]
    v = _report_for(tmp_path, items, base + arm)["verdicts"]["t"]  # 95 common labelled items: over 90%, under 100
    assert v["rules"]["a"]["ok"] is None and "floor" in v["rules"]["a"]["note"]
    monkeypatch.setattr(gs, "MIN_COMMON_N", 95)
    v = _report_for(tmp_path / "x", items, base + arm)["verdicts"]["t"] if (tmp_path / "x").mkdir() is None else None
    assert v["rules"]["a"]["ok"] is not None


# ---- rule (d): pooled expansion classes, >= is "no worse", > beyond noise is "demonstrated" -----------------------------------


def test_a_perfect_arm_passes_d_even_when_the_floor_is_already_perfect_on_a_class(tmp_path):
    items = _big_items_n(20, 20, 60)
    for it in items:  # make always-candidate-1 perfect on every expansion item
        if it.get("gold_kind") == "expansion":
            it["candidates"] = sorted(it["candidates"], key=lambda c: c["title"] != it["gold"])
    rows = _both_orders(items, "qwen-local", _mediocre) + _both_orders(items, "t", _right)
    d = _report_for(tmp_path, items, rows)["verdicts"]["t"]["rules"]["d"]
    assert d["ok"] is True and d["within_noise"] is True and "already perfect" in d["note"]


def test_an_arm_equal_to_the_floor_is_no_worse_but_not_demonstrated(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + _with_rev("t", lambda it: gs.heuristic_pick(it).title)
    d = _big_report(tmp_path, rows)["verdicts"]["t"]["rules"]["d"]
    assert d["ok"] is True and d["within_noise"] is True  # `>=`: not a FAIL; the intervals overlap: not demonstrated


def test_an_arm_below_the_floor_on_the_pooled_expansions_fails_d(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + _with_rev("t", _none)
    d = _big_report(tmp_path, rows)["verdicts"]["t"]["rules"]["d"]
    assert d["ok"] is False and set(d["classes"]) == {
        "expansion_independent",
        "expansion_incumbent",
    }  # the split is reporting only


# ---- rules (c) and (e): sample floors, and a FAIL within noise ----------------------------------------------------------------


def test_rule_c_is_incomplete_below_100_reversed_pairs(tmp_path):
    items = _big_items_n(20, 15, 50)
    base = _both_orders(items, "qwen-local", _mediocre)
    arm = _rows_for(items, "t", _right) + _rows_for(items, "t", _right, order="rev")[:60]
    c = _report_for(tmp_path, items, base + arm)["verdicts"]["t"]["rules"]["c"]
    assert c["ok"] is None and c["below_floor"] is True and "100" in c["note"]


def test_a_rule_c_fail_within_noise_reads_fail_within_noise(tmp_path):
    items = _big_items_n(20, 15, 50)
    base = _both_orders(items, "qwen-local", _mediocre)

    def flip(it):  # 6 of the 100 reversed answers change: over 5%, but the interval reaches under it
        if it.get("negative") or int(it["term"][1:]) % 14:
            return _right(it)
        return it["candidates"][0]["title"] if it["candidates"][0]["title"] != it["gold"] else it["candidates"][1]["title"]

    arm = _rows_for(items, "t", _right) + _rows_for(items, "t", flip, order="rev")
    rep = _report_for(tmp_path, items, base + arm)
    c = rep["verdicts"]["t"]["rules"]["c"]
    assert c["ok"] is False and c["within_noise"] is True  # the point estimate is over 5%, the interval reaches under it
    assert "FAIL (within noise)" in gs.render_markdown(rep)


def test_a_floor_incomplete_outranks_a_fail_in_the_overall_verdict(tmp_path):
    items = _big_items_n(20, 15, 50)
    base = _both_orders(items, "qwen-local", _mediocre)
    arm = _rows_for(items, "t", _right) + _rows_for(items, "t", _right, order="rev")[:40]  # (c) below its floor
    arm += [_e(it["id"], "t") for it in items[:5]]  # and (e) would otherwise fail
    v = _report_for(tmp_path, items, base + arm)["verdicts"]["t"]
    assert v["rules"]["c"]["below_floor"] and v["verdict"] == "INCOMPLETE"


def test_rule_e_is_incomplete_below_the_labelled_floor(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + [_e(BIG[0]["id"], "t"), _t(BIG[1]["id"], "t", "E1")]
    e = _big_report(tmp_path, rows)["verdicts"]["t"]["rules"]["e"]
    assert e["ok"] is None and e["below_floor"] is True


# ---- Span-01 Lite and any per-candidate noul arm: argmax, tau decides ---------------------------------------------------------


def _span_row(item_id, scores, arm="span", order="fwd"):
    return {
        "id": item_id,
        "arm": arm,
        "order": order,
        "raw": [],
        "latency_s": 0.1,
        "usage": None,
        "error": None,
        "parsed": {"scores": scores},
    }


def test_a_scores_row_picks_the_argmax_title_with_its_score_and_never_none():
    pick = gs.row_pick(_span_row("i", {"Zoro": 0.06, "Roronoa Zoro": 0.09}))
    assert pick.title == "Roronoa Zoro" and pick.conf == 0.09
    assert not hasattr(gs, "SPAN_PICK_MIN")


def test_the_tau_sweep_decides_a_span_arms_abstention(tmp_path):
    rows = [_span_row(IDS["Xa"], {"Xa Prime": 0.09, "Xa Zed": 0.02}), _span_row(IDS["Xb"], {"Xb Alt": 0.04, "Xb Prime": 0.03})]
    curve = _report(tmp_path, rows, baseline="span", tau_step=0.05)["arms"]["span"]["curve"]
    by = {round(p["tau"], 2): p for p in curve}
    assert by[0.0]["accepted"] == 2 and by[0.05]["accepted"] == 1 and by[0.1]["accepted"] == 0


def test_score_distributions_are_reported_and_a_per_candidate_noul_is_not_called_a_choice_probability(tmp_path):
    rows = [
        _span_row(IDS["Xa"], {"Xa Prime": 0.09, "Xa Zed": 0.02}),
        _span_row(IDS["Xc"], {"Xc Prime": 0.30}),
        _span_row(IDS["Xb"], {"Xb Alt": 0.06, "Xb Prime": 0.01}),
    ]
    rep = _report(tmp_path, rows, baseline="span", tau_step=0.25)
    cal = rep["arms"]["span"]["calibration"]
    assert cal["scores"]["correct_median"] == pytest.approx(0.09) and cal["scores"]["other_median"] == pytest.approx(0.04)
    assert cal["scores"]["n_correct"] == 3 and cal["scores"]["n_other"] == 2
    assert cal["pick_conf"]["n_correct"] == 2 and cal["pick_conf"]["n_wrong"] == 1
    md = gs.render_markdown(rep)
    assert "not a choice probability" in md and "median" in md.lower()


# ---- matched point: the new metric, optimism stated, a held-out figure --------------------------------------------------------


def test_the_matched_tau_is_the_smallest_tau_whose_wrong_write_rate_is_not_above_the_baselines(tmp_path):
    base = _with_rev("qwen-local", _mediocre)

    # a decision arm: right with high confidence on the first 10 of every expansion class, wrong with low confidence elsewhere
    def dec(it):
        return it["gold"] if it.get("gold_kind") == "exact" or (not it.get("negative") and int(it["term"][1:]) < 10) else None

    rows = []
    for it in BIG:
        if it.get("negative"):
            rows.append(_d(it["id"], "d", it["candidates"][0]["title"], 0.2))  # wrong writes only below tau 0.3
        elif dec(it):
            rows.append(_d(it["id"], "d", it["gold"], 0.9))
        else:
            wrong = [c["title"] for c in it["candidates"] if c["title"] != it["gold"]][0]
            rows.append(_d(it["id"], "d", wrong, 0.2))
    rows += [{**r, "order": "rev"} for r in rows]
    rep = _big_report(tmp_path, base + rows)
    m = rep["arms"]["d"]["matched"]
    assert m["tau"] == pytest.approx(0.25) and m["arm_wrong_write_rate"] == 0.0
    assert m["baseline_wrong_write_rate"] == pytest.approx(44 / 64) and m["arm_good_write_rate"] == pytest.approx(20 / 40)
    assert m["n_common"] == 100


def test_the_report_says_the_matched_point_is_optimistic_and_gives_a_held_out_figure(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + [
        _d(it["id"], "d", _right(it) or it["candidates"][0]["title"], 0.9 if not it.get("negative") else 0.1) for it in BIG
    ]
    rows += [{**r, "order": "rev"} for r in rows if r["arm"] == "d"]
    rep = _big_report(tmp_path, rows)
    ho = rep["arms"]["d"]["matched"]["held_out"]
    assert ho["n_a"] + ho["n_b"] == 100 and ho["tau_a"] is not None and "arm_wrong_write_rate_b" in ho
    md = gs.render_markdown(rep)
    assert "optimistic" in md and "held-out" in md.lower()


# ---- the report: consequences section, non-trivial primary curve, off-list rate, collapsed accept counts ----------------------


def test_the_report_states_the_metric_follows_apply_results_and_prints_a_consequences_section(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + _with_rev("t", _right)
    md = gs.render_markdown(_big_report(tmp_path, rows))
    assert "apply_results" in md and "## Consequences" in md
    section = md.split("## Consequences")[1].split("\n## ")[0]
    for needle in ("good writes", "wrong-write rate", "missed", "review load", "harmful flags", "qwen-local"):
        assert needle in section.lower() or needle in section


def test_decision_arms_show_consequences_at_the_matched_tau_and_at_0_5_and_0_8(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + [_d(it["id"], "d", _right(it) or it["candidates"][0]["title"], 0.9) for it in BIG]
    rep = _big_report(tmp_path, rows)
    pts = rep["arms"]["d"]["consequence_points"]
    assert {"matched", "0.50", "0.80"} <= set(pts) and pts["0.50"]["writes"] > 0
    md = gs.render_markdown(rep)
    assert "tau 0.50" in md and "tau 0.80" in md


def test_the_primary_operating_curve_is_the_non_trivial_one_with_the_all_class_column_secondary(tmp_path):
    rows = _with_rev("qwen-local", _mediocre) + [_d(it["id"], "d", _right(it) or it["candidates"][0]["title"], 0.9) for it in BIG]
    rep = _big_report(tmp_path, rows)
    assert rep["arms"]["d"]["curve_nt"][0]["tau"] == 0.0 and "all_class_false_accept" in rep["arms"]["d"]["curve_nt"][0]
    curve = gs.render_markdown(rep).split("## Operating curve")[1].split("\n## ")[0]
    assert "non-trivial" in curve and "all-class" in curve


def test_each_arms_off_list_answer_rate_is_reported(tmp_path):
    rows = [
        _t(IDS["Xa"], "m", "Something Else Entirely"),
        _t(IDS["Xb"], "m", "Xb Prime"),
        _t(IDS["Xc"], "m", ""),
        _e(IDS["Ex1"], "m"),
    ]
    assert _report(tmp_path, rows, baseline="m")["arms"]["m"]["off_list"] == {"n": 1, "of": 3}


def test_accepted_answer_choices_are_collapsed_to_counts(tmp_path):
    rows = [_t(IDS["Ex2"], "m", "Ex2"), _t(IDS["Ex2"], "m", "Ex2 Jr")]  # the same key twice: the latest wins
    m = _report(tmp_path, rows, baseline="m")["arms"]["m"]
    assert m["accept_counts"] == {"exact": 0, "expansion": 1}
    md = gs.render_markdown(_report(tmp_path, rows, baseline="m"))
    assert "Ex2 Jr" not in md  # no title list in the report


# =====================================================================================
# Phase 5b: the string-rule floor, case-exact classification, scope-labelled consequences, verdict precedence, review load
# =====================================================================================


def test_the_expansion_heuristic_picks_a_whole_word_expansion_then_the_exact_title_then_none():
    h = gs.heuristic_pick
    exp = _item("Zoro", ["Zoro", "Roronoa Zoro"], "Zoro", "exact")
    assert h(exp).title == "Roronoa Zoro" and h(exp).word == "high"  # an expansion beats the equal title
    assert h(_item("Zoro", ["Zoro", "Zorro"], "Zoro", "exact")).title == "Zoro"  # no expansion: the equal title
    none = h(_item("Zoro", ["Zorro", "Zora"], negative=True))
    assert none.title == "" and none.word == "none"


def test_the_expansion_heuristic_needs_a_whole_word_and_ignores_the_candidate_order():
    assert (
        gs.heuristic_pick(_item("Zoro", ["Zoroaster", "Zorro"], negative=True)).title == ""
    )  # is_expansion says yes; not a word
    assert gs.heuristic_pick(_item("Ace", ["Pace", "Ace"], "Ace", "exact")).title == "Ace"
    a = _item("Zoro", ["Roronoa Zoro", "Zoro Jr"], "Roronoa Zoro", "expansion")
    b = _item("Zoro", ["Zoro Jr", "Roronoa Zoro"], "Roronoa Zoro", "expansion")
    assert gs.heuristic_pick(a).title == gs.heuristic_pick(b).title == "Roronoa Zoro"  # sorted by title


def test_both_floor_arms_are_in_every_table_and_never_get_a_verdict(tmp_path):
    rep = _big_report(tmp_path, _with_rev("qwen-local", _mediocre) + _with_rev("t", _right))
    assert {"always-candidate-1", "expansion-heuristic"} <= set(rep["arms"])
    assert "expansion-heuristic" not in rep["verdicts"] and "always-candidate-1" not in rep["verdicts"]
    md = gs.render_markdown(rep)
    for section in ("## Accuracy by class", "## Consequences", "## High-confidence false accepts"):
        assert "expansion-heuristic" in md.split(section)[1].split("\n## ")[0], section


def test_the_report_header_says_expansion_gold_is_string_derivable(tmp_path):
    md = gs.render_markdown(_big_report(tmp_path, _with_rev("qwen-local", _mediocre) + _with_rev("t", _right)))
    head = md.split("## Items")[0]
    assert "string-derivable" in head and "no worse than a string rule" in head and "negatives" in head


def test_a_model_that_only_equals_a_perfect_string_rule_is_not_demonstrated_not_pass(tmp_path):
    items = _big_items_n(20, 15, 50)  # the heuristic is perfect on every expansion here
    pick = lambda it: gs.heuristic_pick(it).title  # noqa: E731
    rows = _both_orders(items, "qwen-local", _mediocre) + _both_orders(items, "t", pick)
    rep = _report_for(tmp_path, items, rows)
    d = rep["verdicts"]["t"]["rules"]["d"]
    assert rep["arms"]["expansion-heuristic"]["classes"]["expansion_independent"]["accuracy"] == 1.0
    assert d["floor_arm"] == "expansion-heuristic" and d["ok"] is True and d["within_noise"] is True
    assert rep["verdicts"]["t"]["verdict"] == "NOT DEMONSTRATED"


def test_rule_d_is_measured_against_the_stronger_floor(tmp_path):
    items = _big_items_n(20, 15, 50, mixed=True)  # the heuristic misses the odd ones; candidate 1 misses most of the rest
    rows = _both_orders(items, "qwen-local", _mediocre) + _both_orders(items, "t", _right)
    d = _report_for(tmp_path, items, rows)["verdicts"]["t"]["rules"]["d"]
    heur = _report_for(tmp_path / "h", items, rows) if (tmp_path / "h").mkdir() is None else None
    floors = d["floors"]
    assert set(floors) == {"always-candidate-1", "expansion-heuristic"}
    assert d["floor"] == max(floors.values()) and floors[d["floor_arm"]] == d["floor"]
    assert d["ok"] is True and heur["verdicts"]["t"]["verdict"] == "PASS"


# ---- classification: "nothing" only for the EXACT term -------------------------------------------------------------------


@pytest.mark.parametrize("term,canon", [("Zoro", "zoro"), ("Zoro", "ZORO"), ("Straw Hat", "straw hat"), ("Ace", "ace")])
def test_a_case_only_canonical_is_a_respelling_flag_not_nothing(term, canon):
    import tools.glossary_consequences as gc

    item = _item(term, [term, canon], term, "exact")
    assert gc.classify(item, gs.Pick(canon, word="high")) == "flag_respelling"
    assert gc.classify(item, gs.Pick(term, word="high")) == "nothing"
    t = gc.tally([(item, gs.Pick(canon, word="high"), "exact")])
    assert t["harmful_flags"] == 1 and t["exact"]["correct"] == 0


def test_classify_survives_an_item_without_a_gold():
    import tools.glossary_consequences as gc

    item = {"id": "x", "term": "Zoro", "candidates": [{"title": "Roronoa Zoro"}], "gold": None}
    assert gc.classify(item, gs.Pick("Roronoa Zoro", word="high")) == "wrong_write"


# ---- the consequences table: scope-labelled good writes -----


def test_good_writes_are_split_into_expansion_items_and_exact_controls():
    import tools.glossary_consequences as gc

    exact = _item("Zoro", ["Zoro", "Roronoa Zoro"], "Zoro", "exact", accept=["Zoro", "Roronoa Zoro"])
    exp = _item("Doffy", ["Doffy Prime", "Doffy Abe"], "Doffy Prime", "expansion")
    pairs = [
        (exact, gs.Pick("Roronoa Zoro", word="high"), "exact"),  # an accepted expansion on a control: right, but not a gain
        (exp, gs.Pick("Doffy Prime", word="high"), "expansion_independent"),
    ]
    t = gc.tally(pairs)
    assert (t["good"], t["good_expansion"], t["good_exact"]) == (2, 1, 1)


def test_the_consequences_table_has_one_good_writes_column_per_scope_and_labels_the_tau(tmp_path):
    rep = _big_report(
        tmp_path,
        _with_rev("qwen-local", _mediocre)
        + _with_rev("d", lambda it: "")
        + [_d(it["id"], "d2", _right(it) or "", 0.9) for it in BIG],
    )
    section = gs.render_markdown(rep).split("## Consequences")[1].split("\n## ")[0]
    assert "good writes (expansion items)" in section and "good writes (exact controls, not a gain)" in section
    assert "exact controls right (at this tau)" in section and "| good writes |" not in section


# ---- verdict precedence -----


def test_a_decisive_fail_outranks_a_floor_shortfall_elsewhere(tmp_path):
    items = _big_items_n(60, 30, 140)  # 260 items, all with two candidates
    base = _both_orders(items[:100], "qwen-local", _mediocre)  # the baseline ran 100: (a), (b), (d) are below their floors

    def flip(it):  # 25 of the 260 reversed answers change: 9.6%, interval entirely above 5%
        if int(it["term"][1:]) % 11:
            return _right(it)
        return (
            it["candidates"][0]["title"]
            if it.get("negative")
            else [c["title"] for c in it["candidates"] if c["title"] != it["gold"]][0]
        )

    arm = _rows_for(items, "t", _right) + _rows_for(items, "t", flip, order="rev")
    v = _report_for(tmp_path, items, base + arm)["verdicts"]["t"]
    c = v["rules"]["c"]
    assert c["ok"] is False and not c.get("within_noise") and not c.get("below_floor") and c["n"] >= 100
    assert v["rules"]["a"].get("below_floor") and v["verdict"] == "FAIL"


def test_a_floor_shortfall_still_outranks_a_noisy_fail_and_missing_results(tmp_path):
    items = _big_items_n(20, 15, 50)
    base = _both_orders(items, "qwen-local", _mediocre)
    arm = _rows_for(items, "t", _right) + _rows_for(items, "t", _right, order="rev")[:40]  # (c) below its floor, nothing failing
    assert _report_for(tmp_path, items, base + arm)["verdicts"]["t"]["verdict"] == "INCOMPLETE"


# ---- review load -----


def test_review_load_counts_respelling_flags_only_and_the_other_flags_are_recorded():
    import tools.glossary_consequences as gc

    exacts = [_item(f"E{k}", [f"E{k}", f"E{k} Jr"], f"E{k}", "exact") for k in range(4)]
    negs = [_item(f"N{k}", [f"N{k}x", f"N{k}y"], negative=True) for k in range(2)]
    pairs = [
        (exacts[0], gs.Pick("E0", word="high"), "exact"),  # nothing
        (exacts[1], gs.Pick("Q1", word="high"), "exact"),  # respelling: a human reviews it
        (exacts[2], gs.Pick("E2", word="low"), "exact"),  # recorded, not reviewed
        (exacts[3], gs.Pick("", word="none"), "exact"),  # recorded, not reviewed
        (negs[0], gs.Pick("", word="none"), "negative"),  # the right answer: costs nobody anything
        (negs[1], gs.Pick("N1x", word="low"), "negative"),
    ]
    t = gc.tally(pairs, policy="legacy")
    assert t["review"]["exact"] == {"n": 4, "flagged": 1, "recorded": 2, "per_100": 25.0}
    assert t["review"]["negative"] == {"n": 2, "flagged": 0, "recorded": 2, "per_100": 0.0}
    assert t["harmful_flags"] == 1


# ---- rule (d) against a perfect floor: "cannot be beaten" only for a ----


def _d_against_a_perfect_heuristic(tmp_path, picker):
    items = _big_items_n(20, 15, 50)  # the string rule is perfect on every expansion here
    rows = _both_orders(items, "qwen-local", _mediocre) + _both_orders(items, "t", picker)
    return _report_for(tmp_path, items, rows)["verdicts"]["t"]["rules"]["d"]


def test_an_arm_far_below_a_perfect_floor_is_a_real_fail_not_within_noise(tmp_path):
    d = _d_against_a_perfect_heuristic(tmp_path, lambda it: "")  # answers none on every expansion: 0% against 100%
    assert d["ok"] is False and d["within_noise"] is False
    assert "cannot be beaten" not in d.get("note", "")


def test_an_arm_slightly_below_a_perfect_floor_is_within_noise_by_interval_overlap(tmp_path):
    items = _big_items_n(20, 15, 50)
    wrong_on_one = {items[20]["id"]}  # one expansion answered wrongly, the rest like the string rule

    def picker(it):
        if it["id"] in wrong_on_one:
            return "" if not it.get("negative") else ""
        return gs.heuristic_pick(it).title

    rows = _both_orders(items, "qwen-local", _mediocre) + _both_orders(items, "t", picker)
    d = _report_for(tmp_path, items, rows)["verdicts"]["t"]["rules"]["d"]
    assert d["ok"] is False and d["within_noise"] is True  # 29/30 against 30/30: the intervals overlap
    assert "cannot be beaten" not in d.get("note", "")


def test_an_arm_equal_to_a_perfect_floor_keeps_the_cannot_be_beaten_note(tmp_path):
    d = _d_against_a_perfect_heuristic(tmp_path, lambda it: gs.heuristic_pick(it).title)
    assert d["ok"] is True and d["within_noise"] is True and "cannot be beaten" in d["note"]


def test_the_cell_for_a_decisive_d_fail_does_not_read_within_noise(tmp_path):
    items = _big_items_n(20, 15, 50)
    rows = _both_orders(items, "qwen-local", _mediocre) + _both_orders(items, "t", lambda it: "")
    md = gs.render_markdown(_report_for(tmp_path, items, rows))
    row = [ln for ln in md.split("## Rule verdicts")[1].splitlines() if ln.startswith("| t ")][0]
    assert "FAIL (within noise)" not in row.split("|")[5]  # the (d) cell
