"""Part A: a rejected repair that changed many words is recorded but dismissed from the queue (REPAIR_AUTO_DISMISS_WORDS).
Part B: which guard rejects a punctuation/case-only proposal, the 'guard' key, and REPAIR_ACCEPT_PUNCT_CASE_ONLY.

Synthetic lines only; the one word-count rule is unresolved.word_changes."""

import json

import pytest

import glossary
import punctuation
import repair
import unresolved

# ---- the one counter ----------------------------------------------- ----


@pytest.mark.parametrize(
    "a,b,n",
    [
        ("", "", 0),
        ("", "hello world", 2),
        ("hello", "", 1),
        ("kaido's business partner", "Kaido's business partner.", 0),  # case and punctuation only
        ("Hello, world", "hello world!", 0),
        ("Café au lait", "café au lait.", 0),  # accents are letters, not separators
        ("cafe", "café", 2),  # a respelling with an accent is a different word
        ("it's here", "it’s here", 0),  # curly and straight apostrophes are one
        ("everyone's", "everyones", 2),
        ("Mobydick is here", "Moby Dick is here", 3),  # a name split in two: one word dropped, two added
        ("100 days", "one hundred days", 3),
        ("a a b", "a b", 1),  # a multiset, not a set
        ("one two three", "three two one", 0),  # order is not counted
        ("Zoro, behind you!", "Roronoa Zoro, behind you!", 1),
        ("'quoted' word", "quoted word", 0),  # surrounding quote marks are punctuation
        ("...", "!!!", 0),
    ],
)
def test_word_changes(a, b, n):
    assert unresolved.word_changes(a, b) == n
    assert unresolved.word_changes(b, a) == n  # symmetric


def test_the_threshold_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("REPAIR_AUTO_DISMISS_WORDS", raising=False)
    assert unresolved.auto_dismiss_threshold() is None
    for raw, expect in (("6", 6), (" 4 ", 4), ("0", 0), ("", None), ("many", None), ("-1", None), ("2.5", None)):
        monkeypatch.setenv("REPAIR_AUTO_DISMISS_WORDS", raw)
        assert unresolved.auto_dismiss_threshold() == expect, raw


def test_dismissal_is_empty_when_off_or_not_over_the_threshold(monkeypatch):
    monkeypatch.delenv("REPAIR_AUTO_DISMISS_WORDS", raising=False)
    assert unresolved.dismissal("a b c", "x y z q r s t") == {}
    monkeypatch.setenv("REPAIR_AUTO_DISMISS_WORDS", "4")
    assert unresolved.dismissal("a b c", "a b d") == {}  # 2 changes
    assert unresolved.dismissal("a b c", "a b x y z") == {}  # exactly 4 is not over 4: "exceeds N"
    assert unresolved.dismissal("a b c", "x y z q") == {"dismissed": "large_change", "changes": 7}


# ---- the queue skips dismissed entries and can show them ----------- ----


def test_pending_primary_only_skips_dismissed_but_the_full_view_keeps_them(tmp_path):
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "rejected_guard", original_text="a", proposed_text="b")
    unresolved.record(
        stem, "repair", "rejected_guard", original_text="c", proposed_text="d e f g h", dismissed="large_change", changes=6
    )
    assert [e["original_text"] for e in unresolved.pending(stem, primary_only=True)] == ["a"]
    assert len(unresolved.pending(stem)) == 2  # the unfiltered walk (and the page's all-reasons toggle) still returns everything


def test_the_review_page_hides_dismissed_entries_in_its_default_view(tmp_path):
    import review_server

    stem = str(tmp_path / "ep")
    unresolved.record(
        stem, "repair", "rejected_guard", original_text="c", proposed_text="d e f g h", dismissed="large_change", changes=6
    )
    review_server._QUEUE_CACHE.clear()
    assert review_server.open_entries(stem) == []


def test_the_cli_hides_dismissed_entries_and_all_shows_them(tmp_path, capsys):
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "rejected_guard", original_text="keep me", proposed_text="x")
    unresolved.record(
        stem,
        "repair",
        "rejected_guard",
        original_text="hide me",
        proposed_text="p q r s t u",
        dismissed="large_change",
        changes=7,
    )
    unresolved.main([stem])
    shown = capsys.readouterr().out
    assert "keep me" in shown and "hide me" not in shown and "1 dismissed" in shown and "--all" in shown
    unresolved.main([stem, "--all"])
    assert "hide me" in capsys.readouterr().out


def test_without_dismissed_entries_the_cli_output_is_unchanged(tmp_path, capsys):
    """GUARD (passes on the old code): no summary line when nothing was dismissed."""
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "rejected_guard", original_text="keep me", proposed_text="x")
    unresolved.main([stem])
    assert "dismissed" not in capsys.readouterr().out


# ---- recording in repair.process and punctuation.restore ----------- ----


def _write_conf(path, srt, segs):
    import test_repair

    test_repair._write_conf(path, srt, segs)


def _episode(tmp_path, monkeypatch, original, proposal, gloss=None):
    stem = str(tmp_path / "ep")
    conf = stem + repair.CONF_SUFFIX
    _write_conf(
        conf, stem + repair.SRT_SUFFIX, [{"start": 0.0, "end": 6.0, "text": original, "avg_logprob": -0.6, "no_speech_prob": 0.1}]
    )
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gloss or glossary.load_dict({}))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 6.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: proposal)
    repair.process(conf)
    return stem, json.load(open(stem + ".dubtitles.repair-summary.json"))


BIG = "the old line has few words"  # 6 words
HUGE = "a completely different sentence that adds many brand new words to the card here"  # length ratio > 1.5


def test_by_default_nothing_is_dismissed_and_the_summary_has_no_new_key(tmp_path, monkeypatch):
    """GUARD (passes on the old code)."""
    monkeypatch.delenv("REPAIR_AUTO_DISMISS_WORDS", raising=False)
    stem, summary = _episode(tmp_path, monkeypatch, BIG, HUGE)
    (entry,) = unresolved.items(stem)
    assert entry["reason"] == "rejected_guard" and "dismissed" not in entry and "dismissed_large_change" not in summary


def test_a_large_change_is_recorded_dismissed_and_counted(tmp_path, monkeypatch):
    monkeypatch.setenv("REPAIR_AUTO_DISMISS_WORDS", "6")
    stem, summary = _episode(tmp_path, monkeypatch, BIG, HUGE)
    (entry,) = unresolved.items(stem)  # still in the sidecar: the audit trail
    assert entry["proposed_text"] == HUGE and entry["dismissed"] == "large_change" and entry["changes"] > 6
    assert summary["dismissed_large_change"] == 1 and summary["rejected_guard"] == 1
    assert unresolved.pending(stem, primary_only=True) == []


def test_a_small_change_is_still_queued(tmp_path, monkeypatch):
    monkeypatch.setenv("REPAIR_AUTO_DISMISS_WORDS", "6")
    stem, summary = _episode(tmp_path, monkeypatch, "the old line", "the old line is here now")  # ratio too big
    (entry,) = unresolved.items(stem)
    assert "dismissed" not in entry and summary["dismissed_large_change"] == 0
    assert len(unresolved.pending(stem, primary_only=True)) == 1


def test_a_name_invented_rejection_is_dismissed_too(tmp_path, monkeypatch):
    monkeypatch.setenv("REPAIR_AUTO_DISMISS_WORDS", "2")
    gl = glossary.load_dict({"names": ["Zoro"]})
    stem, _ = _episode(tmp_path, monkeypatch, "I saw Zoro today", "I saw Dester Qorgan Vexil today", gl)
    (entry,) = unresolved.items(stem)
    assert entry["reason"] == "rejected_name_invented" and entry["dismissed"] == "large_change"


def test_a_punctuation_rejection_is_dismissed_with_the_same_rule(monkeypatch, tmp_path):
    monkeypatch.setenv("REPAIR_AUTO_DISMISS_WORDS", "3")
    words, segments = [], []
    import test_punctuation

    words, segments = test_punctuation._words(["we have to go", "it is dangerous"])
    test_punctuation._stub(monkeypatch, "We shall now leave. It is really very dangerous indeed.")
    stem = str(tmp_path / "ep")
    punctuation.restore(words, segments, None, stem)
    (entry,) = [e for e in unresolved.items(stem) if e["reason"] == "rejected_guard"]
    assert entry["stage"] == "punctuation" and entry["dismissed"] == "large_change"


def test_a_human_verdict_on_a_dismissed_pair_still_applies(monkeypatch):
    """Verdicts are keyed on (original, proposal): the dismissal marker is not part of the key."""
    import decisions

    monkeypatch.setenv("REPAIR_AUTO_DISMISS_WORDS", "2")
    store = decisions.record({}, BIG, HUGE, "force")
    assert unresolved.dismissal(BIG, HUGE)["dismissed"] == "large_change"
    assert decisions.lookup(store, BIG, HUGE)["verdict"] == "force"


# =====================================================================================
# Part B: punctuation / case-only proposals
# =====================================================================================

DENSE = "Let's see what the cards say"  # 28 chars: over 17 cps on a 1.5 s card, under it on a 1.7 s card
GL = glossary.load_dict({"names": ["Kaido"]})


def test_the_guard_that_rejects_a_punctuation_only_proposal_on_a_dense_card_is_fits_card(monkeypatch):
    """Evidence: an already-over-cps card may not get worse in ANY dimension, and one added '.' is one more visible character."""
    monkeypatch.delenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", raising=False)
    assert unresolved.word_changes(DENSE, DENSE + ".") == 0
    assert repair.rejecting_guard(DENSE, DENSE + ".", "", 1.5, GL) == "fits_card"
    assert not repair.accept_repair(DENSE, DENSE + ".", "", 1.5, GL)
    assert repair.rejecting_guard(DENSE, DENSE + ".", "", 6.0, GL) is None  # the same edit on a roomy card is fine


def test_a_case_only_proposal_is_rejected_as_nothing_changed(monkeypatch):
    monkeypatch.delenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", raising=False)
    assert repair.rejecting_guard("kaido's business", "Kaido's business", "", 6.0, GL) == "unchanged"


@pytest.mark.parametrize(
    "orig,new,ref,dur,gl,guard",
    [
        ("I saw Zoro today", "I saw Dester Qorgan Vexil today", "", 6.0, glossary.load_dict({"names": ["Zoro"]}), "invents_name"),
        ("the old line", "the old line is here now", "", 6.0, GL, "length_ratio"),
        ("same line", "same line", "", 6.0, GL, "unchanged"),
        ("", "", "", 6.0, GL, "empty"),
    ],
)
def test_rejecting_guard_names_the_guard(monkeypatch, orig, new, ref, dur, gl, guard):
    assert repair.rejecting_guard(orig, new, ref, dur, gl) == guard


def test_accept_repair_is_exactly_the_guard_being_none(monkeypatch):
    monkeypatch.delenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", raising=False)
    for orig, new, dur in (("a b", "a b c d e f g", 6.0), (DENSE, DENSE + ".", 1.5), (DENSE, DENSE + ".", 6.0), ("x", "y", 6.0)):
        assert repair.accept_repair(orig, new, "", dur, GL) is (repair.rejecting_guard(orig, new, "", dur, GL) is None)


def test_the_rejected_entry_records_the_guard_that_fired(tmp_path, monkeypatch):
    monkeypatch.delenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", raising=False)
    stem, _ = _episode(tmp_path, monkeypatch, BIG, HUGE)
    (entry,) = unresolved.items(stem)
    assert entry["guard"] == "length_ratio"


def test_with_the_flag_a_punctuation_only_proposal_passes_on_a_dense_card(monkeypatch):
    monkeypatch.setenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", "1")
    assert (
        repair.rejecting_guard(DENSE, DENSE + ".", "", 1.5, GL) is None
    )  # no NEW kind of layout fault: over_cps was already there


def test_with_the_flag_a_proposal_that_creates_a_new_fault_is_still_rejected(monkeypatch):
    monkeypatch.setenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", "1")
    # 28 chars on 1.7 s is 16.5 cps (fine); one more character is 17.06 (over): a fault the card did not have
    assert repair.rejecting_guard(DENSE, DENSE + ".", "", 1.7, GL) == "fits_card"


def test_with_the_flag_a_case_only_proposal_is_accepted(monkeypatch):
    monkeypatch.setenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", "1")
    assert repair.rejecting_guard("kaido's business", "Kaido's business", "", 6.0, GL) is None
    assert repair.rejecting_guard("same line", "same line", "", 6.0, GL) == "unchanged"  # identical is still nothing


def test_with_the_flag_a_proposal_that_also_changes_words_gets_no_leniency(monkeypatch):
    monkeypatch.setenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", "1")
    assert repair.rejecting_guard(DENSE, "Let's see what the cards say now.", "", 1.5, GL) == "fits_card"


def test_the_other_guards_still_apply_to_a_punctuation_only_proposal(monkeypatch):
    monkeypatch.setenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", "1")
    # a flood of punctuation changes no word but is still an unreasonable edit: the length band applies
    assert repair.rejecting_guard("go now", "go, now!!!!!!!!!!!!!!!!!!!!", "", 6.0, GL) == "length_ratio"


def test_the_summary_counts_the_newly_accepted_proposals_only_when_the_flag_is_on(tmp_path, monkeypatch):
    def run(name):
        sub = tmp_path / name
        sub.mkdir()
        stem = str(sub / "ep")
        conf = stem + repair.CONF_SUFFIX
        _write_conf(
            conf,
            stem + repair.SRT_SUFFIX,
            [{"start": 0.0, "end": 1.5, "text": DENSE, "avg_logprob": -0.6, "no_speech_prob": 0.1}],
        )
        monkeypatch.setattr(repair, "find_video", lambda s: str(sub / "ep.mkv"))
        monkeypatch.setattr(repair, "glossary_for", lambda video: glossary.load_dict({}))
        monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.5, "the official sub")])
        monkeypatch.setattr(repair, "llm", lambda prompt, model=None: DENSE + ".")
        repair.process(conf)
        return json.load(open(stem + ".dubtitles.repair-summary.json"))

    monkeypatch.delenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", raising=False)
    off = run("off")
    assert "accepted_punct_case_only" not in off and off["repaired"] == 0 and off["rejected_guard"] == 1
    monkeypatch.setenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", "1")
    on = run("on")
    assert on["accepted_punct_case_only"] == 1 and on["repaired"] == 1 and on["rejected_guard"] == 0


def test_a_punctuation_only_repair_the_guards_would_have_admitted_anyway_is_not_counted(tmp_path, monkeypatch):
    """The counter is for proposals the flag rescued: on a roomy card the same edit passes without it."""
    monkeypatch.setenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", "1")
    stem = str(tmp_path / "ep")
    conf = stem + repair.CONF_SUFFIX
    _write_conf(
        conf, stem + repair.SRT_SUFFIX, [{"start": 0.0, "end": 6.0, "text": DENSE, "avg_logprob": -0.6, "no_speech_prob": 0.1}]
    )
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: glossary.load_dict({}))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 6.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: DENSE + ".")
    repair.process(conf)
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["repaired"] == 1 and summary["accepted_punct_case_only"] == 0
