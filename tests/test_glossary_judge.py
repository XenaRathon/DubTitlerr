"""export-judge / import-judge / score --judged: blind judging sets for the glossary bake-off. Synthetic data only; no network."""

import json

import pytest

import tools.glossary_bakeoff as gb
import tools.glossary_score as gs

KEYS = ("qwen-local", "mercury-decide", "longcat-2.0")


def _vitem(term, titles, gold=None, no_call=False):
    it = {
        "id": f"verify:Show One:{term}", "stage": "verify", "show": "Show One", "term": term, "list": "names", "verified": False,
        "candidates": [{"title": t, "score": 0.9} for t in titles], "no_call": no_call, "gold": gold,
    }  # fmt: skip
    if gold:
        it.update(gold_kind="exact", gold_accept=[gold], incumbent_derived=False)
    return it


def _aitem(variant, canonical, quotes):
    historical = {"same_entity": True, "confidence": "high"}
    return {
        "id": f"acquire:Show One:{variant}|{canonical}",
        "stage": "acquire",
        "show": "Show One",
        "variant": variant,
        "canonical": canonical,
        "historical": historical,
        "quotes": quotes,
    }


ITEMS = [
    _vitem("Zoro", ["Zoro", "Roronoa Zoro", "Zorro"], gold="Zoro"),
    _vitem("Luffy", ["Luffy", "Monkey D. Luffy", "Lucy"]),  # no gold
    _vitem("Nami", ["Nami", "Namie"], gold="Nami"),
    _vitem("Sanji", ["Sanji", "Sanjy"], gold="Sanji"),
    _vitem("Agree", ["Agree", "Agreed"], gold="Agree"),
    _vitem("Nada", [], no_call=True),
    _aitem("Zoroo", "Zoro", {"variant": ["Zoroo said hi"], "canonical": ["Zoro drew his sword"]}),
    _aitem("Nammi", "Nami", None),  # no quotes: skipped
]


def _row(item, arm, parsed, order="fwd", error=None):
    return {
        "id": item, "arm": arm, "order": order, "raw": "x", "parsed": parsed, "latency_s": 1.0, "usage": None, "error": error,
    }  # fmt: skip


def _t(item, arm, canonical, conf="high", order="fwd"):
    return _row(item, arm, {"canonical": canonical, "confidence": conf}, order)


def _d(item, arm, title, conf, order="fwd"):
    parsed = {"choice": "c1" if title else "none", "canonical": title, "probabilities": None, "confidence": conf}
    return _row(item, arm, parsed, order)


def _a(item, arm, same, conf="high"):
    return _row(item, arm, {"same_entity": same, "confidence": conf})


def _e(item, arm):
    return _row(item, arm, None, error="HTTP 429")


Z, L, N, S, AG = (f"verify:Show One:{t}" for t in ("Zoro", "Luffy", "Nami", "Sanji", "Agree"))
AQ = "acquire:Show One:Zoroo|Zoro"
ROWS = [
    _t(Z, "qwen-local", "Zoro"),
    _d(Z, "mercury-decide", "Roronoa Zoro", 0.93),
    _t(Z, "longcat-2.0", "Zoro", "low"),  # 2 distinct picks
    _t(L, "qwen-local", ""), _d(L, "mercury-decide", "Monkey D. Luffy", 0.55), _t(L, "longcat-2.0", "Monkey D. Luffy"),  # no gold
    _t(N, "qwen-local", "Nami"), _d(N, "mercury-decide", "Nami", 0.9), _t(N, "longcat-2.0", "Nami"),  # all agree: not exported
    _t(S, "qwen-local", "Sanji"), _d(S, "mercury-decide", "Sanjy", 0.7), _e(S, "longcat-2.0"),  # an errored arm is ignored
    _t(AG, "qwen-local", "Agree"), _t(AG, "mercury-decide", "Agree"),
    _a(AQ, "qwen-local", True), _a(AQ, "longcat-2.0", False), _a(AQ, "mercury-decide", True, "low"),
]  # fmt: skip


@pytest.fixture
def files(tmp_path):
    items = tmp_path / "items.jsonl"
    items.write_text("".join(json.dumps(i) + "\n" for i in ITEMS), encoding="utf-8")
    res = tmp_path / "res.jsonl"
    res.write_text("".join(json.dumps(r) + "\n" for r in ROWS), encoding="utf-8")
    return items, res


def _export(tmp_path, files, *extra, stage="verify", out="judge", arms=KEYS):
    items, res = files
    d = tmp_path / out
    code = gb.main(
        ["export-judge", "--items", str(items), "--results", str(res), "--arms", *arms, "--stage", stage, "--out", str(d), *extra]
    )
    md = (d / "items.md").read_text(encoding="utf-8") if (d / "items.md").exists() else ""
    key = json.loads((d / "key.json").read_text(encoding="utf-8")) if (d / "key.json").exists() else None
    return code, md, key, d


# ---- export-judge: verify ---------------------------------------------------------------------------------------


def test_only_items_where_the_arms_disagree_are_exported(tmp_path, files):
    code, md, key, _ = _export(tmp_path, files)
    assert code == 0
    ids = [k["id"] for k in key["items"]]
    assert Z in ids and S in ids  # Sanji: two arms answered and differ; the third failed and is ignored
    assert N not in ids and AG not in ids  # everyone agrees
    assert L not in ids  # no gold: only with --include-no-gold
    assert "Nada" not in md and "### Item 1" in md


def test_include_no_gold_adds_the_items_without_a_gold_label(tmp_path, files):
    _, md, key, _ = _export(tmp_path, files, "--include-no-gold")
    assert L in [k["id"] for k in key["items"]] and "Luffy" in md


def test_the_verify_layout_is_blind_and_neutral(tmp_path, files):
    _, md, key, _ = _export(tmp_path, files, "--include-no-gold")
    block = md.split("### Item 1")[1].split("### Item 2")[0]
    for line in ("- show: Show One", "- term (as heard in the dub): ", "- wiki titles (candidates):", "- answer A: "):
        assert line in block, line
    assert "historical" not in md.lower() and "confidence" not in md.lower()


def test_no_arm_name_confidence_or_verdict_ever_reaches_items_md(tmp_path, files):
    _, md, _, _ = _export(tmp_path, files, "--include-no-gold")
    low = md.lower()
    for arm in KEYS:
        assert arm.lower() not in low
    for needle in ("0.93", "0.55", "conf", "historical", "mercury", "qwen", "longcat"):
        assert needle not in low, needle


def test_identical_picks_are_merged_and_the_key_maps_labels_to_arms(tmp_path, files):
    _, md, key, _ = _export(tmp_path, files)
    zoro = next(k for k in key["items"] if k["id"] == Z)
    assert len(zoro["answers"]) == 2  # qwen and longcat both said Zoro: one answer
    merged = next(a for a in zoro["answers"].values() if a["pick"] == "Zoro")
    assert sorted(merged["arms"]) == ["longcat-2.0", "qwen-local"]
    other = next(a for a in zoro["answers"].values() if a["pick"] == "Roronoa Zoro")
    assert other["arms"] == ["mercury-decide"]
    assert md.count("- answer ") >= 4  # two for Zoro, two for Sanji


def test_a_none_pick_is_shown_as_none(tmp_path, files):
    _, md, key, _ = _export(tmp_path, files, "--include-no-gold")
    luffy = next(k for k in key["items"] if k["id"] == L)
    assert "none" in [a["pick"] for a in luffy["answers"].values()] and "- answer " in md and ": none" in md


def test_shuffling_is_deterministic_per_seed_and_varies_with_it(tmp_path, files):
    outs = {}
    for seed in ("1", "1", "2", "3"):
        _, md, key, d = _export(tmp_path, files, "--include-no-gold", "--seed", seed, out=f"j{seed}_{len(outs)}")
        outs[f"{seed}_{len(outs)}"] = (md, json.dumps(key, sort_keys=True))
    vals = list(outs.values())
    assert vals[0] == vals[1]  # same seed, byte-identical
    assert vals[0] != vals[2] or vals[0] != vals[3]  # a different seed shuffles (at least one differs)
    for md, _ in vals:
        assert md.count("Roronoa Zoro") >= 1 and md.count("Zorro") >= 1  # every candidate is still listed


def test_sample_takes_a_deterministic_subset(tmp_path, files):
    _, _, key, _ = _export(tmp_path, files, "--include-no-gold", "--sample", "2", "--seed", "5", out="s1")
    _, _, key2, _ = _export(tmp_path, files, "--include-no-gold", "--sample", "2", "--seed", "5", out="s2")
    assert len(key["items"]) == 2 and [k["id"] for k in key["items"]] == [k["id"] for k in key2["items"]]


def test_a_single_arm_or_unknown_arm_cannot_disagree(tmp_path, files):
    code, md, key, _ = _export(tmp_path, files, arms=("qwen-local",), out="one")
    assert code == 0 and key["items"] == []
    items, res = files
    with pytest.raises(SystemExit) as e:
        gb.main(
            [
                "export-judge",
                "--items",
                str(items),
                "--results",
                str(res),
                "--arms",
                "qwen-local",
                "nope",
                "--stage",
                "verify",
                "--out",
                str(tmp_path / "x"),
            ]
        )
    assert e.value.code == 2


# ---- export-judge: acquire ----------------------------------------------------------------------------------------


def test_acquire_layout_has_both_spellings_the_quotes_and_merged_answers(tmp_path, files):
    code, md, key, _ = _export(tmp_path, files, stage="acquire", out="acq")
    assert code == 0 and len(key["items"]) == 1  # the quote-less pair is skipped
    for needle in ('"Zoroo"', "Zoroo said hi", '"Zoro"', "Zoro drew his sword"):
        assert needle in md, needle
    answers = {a["pick"]: sorted(a["arms"]) for a in key["items"][0]["answers"].values()}
    assert answers == {"same entity": ["mercury-decide", "qwen-local"], "different entities": ["longcat-2.0"]}
    for bit in ("historical", "confidence", "qwen", "mercury", "longcat"):
        assert bit not in md.lower()


# ---- import-judge ---------------------------------------------------------------------------------------------------


def _label_of(key, item_id, pick):
    item = next(k for k in key["items"] if k["id"] == item_id)
    return next(lbl for lbl, a in item["answers"].items() if a["pick"] == pick)


def _import(tmp_path, d, text, name="v.txt"):
    v = tmp_path / name
    v.write_text(text, encoding="utf-8")
    out = tmp_path / "judged.jsonl"
    code = gb.main(["import-judge", "--key", str(d / "key.json"), "--verdicts", str(v), "--out", str(out)])
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()] if out.exists() else []
    return code, rows


def test_import_round_trip_maps_labels_back_to_arms(tmp_path, files, capsys):
    _, _, key, d = _export(tmp_path, files)
    n_z = key["items"][[k["id"] for k in key["items"]].index(Z)]["n"]
    good, bad = _label_of(key, Z, "Zoro"), _label_of(key, Z, "Roronoa Zoro")
    code, rows = _import(tmp_path, d, f"{n_z} | best={good} | worst={bad} | the exact name\n")
    assert code == 0
    by_arm = {r["arm"]: r for r in rows if r["item"] == Z}
    assert set(by_arm) == set(KEYS)
    assert by_arm["qwen-local"]["best"] and by_arm["longcat-2.0"]["best"] and not by_arm["mercury-decide"]["best"]
    assert by_arm["mercury-decide"]["worst"] and not by_arm["qwen-local"]["worst"]
    assert (
        by_arm["qwen-local"]["note"] == "the exact name"
        and by_arm["qwen-local"]["stage"] == "verify"
        and by_arm["qwen-local"]["pick"] == "Zoro"
    )
    assert "0 malformed" in capsys.readouterr().out


def test_import_tolerates_spaces_case_multiple_best_and_an_empty_worst(tmp_path, files):
    _, _, key, d = _export(tmp_path, files)
    n_z = next(k["n"] for k in key["items"] if k["id"] == Z)
    a, b = _label_of(key, Z, "Zoro"), _label_of(key, Z, "Roronoa Zoro")
    code, rows = _import(tmp_path, d, f"  {n_z}|  BEST = {a.lower()} , {b.lower()}|worst=|\n")
    assert code == 0 and all(r["best"] for r in rows if r["item"] == Z) and not any(r["worst"] for r in rows)


def test_malformed_lines_are_counted_and_rejected(tmp_path, files, capsys):
    _, _, key, d = _export(tmp_path, files)
    n_z = next(k["n"] for k in key["items"] if k["id"] == Z)
    a = _label_of(key, Z, "Zoro")
    text = "\n".join(
        [
            f"{n_z} | best={a} | worst= | fine",
            "not a verdict line",
            "99 | best=A | worst=B | no such item",
            f"{n_z} | best=Z | worst= | no such label",
            f"{n_z} | worst=A",
            "# a comment is not malformed",
            "",
        ]
    )
    code, rows = _import(tmp_path, d, text)
    out = capsys.readouterr().out
    assert code == 0 and "4 malformed" in out
    assert {r["item"] for r in rows} == {Z}


def test_a_later_verdict_for_the_same_item_wins(tmp_path, files):
    _, _, key, d = _export(tmp_path, files)
    n_z = next(k["n"] for k in key["items"] if k["id"] == Z)
    a, b = _label_of(key, Z, "Zoro"), _label_of(key, Z, "Roronoa Zoro")
    _, rows = _import(tmp_path, d, f"{n_z} | best={a} | worst={b}\n{n_z} | best={b} | worst={a}\n")
    assert next(r for r in rows if r["arm"] == "mercury-decide" and r["item"] == Z)["best"] is True


def test_import_bad_arguments_exit_2(tmp_path):
    for argv in (
        ["import-judge", "--key", str(tmp_path / "no"), "--verdicts", str(tmp_path / "no2"), "--out", str(tmp_path / "o")],
    ):
        with pytest.raises(SystemExit) as e:
            gb.main(argv)
        assert e.value.code == 2


# ---- score --judged -------------------------------------------------------------------------------------------------


def test_the_judged_table_counts_best_worst_net_and_sole_winners_per_stage():
    def r(item, n, arm, pick, best, worst, stage="verify", sole=False):
        return {
            "item": item,
            "n": n,
            "stage": stage,
            "arm": arm,
            "pick": pick,
            "best": best,
            "worst": worst,
            "note": "",
            "sole_best": sole,
        }

    rows = [
        # item 1: qwen alone gave the best answer (sole winner); mercury and longcat share the worst one
        r("i1", 1, "qwen-local", "A", True, False, sole=True),
        r("i1", 1, "mercury-decide", "B", False, True),
        r("i1", 1, "longcat-2.0", "B", False, True),
        # item 2: qwen and longcat share the best answer (not sole), mercury is worst
        r("i2", 2, "qwen-local", "A", True, False),
        r("i2", 2, "longcat-2.0", "A", True, False),
        r("i2", 2, "mercury-decide", "B", False, True),
        r("i3", 1, "qwen-local", "same entity", True, False, stage="acquire", sole=True),
    ]
    t = gs.judged_table(rows)
    q = t["verify"]["qwen-local"]
    assert (q["judged"], q["best"], q["worst"], q["net"], q["sole"]) == (2, 2, 0, 2, 1)
    m = t["verify"]["mercury-decide"]
    assert (m["judged"], m["best"], m["worst"], m["net"], m["sole"]) == (2, 0, 2, -2, 0)
    assert t["acquire"]["qwen-local"]["sole"] == 1 and "mercury-decide" not in t["acquire"]


def test_score_judged_prints_the_headline_table(tmp_path, files):
    items, res = files
    _, _, key, d = _export(tmp_path, files)
    n_z = next(k["n"] for k in key["items"] if k["id"] == Z)
    a, b = _label_of(key, Z, "Zoro"), _label_of(key, Z, "Roronoa Zoro")
    _import(tmp_path, d, f"{n_z} | best={a} | worst={b}\n")
    out = tmp_path / "report.md"
    code = gb.main(
        ["score", "--items", str(items), "--results", str(res), "--judged", str(tmp_path / "judged.jsonl"), "--out", str(out)]
    )
    md = out.read_text(encoding="utf-8")
    assert code == 0 and "## Blind-judged accuracy (headline)" in md
    section = md.split("## Blind-judged accuracy (headline)")[1].split("\n## ")[0]
    assert "verify" in section and "qwen-local" in section and "sole" in section.lower()
    assert md.index("## Blind-judged accuracy (headline)") < md.index("## Accuracy by class")


def test_the_import_marks_sole_winners(tmp_path, files):
    _, _, key, d = _export(tmp_path, files)
    n_z = next(k["n"] for k in key["items"] if k["id"] == Z)
    a, b = _label_of(key, Z, "Zoro"), _label_of(key, Z, "Roronoa Zoro")
    _, rows = _import(tmp_path, d, f"{n_z} | best={b} | worst={a}\n")
    sole = {r["arm"]: r["sole_best"] for r in rows if r["item"] == Z}
    assert sole == {"mercury-decide": True, "qwen-local": False, "longcat-2.0": False}
