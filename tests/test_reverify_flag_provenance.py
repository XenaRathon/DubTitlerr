"""Phase 29 F13 (a note, not a fix): a successful re-verify that affirms the term leaves an earlier verify-owned correction
proposal in the review queue. Sol's self-rebuttal downgraded this: clearing every flag after a model answer could delete another
stage's evidence, so the behaviour is kept and pinned here, and documented in the CHANGELOG. Changing it is a policy decision."""

import glossary_acquire as ga
import glossary_verify as gv

OLD = {"reason": "respelling-needs-review", "canonical": "Ratel"}


def reverified():
    initial = {"show": "S", "names": ["Raftel"], "phrases": [], "flagged": {"Raftel": dict(OLD)}}
    return gv.apply_results(initial, {"Raftel": {"canonical": "Raftel", "confidence": "high"}})


def test_the_earlier_proposal_stays_visible_after_an_affirming_reverify():
    assert reverified()["flagged"]["Raftel"] == OLD


def test_nothing_is_written_by_the_reverify_itself():
    out = reverified()
    assert "hard_fixes" not in out and out["names"] == ["Raftel"] and out["phrases"] == []


def test_accepting_it_is_still_the_reviewers_explicit_choice():
    assert ga.record_decision(reverified(), "Raftel", accept=True)["hard_fixes"] == {"Raftel": "Ratel"}
