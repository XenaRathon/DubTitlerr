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


def _report(tmp_path, rows, baseline="qwen-local", tau_step=0.25, items=ITEMS):
    return gs.build_report(
        gs.load_items(str(_write_items(tmp_path, items))), gs.load_results([str(_write_rows(tmp_path, rows))]), baseline, tau_step
    )


@pytest.fixture
def small_floors(monkeypatch):
    """The sample-size floors (100 common labelled items, 90% of the baseline's) off, for tests of one rule on a tiny set."""
    monkeypatch.setattr(gs, "MIN_COMMON_N", 1)
    monkeypatch.setattr(gs, "MIN_COMMON_FRAC", 0.0)


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


def test_matched_operating_point_is_the_smallest_tau_not_above_the_baselines_false_accept(tmp_path, small_floors):
    base = [_t(IDS["Xa"], "qwen-local", "Xa Zed"), _t(IDS["Xc"], "qwen-local", "Xc Prime"), _t(NEG["Ng1"], "qwen-local", "")]
    # on the 3 shared non-trivial items the baseline accepts 2 with 1 wrong: FA 1/2; positives Xa, Xc -> TA 1/2
    dec = [
        _d(IDS["Xa"], "d", "Xa Zed", 0.4),
        _d(IDS["Xb"], "d", "Xb Prime", 0.8),  # not shared
        _d(IDS["Xc"], "d", "Xc Prime", 0.7),
        _d(NEG["Ng1"], "d", "", 0.9),
    ]
    m = _report(tmp_path, base + dec, tau_step=0.1)["arms"]["d"]["matched"]
    assert (
        m["n_common"] == 3
        and m["baseline_false_accept"] == pytest.approx(0.5)
        and m["baseline_true_accept"] == pytest.approx(0.5)
    )
    assert m["tau"] == pytest.approx(0.0)  # FA 1/2 already at tau 0, which is not above the baseline's


def test_a_tau_above_zero_is_chosen_when_low_confidence_picks_are_the_wrong_ones(tmp_path, small_floors):
    base = [
        _t(IDS["Xa"], "qwen-local", "Xa Prime"),
        _t(IDS["Xc"], "qwen-local", "Xc Prime"),
        _t(NEG["Ng1"], "qwen-local", ""),
    ]  # FA 0
    dec = [_d(IDS["Xa"], "d", "Xa Zed", 0.4), _d(IDS["Xc"], "d", "Xc Prime", 0.7), _d(NEG["Ng1"], "d", "", 0.9)]
    m = _report(tmp_path, base + dec, tau_step=0.1)["arms"]["d"]["matched"]
    assert m["tau"] == pytest.approx(0.5) and m["arm_false_accept"] == 0.0 and m["arm_true_accept"] == pytest.approx(1 / 2)


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
            titles = [f"{cls_name}{k} Prime", f"{cls_name}{k} Zed"] if k < 5 else [f"{cls_name}{k} Zed", f"{cls_name}{k} Prime"]
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
    assert v["rules"]["a"]["ok"] is None and v["rules"]["b"]["ok"] is None and "accepted nothing" in v["rules"]["a"]["note"]
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
    assert d["classes"]["expansion_independent"]["arm"] == 1.0 and d["classes"]["expansion_independent"][
        "floor"
    ] == pytest.approx(0.25)
    assert d["balanced"]["arm"] == 1.0 and d["balanced"]["floor"] == pytest.approx((0.25 + 0.0) / 2)


def test_the_report_shows_the_secondary_all_class_column_and_the_expansion_split(tmp_path):
    md = gs.render_markdown(_big_report(tmp_path, _with_rev("qwen-local", _mediocre) + _with_rev("t", _right)))
    verdicts = md.split("## Rule verdicts")[1]
    assert "all classes" in verdicts and "independent" in verdicts and "incumbent" in verdicts and "balanced" in verdicts
