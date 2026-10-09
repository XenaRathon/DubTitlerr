"""Phase 28 F9: an exact known phrase vouches for its own component tokens, and re-spacing a known phrase is not a large change.

Sol's probe: glossary phrases ["Van der Decken"] (the shape verify writes: a long form goes into `phrases`, not `names`), the
line "Vanderdecken and Vanderdecken are here with us." and the proposal "Van der Decken and Van der Decken are here with us."
was refused as invents_name and then hidden by the default auto-dismiss (8 word changes)."""

import json

import glossary
import repair
import unresolved

ORIG = "Vanderdecken and Vanderdecken are here with us."
NEW = "Van der Decken and Van der Decken are here with us."
PHRASES = {"names": [], "phrases": ["Van der Decken"]}


def gl(**kw):
    return glossary.load_dict({**PHRASES, **kw})


def test_invents_name_accepts_the_respacing_of_a_listed_phrase():
    assert not repair.invents_name(ORIG, NEW, gl())
    assert repair.rejecting_guard(ORIG, NEW, ORIG, 6.0, gl()) is None


def test_the_phrase_vouches_only_when_it_is_present_whole():
    """A component alone is still a conjured name: 'Decken' with no 'Van der' in front is not vouched by the phrase."""
    assert repair.invents_name("Vanderdecken is here.", "Decken is here.", gl())
    assert repair.invents_name("Vanderdecken is here.", "Van Decken is here.", gl())


def test_a_name_the_glossary_does_not_know_is_still_refused():
    assert repair.invents_name(ORIG, "Van der Hocken and Van der Hocken are here with us.", gl())


def test_word_changes_counts_a_known_phrase_respacing_as_zero():
    assert unresolved.word_changes(ORIG, NEW) == 8  # no phrases given: the legacy count
    assert unresolved.word_changes(ORIG, NEW, phrases=["Van der Decken"]) == 0
    assert unresolved.word_changes(NEW, ORIG, phrases=["Van der Decken"]) == 0  # symmetric
    assert unresolved.word_changes("a b c", "a x y z", phrases=["Van der Decken"]) == 5  # unrelated changes still count


def test_the_respacing_is_not_hidden_when_it_is_refused_for_another_reason(tmp_path, monkeypatch):
    """End to end through repair.process: a re-spacing that a guard refuses stays in the primary queue."""
    import test_repair_dismiss as d

    gloss = gl()
    monkeypatch.setattr(repair, "invents_name", lambda *a: True)  # force a refusal; the dismissal is what is under test
    stem, summary = d._episode(tmp_path, monkeypatch, ORIG, NEW, gloss)
    (entry,) = unresolved.items(stem)
    assert entry["reason"] in ("rejected_name_invented", "rejected_guard") and "dismissed" not in entry
    assert unresolved.pending(stem, primary_only=True) != []
    assert json.load(open(stem + ".dubtitles.repair-summary.json")) == summary
