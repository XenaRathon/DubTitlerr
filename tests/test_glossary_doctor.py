"""The invariant a verified glossary term must hold: it stays IN SERVICE.

`glossary_verify.apply_results()` used to overwrite a term with its wiki canonical, leaving
the original only in `verified` -- a key `glossary.load_dict()` never reads. Every counter
the run reported moved the right way (129 verified, 105 known, 7 flagged) while the runtime
dictionary lost 23 terms. These tests are the alarm that was missing."""

import json

from tools import glossary_doctor as doc


def test_a_verified_term_must_be_reachable_at_runtime():
    g = {"names": ["Luffy"], "phrases": [], "hard_fixes": {}, "verified": ["Luffy", "Doflamingo"]}
    assert doc.diagnose(g)["stranded"] == ["Doflamingo"]


def test_hard_fixes_VALUES_count_as_reachable():
    """`correct()` rewrites to the value, so a term living only there is still in service.
    Alabasta and Straw Hats are real cases -- an invariant that missed this would raise two
    false alarms on the live glossary."""
    g = {"names": [], "phrases": [], "hard_fixes": {"arabasta": "Alabasta"}, "verified": ["Alabasta"]}
    assert doc.diagnose(g)["stranded"] == []


def test_a_flagged_term_is_legitimately_out_of_service():
    """A human rejection is a decision, not damage. Without this the operator has to choose
    between a permanent false alarm and deleting the audit trail."""
    g = {
        "names": [],
        "phrases": [],
        "hard_fixes": {},
        "verified": ["Ratel"],
        "flagged": {"Ratel": {"reason": "respelling-needs-review"}},
    }
    assert doc.diagnose(g)["ok"] is True


def test_multi_word_in_names_is_a_defect():
    """`names` feeds a per-TOKEN matcher (`_TOKEN_RE` matches one token), so a multi-word
    entry there can never fire."""
    g = {"names": ["Boa Hancock"], "phrases": [], "hard_fixes": {}, "verified": []}
    assert doc.diagnose(g)["misshaped"] == ["Boa Hancock"]


def test_repair_restores_by_shape():
    g = {"names": [], "phrases": [], "hard_fixes": {}, "verified": ["Doflamingo", "Straw Hat Pirates"]}
    out, _ = doc.repair(g)
    assert "Doflamingo" in out["names"]
    assert "Straw Hat Pirates" in out["phrases"]


def test_repair_moves_add_then_remove():
    """A move done remove-then-add loses the term outright if the process dies between the
    two steps -- strictly worse than the bug being repaired."""
    g = {"names": ["Boa Hancock", "Luffy"], "phrases": [], "hard_fixes": {}, "verified": []}
    out, _ = doc.repair(g)
    assert "Boa Hancock" in out["phrases"] and "Boa Hancock" not in out["names"]
    assert "Luffy" in out["names"]


def test_repair_is_idempotent():
    g = {"names": ["Boa Hancock"], "phrases": [], "hard_fixes": {}, "verified": ["Doflamingo"]}
    once, _ = doc.repair(g)
    twice, rep = doc.repair(once)
    assert once == twice and rep["ok"] is True


def test_repair_never_mutates_its_input():
    g = {"names": ["Boa Hancock"], "phrases": [], "hard_fixes": {}, "verified": []}
    before = json.dumps(g, sort_keys=True)
    doc.repair(g)
    assert json.dumps(g, sort_keys=True) == before


def test_drop_prompt_terms_splits_on_fields_not_substrings():
    """`initial_prompt` is one comma-joined string. A `replace()` would cut a name in half
    or take a prefix of a longer one."""
    g = {
        "initial_prompt": "Spell names correctly: Luffy, Zoro. Attack names: Gum-Gum Pistol, Gum-Gum Bazooka, Gear Second.",
        "phrases": ["Gum-Gum Pistol", "Gum-Gum Bazooka", "Gear Second"],
    }
    out, dropped = doc.drop_prompt_terms(g, ["Gum-Gum Bazooka", "Gear Second"], "unverified-attack-name")
    assert "Gum-Gum Pistol" in out["initial_prompt"]
    assert "Gum-Gum Bazooka" not in out["initial_prompt"]
    assert "Gear Second" not in out["initial_prompt"]
    assert out["phrases"] == ["Gum-Gum Pistol"]
    assert sorted(dropped) == ["Gear Second", "Gum-Gum Bazooka"]


def test_dropped_terms_are_flagged_so_the_next_sweep_does_not_re_propose():
    g = {"initial_prompt": "Attack names: Gear Second.", "phrases": ["Gear Second"]}
    out, _ = doc.drop_prompt_terms(g, ["Gear Second"], "unverified-attack-name")
    assert out["flagged"]["Gear Second"]["reason"] == "unverified-attack-name"


def test_the_committed_glossaries_hold_the_invariant():
    """CI alarm. The other 14 shows are clean today; this fails the build if any drifts."""
    import glob
    import os

    bad = {}
    for p in glob.glob("glossaries/*.json"):
        if p.endswith((".lastrun.json", ".bak")):
            continue
        rep = doc.diagnose(json.load(open(p, encoding="utf-8")))
        if not rep["ok"]:
            bad[os.path.basename(p)] = rep
    assert not bad, f"glossaries violating the invariant: {bad}"
