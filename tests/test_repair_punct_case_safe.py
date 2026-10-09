"""Phase 20: REPAIR_ACCEPT_PUNCT_CASE_ONLY leniency is limited to edits that cannot change meaning or wreck a card."""

import pytest

import glossary
import repair
import unresolved

GL = glossary.load_dict({"names": ["Kaido", "Monkey D. Luffy"], "phrases": ["Straw Hat Pirates"]})


@pytest.fixture(autouse=True)
def flag(monkeypatch):
    monkeypatch.setenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", "1")
    monkeypatch.setattr(
        glossary, "_ORDINARY", {"us", "march", "turkey"}
    )  # a word list that is present, whatever this machine has
    monkeypatch.setattr(glossary, "_ORDINARY_STATUS", "ok")


# ---- 1. sequences, not multisets ----------------------------------- ----


def test_a_reorder_is_not_punctuation_only():
    assert unresolved.word_changes("The dog bit the man.", "The man bit the dog.") == 0  # the dismissal counter stays a multiset
    assert not repair.is_punct_case_only("The dog bit the man.", "The man bit the dog.", GL)
    # no leniency: on a dense card the relaxed layout check would pass one added '.', the normal one does not
    dense, shuffled = "Let's see what the cards say", "What the cards say let's see."
    assert repair.rejecting_guard(dense, shuffled, "", 1.5, GL) == "fits_card"


def test_punctuation_alone_still_qualifies():
    assert repair.is_punct_case_only("we have to go", "We have to go.", GL, prev_text="")
    assert repair.is_punct_case_only("Let's eat Grandma", "Let's eat, Grandma", GL)  # documented limit: meaning is not judged


# ---- 2. slack of +2 characters ------------------------------------- ----


def test_an_already_bad_card_may_not_get_much_worse():
    """The reviewer's probe: a 70+ character card over cps becomes ~12 characters longer with '... !!! ...'."""
    probe_orig = "here and take everything we have been given by now so it goes on and on and on"
    assert len(probe_orig) > 70
    probe_new = "here, and take everything, we have been given by now, so it goes on, and on, and on."
    assert repair.is_punct_case_only(probe_orig, probe_new, GL)
    assert repair.rejecting_guard(probe_orig, probe_new, "", 2.0, GL) == "fits_card"


def test_up_to_two_added_characters_on_a_card_that_was_already_over_cps_pass():
    dense = "Let's see what the cards say"
    assert repair.rejecting_guard(dense, dense + ".", "", 1.5, GL) is None  # +1
    assert repair.rejecting_guard(dense, dense.replace("see", "see,") + ".", "", 1.5, GL) is None  # +2
    plus3 = dense.replace("see", "see,").replace("cards", "cards,") + "."
    assert repair.rejecting_guard(dense, plus3, "", 1.5, GL) == "fits_card"  # +3


# ---- 3. which case changes are lenient ----------------------------- ----


@pytest.mark.parametrize(
    "orig,new",
    [
        ("we have to go", "We have to go"),  # card start
        ("he left. we stayed", "he left. We stayed"),  # sentence start
        ("who is it? they ran", "who is it? They ran"),
        ("then i went home", "then I went home"),  # the pronoun
        ("i think i can", "I think I can"),
        ("it was ok", "it was OK"),
        ("we met kaido today", "we met Kaido today"),  # glossary spelling
        ("we met straw hat pirates", "we met Straw Hat Pirates"),
        ("tell monkey d. luffy", "tell Monkey D. Luffy"),
    ],
)
def test_lenient_case_changes(orig, new):
    assert repair.is_punct_case_only(orig, new, GL, prev_text="")
    assert repair.rejecting_guard(orig, new, "", 6.0, GL, prev_text="") is None


@pytest.mark.parametrize(
    "orig,new",
    [
        ("we are in the us now", "we are in the US now"),
        ("it happens in march", "it happens in March"),
        ("we ate turkey", "we ate Turkey"),
        ("we met zoro today", "we met Zoro today"),  # not in this glossary
        ("We Have To Go", "we have to go"),  # a lowered sentence start
        ("it was OK", "it was ok"),
        ("then I went", "then i went"),
        ("we met kaido today", "we met KAIDO today"),  # not the glossary's spelling
    ],
)
def test_other_case_changes_get_no_leniency(orig, new):
    assert not repair.is_punct_case_only(orig, new, GL, prev_text="")
    assert repair.rejecting_guard(orig, new, "", 6.0, GL, prev_text="") == "unchanged"


def test_a_case_change_with_other_punctuation_is_judged_per_token():
    assert not repair.is_punct_case_only("we are in the us. ok", "We are in the US. ok", GL, prev_text="")
    assert repair.is_punct_case_only("we are in the us ok", "We are in the us, ok.", GL, prev_text="")


# ---- 4. the threshold is not silently off -------------------------- ----


@pytest.mark.parametrize("raw", ["abc", "4.0", "-1", "2.5"])
def test_an_unusable_threshold_is_logged_once(monkeypatch, capsys, raw):
    monkeypatch.setattr(unresolved, "_WARNED_THRESHOLDS", set())
    monkeypatch.setenv("REPAIR_AUTO_DISMISS_WORDS", raw)
    assert unresolved.auto_dismiss_threshold() is None
    assert unresolved.auto_dismiss_threshold() is None
    out = capsys.readouterr().out
    assert out.count("REPAIR_AUTO_DISMISS_WORDS") == 1 and repr(raw) in out and "OFF" in out


@pytest.mark.parametrize("raw", ["", "  ", "0", "6"])
def test_a_usable_or_unset_threshold_logs_nothing(monkeypatch, capsys, raw):
    monkeypatch.setattr(unresolved, "_WARNED_THRESHOLDS", set())
    monkeypatch.setenv("REPAIR_AUTO_DISMISS_WORDS", raw)
    unresolved.auto_dismiss_threshold()
    assert capsys.readouterr().out == ""


def test_zero_still_means_any_word_change_dismisses(monkeypatch):
    monkeypatch.setenv("REPAIR_AUTO_DISMISS_WORDS", "0")
    assert unresolved.dismissal("a b", "a c")["dismissed"] == "large_change"
    assert unresolved.dismissal("a b", "A b.") == {}


# ---- hardening from the same review: only the three large-change rea ----


def test_a_dismissed_flag_cannot_hide_other_reasons(tmp_path, monkeypatch):
    stem = str(tmp_path / "ep")
    unresolved.record(stem, stage="repair", reason="decision_unfittable", original="a", proposed="b", dismissed="large_change")
    assert len(unresolved.pending(stem, primary_only=True)) == 1


def test_a_reorder_toward_glossary_spellings_is_still_a_change():
    gl = glossary.load_dict({"names": ["dog", "man"]})
    assert not repair.is_punct_case_only("the dog bit the man", "the man bit the dog", gl)
