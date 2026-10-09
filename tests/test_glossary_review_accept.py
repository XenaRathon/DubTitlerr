"""A reviewer's 'y' on a flagged expansion writes it, exactly as apply_results would have (glossary_acquire --review).

The flags are produced by the real apply_results, so the entries have the shape the review sees. Synthetic words only."""

import pytest

import glossary
import glossary_acquire as ga
import glossary_verify as gv


def high(canon):
    return {"canonical": canon, "confidence": "high", "dub_note": ""}


def base(**extra):
    return {"show": "S", "names": [], "phrases": [], "hard_fixes": {}, **extra}


def flagged_by(monkeypatch, reason):
    """(glossary, term, canon) with `term` flagged for `reason` by the real apply_results."""
    if reason == "common-word":
        monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
        monkeypatch.setattr(glossary, "_ORDINARY", {"drake"})
        term, canon = "Drake", "X Drake"
        g = base(names=[term])
    elif reason == "not-in-arc-pages":
        monkeypatch.setenv("VERIFY_ARC_GATE", "1")
        term, canon = "Weevil", "Edward Weevil"
        g = base(
            names=[term],
            arc_titles={"Wano": ["Kaido"]},
            arc_coverage={a: {"titles": len(t), "redirects": True} for a, t in {"Wano": ["Kaido"]}.items()},
        )
    else:  # respelling-needs-review, from the whole-word guard
        monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "1")
        term, canon = "Usop", "Usopp"
        g = base(names=[term])
    out = gv.apply_results(g, {term: high(canon)})
    assert out["flagged"][term]["reason"] == reason and canon not in out["names"] + out["phrases"]
    return out, term, canon


@pytest.mark.parametrize("reason", ["common-word", "not-in-arc-pages", "respelling-needs-review"])
def test_accepting_a_flagged_expansion_writes_it_like_apply_results(monkeypatch, reason):
    g, term, canon = flagged_by(monkeypatch, reason)
    out = ga.record_decision(g, term, accept=True)
    assert canon in out["names"] + out["phrases"] and term in out["names"]  # written, the term itself left in place
    assert "flagged" not in out or term not in out["flagged"]
    assert out["acquired"][term]["canonical"] == canon
    assert out["acquired"][term]["reason"] == "human-approved" and out["acquired"][term]["run"] == "review"
    assert not [i for i in ga.review_items(out) if i["term"] == term]  # the reviewer is not asked again


@pytest.mark.parametrize("reason", ["common-word", "not-in-arc-pages", "respelling-needs-review"])
def test_the_written_form_is_the_one_apply_results_writes(monkeypatch, reason):
    g, term, canon = flagged_by(monkeypatch, reason)
    written = ga.record_decision(g, term, accept=True)
    for var in ("VERIFY_SKIP_COMMON_WORDS", "VERIFY_ARC_GATE", "VERIFY_WRITE_WHOLE_WORD"):
        monkeypatch.delenv(var, raising=False)
    reference = gv.apply_results(base(names=[term]), {term: high(canon)})  # the ungated write
    assert written["names"] == reference["names"] and written["phrases"] == reference["phrases"]


@pytest.mark.parametrize("reason", ["common-word", "not-in-arc-pages", "respelling-needs-review"])
def test_rejecting_is_unchanged_the_term_is_marked_correct_and_nothing_is_written(monkeypatch, reason):
    g, term, canon = flagged_by(monkeypatch, reason)
    out = ga.record_decision(g, term, accept=False)
    assert term in out["known"] and canon not in out["names"] + out["phrases"]
    assert "flagged" not in out and "acquired" not in out


def test_accepting_twice_does_not_duplicate_the_write(monkeypatch):
    g, term, canon = flagged_by(monkeypatch, "common-word")
    once = ga.record_decision(g, term, accept=True)
    twice = ga.record_decision(once, term, accept=True)  # no flag any more: the second answer is the no-flag path
    assert (once["names"] + once["phrases"]).count(canon) == 1 and (twice["names"] + twice["phrases"]).count(canon) == 1


def test_other_reasons_keep_their_behaviour(monkeypatch):
    """GUARD (passes on the old code): an expansion flagged for a reason outside the three is still refused on 'y'."""
    g = base(names=["Drake"], flagged={"Drake": {"reason": "low-confidence", "canonical": "X Drake"}})
    out = ga.record_decision(g, "Drake", accept=True)
    assert out["flagged"]["Drake"]["reason"] == "unsafe-canonical-rejected" and "X Drake" not in out["names"] + out["phrases"]
