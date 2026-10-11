"""Scoring an arm by what lands in the glossary, the way glossary_verify.apply_results acts on an answer.

Synthetic items only. The classification is checked against production by running apply_results on the same adjudications."""

import pytest

import glossary_verify as gv
import tools.glossary_consequences as gc
import tools.glossary_score as gs


def _item(term, titles, gold=None, kind=None, accept=None, negative=False, incumbent=False):
    it = {
        "id": f"verify:S:{term}", "stage": "verify", "show": "S", "term": term, "list": "names", "verified": False,
        "candidates": [{"title": t, "score": 0.9} for t in titles], "no_call": False, "gold": gold,
    }  # fmt: skip
    if negative:
        it.update(id=f"verify-neg:S:{term}", negative=True, gold="none", gold_kind="negative")
    elif gold:
        it.update(gold_kind=kind, gold_accept=accept or [gold], incumbent_derived=incumbent)
    return it


EXACT = _item("Zoro", ["Zoro", "Lord Zoro"], "Zoro", "exact", ["Zoro", "Lord Zoro"])
EXP = _item("Doffy", ["Doffy Prime", "Doffy Zed"], "Doffy Prime", "expansion")
NEG = _item("Nilo", ["Nilox", "Niloy"], negative=True)
P = gs.Pick


def high(title):
    return P(title, word="high")


def low(title):
    return P(title, word="low")


NONE = P("", word="none")

# ---- classification: one case per outcome production distinguishes ---------------------------------------------------------


@pytest.mark.parametrize(
    "item,pick,outcome",
    [
        (EXP, high("Doffy Prime"), "good_write"),  # a high-confidence expansion in the accepted set is WRITTEN
        (EXP, high("Doffy Zed"), "wrong_write"),  # ...an expansion that is not the accepted one is written too: a wrong write
        (NEG, high("Nilox"), "wrong_write"),  # any expansion write on a gold-none item is wrong
        (EXACT, high("Lord Zoro"), "good_write"),  # an accepted expansion of a correct term is a correct write
        (EXACT, high("Zoro"), "nothing"),  # canonical == term writes nothing: correct
        (EXP, high("Doffy"), "nothing"),
        (EXACT, high("Zorro"), "flag_respelling"),  # high confidence, not an expansion: flagged for review
        (EXP, high("Dofi"), "flag_respelling"),
        (EXP, low("Doffy Prime"), "flag_low"),  # low confidence with a canonical
        (EXACT, low("Zoro"), "flag_low"),  # even the right title at low confidence is flagged
        (EXP, NONE, "flag_nomatch"),
        (NEG, NONE, "flag_nomatch"),
        (EXP, P("", conf=0.2), "flag_nomatch"),
        (EXP, None, "failure"),
    ],
)
def test_the_classification_follows_apply_results(item, pick, outcome):
    assert gc.classify(item, pick, policy="legacy") == outcome


def test_decision_arms_are_high_confidence_at_or_above_tau():
    assert gc.classify(EXP, P("Doffy Prime", conf=0.7), tau=0.7, policy="legacy") == "good_write"
    assert gc.classify(EXP, P("Doffy Prime", conf=0.69), tau=0.7, policy="legacy") == "flag_low"
    assert gc.classify(NEG, P("Nilox", conf=0.95), tau=0.5, policy="legacy") == "wrong_write"
    assert gc.classify(NEG, P("Nilox", conf=0.3), tau=0.5, policy="legacy") == "flag_low"  # not written: only review load


def test_a_wrong_pick_on_a_negative_that_is_not_an_expansion_is_review_load_not_a_wrong_write():
    """Negatives have every expansion removed, so a wrong pick there can only be a respelling: flagged, never written."""
    neg = _item("Nilo", ["Nilax", "Nelo"], negative=True)
    assert gc.classify(neg, high("Nelo")) == "flag_respelling"


@pytest.mark.parametrize(
    "item,pick,adjudication",
    [
        (EXP, high("Doffy Prime"), {"canonical": "Doffy Prime", "confidence": "high"}),
        (EXP, high("Doffy Zed"), {"canonical": "Doffy Zed", "confidence": "high"}),
        (EXACT, high("Zorro"), {"canonical": "Zorro", "confidence": "high"}),
        (EXACT, high("Zoro"), {"canonical": "Zoro", "confidence": "high"}),
        (EXP, low("Doffy Prime"), {"canonical": "Doffy Prime", "confidence": "low"}),
        (EXP, NONE, {"canonical": "", "confidence": "none"}),
        (NEG, high("Nilox"), {"canonical": "Nilox", "confidence": "high"}),
    ],
)
def test_the_classification_agrees_with_what_production_does(monkeypatch, item, pick, adjudication):
    """Same adjudication through glossary_verify.apply_results: the same written / flagged outcome. classify mirrors the legacy
    substring rule and the queued no-match, so the two phase-27 defaults are set back to it here."""
    monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "0")
    monkeypatch.setenv("VERIFY_QUEUE_NO_MATCH", "1")
    gloss = {"names": [item["term"]], "phrases": []}
    new = gv.apply_results(gloss, {item["term"]: adjudication})
    written = [n for n in new["names"] + new["phrases"] if n != item["term"]]
    flagged = new.get("flagged", {}).get(item["term"])
    outcome = gc.classify(item, pick)
    if outcome in ("good_write", "wrong_write"):
        assert written == [pick.title] and flagged is None
    elif outcome == "flag_respelling":
        assert not written and flagged["reason"] == "respelling-needs-review"
    elif outcome == "flag_low":
        assert not written and flagged["reason"] == "low-confidence"
    elif outcome == "flag_nomatch":
        assert not written and flagged == "no-match"
    else:  # nothing: no write, no flag
        assert not written and flagged is None


# ---- the tally ---------------------------------------------------------------------------------------------------------------


def _pairs(*specs):
    out = []
    for item, pick in specs:
        out.append((item, pick, gs.item_class(item)))
    return out


def test_good_wrong_and_missed_writes_are_counted_with_the_missed_breakdown():
    exps = [_item(f"X{k}", [f"X{k} Prime", f"X{k} Zed"], f"X{k} Prime", "expansion") for k in range(7)]
    picks = [
        high("X0 Prime"),  # good write
        high("X1 Zed"),  # wrong write (also a miss)
        NONE,  # missed: picked none
        low("X3 Prime"),  # missed: low confidence
        high("Q4"),  # missed: a respelling (flagged)
        high("X5"),  # missed: picked the term itself
        None,  # missed: failed
    ]
    t = gc.tally(_pairs(*zip(exps, picks, strict=True)), policy="legacy")
    assert (t["good_expansion"], t["wrong"], t["writes"]) == (1, 1, 2)
    assert t["n_expansion"] == 7 and t["good_write_rate"] == pytest.approx(1 / 7)
    assert t["wrong_write_rate"] == pytest.approx(1 / 2) and t["wrong_write_wilson"][0] < 0.5 < t["wrong_write_wilson"][1]
    assert t["missed"] == {"none": 1, "low": 1, "respelling": 1, "wrong_write": 1, "term_itself": 1, "failure": 1}
    assert sum(t["missed"].values()) == t["n_expansion"] - t["good_expansion"]


def test_review_load_per_100_items_by_class_and_harmful_flags():
    exacts = [_item(f"E{k}", [f"E{k}", f"E{k} Jr"], f"E{k}", "exact") for k in range(4)]
    negs = [_item(f"N{k}", [f"N{k}x", f"N{k}y"], negative=True) for k in range(2)]
    specs = [
        (exacts[0], high("E0")),  # nothing
        (exacts[1], high("E1 Jr")),  # an accepted... not in this accept set -> wrong write? gold_accept is just the term
        (exacts[2], high("Q2")),  # harmful: high respelling flag on a correct term
        (exacts[3], low("E3")),  # a flag on a control
        (negs[0], NONE),  # expected flag
        (negs[1], high("N1x")),  # wrong write
    ]
    t = gc.tally(_pairs(*specs), policy="legacy")
    assert t["harmful_flags"] == 1
    assert t["exact"] == {"n": 4, "correct": 1, "wrong_writes": 1}
    assert t["review"]["exact"] == {"n": 4, "flagged": 1, "recorded": 1, "per_100": 25.0}
    assert t["review"]["negative"] == {"n": 2, "flagged": 0, "recorded": 1, "per_100": 0.0}
    assert t["wrong"] == 2 and t["writes"] == 2  # E1 Jr and N1x


def test_picking_the_exact_title_on_exact_items_is_correct_and_writes_nothing():
    exacts = [_item(f"E{k}", [f"E{k}", f"E{k} Jr"], f"E{k}", "exact") for k in range(3)]
    t = gc.tally(_pairs(*[(e, high(e["term"])) for e in exacts]))
    assert t["exact"]["correct"] == 3 and t["writes"] == 0 and t["review"]["exact"]["flagged"] == 0


def test_an_arm_that_always_says_none_makes_no_writes_good_or_wrong():
    exps = [_item(f"X{k}", [f"X{k} Prime", f"X{k} Zed"], f"X{k} Prime", "expansion") for k in range(5)]
    t = gc.tally(_pairs(*[(e, NONE) for e in exps]))
    assert t["writes"] == 0 and t["wrong_write_rate"] is None and t["good_write_rate"] == 0.0
    assert t["missed"]["none"] == 5


def test_tally_at_a_tau_for_a_decision_arm():
    exps = [_item(f"X{k}", [f"X{k} Prime", f"X{k} Zed"], f"X{k} Prime", "expansion") for k in range(3)]
    picks = [P("X0 Prime", conf=0.9), P("X1 Zed", conf=0.6), P("X2 Prime", conf=0.3)]
    pairs = _pairs(*zip(exps, picks, strict=True))
    assert (gc.tally(pairs, tau=0.0, policy="legacy")["writes"], gc.tally(pairs, tau=0.0, policy="legacy")["wrong"]) == (3, 1)
    assert (gc.tally(pairs, tau=0.5, policy="legacy")["writes"], gc.tally(pairs, tau=0.5, policy="legacy")["wrong"]) == (2, 1)
    assert (gc.tally(pairs, tau=0.8, policy="legacy")["writes"], gc.tally(pairs, tau=0.8, policy="legacy")["wrong"]) == (1, 0)


def test_the_held_out_split_is_deterministic_and_roughly_even():
    ids = [f"verify:S:T{k}" for k in range(400)]
    a = [i for i in ids if gc.half(i) == 0]
    assert a == [i for i in ids if gc.half(i) == 0] and 150 < len(a) < 250


# ---- production-policy mode ----------------------------------------------------------------------------------


def test_production_policy_term_whole_word_accepted():
    item = _item("Zoro", ["Roronoa Zoro"], "Roronoa Zoro", "expansion")
    assert gc.classify(item, high("Roronoa Zoro"), policy="production") == "good_write"


def test_production_policy_substring_only_match_refused():
    item = _item("Usop", ["Usopp"], "Usopp", "expansion")
    # Substring is an expansion under the legacy rule, but fails whole-word guard under production policy
    assert gc.classify(item, high("Usopp"), policy="legacy") == "good_write"
    assert gc.classify(item, high("Usopp"), policy="production") == "flag_respelling"


def test_production_policy_common_word_refused(monkeypatch):
    import glossary

    monkeypatch.setattr(glossary, "_ORDINARY", {"castle", "government"})
    item = _item("Castle", ["Castle Rock"], "Castle Rock", "expansion")
    assert gc.classify(item, high("Castle Rock"), policy="legacy") == "good_write"
    assert gc.classify(item, high("Castle Rock"), policy="production") == "flag_common_word"


def test_production_policy_guard_flags_off_changes_prediction(monkeypatch):
    item = _item("Usop", ["Usopp"], "Usopp", "expansion")
    assert gc.classify(item, high("Usopp"), policy="production") == "flag_respelling"
    monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "0")
    assert gc.classify(item, high("Usopp"), policy="production") == "good_write"


def test_production_policy_per_outcome_counts_and_legacy_label():
    item_exp = _item("Zoro", ["Roronoa Zoro"], "Roronoa Zoro", "expansion")
    item_sub = _item("Usop", ["Usopp"], "Usopp", "expansion")
    item_neg = _item("Nilo", ["Nilox"], negative=True)
    pairs = [
        (item_exp, high("Roronoa Zoro"), "expansion_independent"),  # WRITTEN (right)
        (item_sub, high("Usopp"), "expansion_independent"),         # QUEUED (right candidate held for review)
        (item_neg, NONE, "negative"),                               # RECORDED-NOT-QUEUED (right, none on neg)
    ]
    t_prod = gc.tally(pairs, policy="production")
    assert t_prod["mode"] == "PRODUCTION"
    assert t_prod["outcomes"]["WRITTEN"] == {"total": 1, "right": 1, "wrong": 0}
    assert t_prod["outcomes"]["QUEUED"] == {"total": 1, "right": 1, "wrong": 0}
    assert t_prod["outcomes"]["RECORDED-NOT-QUEUED"] == {"total": 1, "right": 1, "wrong": 0}

    t_leg = gc.tally(pairs, policy="legacy")
    assert t_leg["mode"] == "LEGACY"


def test_classify_defaults_to_production_policy():
    item = _item("Usop", ["Usopp"], "Usopp", "expansion")
    # By default without policy keyword, production policy is used
    assert gc.classify(item, high("Usopp")) == "flag_respelling"
    # Legacy policy remains reachable explicitly
    assert gc.classify(item, high("Usopp"), policy="legacy") == "good_write"


def test_tally_defaults_to_production_policy():
    item = _item("Usop", ["Usopp"], "Usopp", "expansion")
    # By default without policy keyword, production policy is used
    t = gc.tally([(item, high("Usopp"), "expansion_independent")])
    assert t["mode"] == "PRODUCTION"
    assert t["policy"] == "production"
    # Legacy policy remains reachable explicitly
    t_leg = gc.tally([(item, high("Usopp"), "expansion_independent")], policy="legacy")
    assert t_leg["mode"] == "LEGACY"
    assert t_leg["policy"] == "legacy"


def test_cli_policy_flag():
    # Default without flag should be production
    p_default = gc.parse_args([])
    assert p_default.policy == "production"

    # Explicit production
    p_prod = gc.parse_args(["--policy", "production"])
    assert p_prod.policy == "production"

    # Explicit legacy
    p_leg = gc.parse_args(["--policy", "legacy"])
    assert p_leg.policy == "legacy"


def test_glossary_score_passes_policy_and_labels_mode():
    rep_default = gs.build_report([], {})
    assert rep_default["policy"] == "production"
    assert rep_default["mode"] == "PRODUCTION"
    assert "(PRODUCTION)" in gs.render_markdown(rep_default)

    rep_leg = gs.build_report([], {}, policy="legacy")
    assert rep_leg["policy"] == "legacy"
    assert rep_leg["mode"] == "LEGACY"
    assert "(LEGACY)" in gs.render_markdown(rep_leg)


def test_glossary_bakeoff_score_policy_flag(monkeypatch, tmp_path):
    import tools.glossary_bakeoff as gb

    called_policy = []

    def mock_build_report(items, rows, baseline, tau_step, judged, policy="production"):
        called_policy.append(policy)
        return {"arms": {}, "policy": policy, "mode": "PRODUCTION" if policy == "production" else "LEGACY"}

    monkeypatch.setattr(gs, "build_report", mock_build_report)
    monkeypatch.setattr(gs, "render_markdown", lambda r: f"Report {r.get('mode')}\n")

    items_f = tmp_path / "items.jsonl"
    items_f.write_text("")
    res_f = tmp_path / "res.jsonl"
    res_f.write_text("")

    # Default score policy is production
    gb.main(["score", "--items", str(items_f), "--results", str(res_f)])
    assert called_policy[-1] == "production"

    # Explicit legacy policy
    gb.main(["score", "--items", str(items_f), "--results", str(res_f), "--policy", "legacy"])
    assert called_policy[-1] == "legacy"

    # Explicit production policy
    gb.main(["score", "--items", str(items_f), "--results", str(res_f), "--policy", "production"])
    assert called_policy[-1] == "production"



