"""Phase 24: the card-initial capital reaches the gate through repair.process; the glossary case rule fails closed without a word
list; REPAIR_GUARD_TERMINAL_PUNCT=1 refuses a proposal that adds or removes a terminal '?', swaps '!' and '?', or converts a
trailing ellipsis to or from '.'/'!'. Synthetic lines only."""

import json

import pytest

import glossary
import repair
import unresolved

GL = glossary.load_dict({"names": ["Luffy", "Rain"]})


def run_episode(tmp_path, monkeypatch, cards, answers, name="ep", dur=6.0):
    """repair.process over ``cards`` (each ``dur`` s); the LLM answers ``answers`` in order: (summary, unresolved items)."""
    sub = tmp_path / name
    sub.mkdir()
    stem = str(sub / "ep")
    conf = [
        {"start": k * dur, "end": (k + 1) * dur, "text": t, "avg_logprob": -0.6, "no_speech_prob": 0.1}
        for k, t in enumerate(cards)
    ]
    open(stem + repair.SRT_SUFFIX, "w").close()
    json.dump(conf, open(stem + repair.CONF_SUFFIX, "w"))
    monkeypatch.setattr(repair, "find_video", lambda s: str(sub / "ep.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: glossary.load_dict({}))
    monkeypatch.setattr(
        repair, "dialogue_intervals", lambda video: [(k * dur, (k + 1) * dur, "the official sub") for k in range(len(cards))]
    )
    it = iter(answers)
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: next(it))
    repair.process(stem + repair.CONF_SUFFIX)
    return json.load(open(stem + ".dubtitles.repair-summary.json")), unresolved.items(stem)


# ---- 1. prev_text reaches the gate in production ----


def test_a_card_initial_capital_ships_after_a_finished_previous_card(tmp_path, monkeypatch):
    monkeypatch.setenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", "1")
    summary, _ = run_episode(tmp_path, monkeypatch, ["He arrived.", "and then he left"], ["He arrived.", "And then he left"])
    assert summary["repaired"] == 1 and summary["rejected_guard"] == 0


def test_the_capital_does_not_ship_after_an_unfinished_previous_card(tmp_path, monkeypatch):
    monkeypatch.setenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", "1")
    summary, items = run_episode(
        tmp_path, monkeypatch, ["He was saying", "and then he left"], ["He was saying", "And then he left"]
    )
    # a case-only proposal is "unchanged" to the ordinary guards: nothing ships, and there is nothing to queue
    assert summary["repaired"] == 0


# ---- 2. the case rule fails closed without a word list ----


def test_a_missing_word_list_gives_no_glossary_case_leniency(monkeypatch):
    monkeypatch.setattr(glossary, "_ORDINARY", set())  # an empty list would call 'rain' a name
    monkeypatch.setattr(glossary, "_ORDINARY_STATUS", "ok")
    assert repair.is_punct_case_only("we need rain", "we need Rain", GL, prev_text="")  # control: a real list says it is a name
    monkeypatch.setattr(glossary, "_ORDINARY_STATUS", "missing")
    assert not repair.is_punct_case_only("we need rain", "we need Rain", GL, prev_text="")
    assert not repair.is_punct_case_only("we met luffy", "we met Luffy", GL, prev_text="")
    # whole multi-word entries and the other lenient cases do not depend on the list
    gl2 = glossary.load_dict({"names": ["Devil Fruit"]})
    assert repair.is_punct_case_only("a devil fruit", "a Devil Fruit", gl2, prev_text="")
    assert repair.is_punct_case_only("then i went", "then I went", gl2, prev_text="")


def test_an_unreadable_word_list_path_fails_closed(monkeypatch):
    monkeypatch.setattr(glossary, "_ORDINARY", None)
    monkeypatch.setattr(glossary, "_ORDINARY_STATUS", None)  # restored afterwards: ordinary_words() sets both
    monkeypatch.setattr(glossary, "WORDLIST_PATH", "/nonexistent/words")
    assert glossary.wordlist_status() == "missing"
    assert not repair.is_punct_case_only("we need rain", "we need Rain", GL, prev_text="")


# ---- 3. REPAIR_GUARD_TERMINAL_PUNCT ----

REFUSED = [
    ("Don't laugh at me?", "Don't laugh at me!"),
    ("Damn...", "Damn!"),
    ("Damn…", "Damn."),
    ("Damn!", "Damn..."),
    ("Damn.", "Damn…"),
    ("It was the gravesite?", "It was the gravesite."),
    ("coming for us any time now?", "coming for us any time now."),
    ("He left.", "He left?"),
    ("Are you ok", "Are you ok?"),
    ("Stop!", "Stop?"),
    ("Stop?", "Stop!"),
    ('"Really?"', '"Really."'),
]
PASSING = [
    ("He'd funneled dirty money here whenever he could,", "He'd funneled dirty money here whenever he could."),
    ("Hey, Sanji! Do these things fry up okay?", "Hey, Sanji, do these things fry up okay?"),
    ("What's that thing?!", "What's that thing?"),
    ("They're freshwater fish.", "They're freshwater fish!"),
    ("One dream,", "One dream."),
    ("Damn", "Damn."),
    ("Damn...", "Damn"),  # an ellipsis dropped, not converted: out of scope
    ("Damn", "Damn..."),
    ("Wait... what is it", "Wait... what is it."),
    ("Nice job! You, damn fool.", "Nice job, you damn fool!"),
]


@pytest.mark.parametrize("orig,new", REFUSED)
def test_with_the_flag_a_terminal_question_or_ellipsis_change_is_refused(monkeypatch, orig, new):
    monkeypatch.setenv("REPAIR_GUARD_TERMINAL_PUNCT", "1")
    assert repair.rejecting_guard(orig, new, "", 6.0, GL) == "terminal_punct"
    assert not repair.accept_repair(orig, new, "", 6.0, GL)


@pytest.mark.parametrize("orig,new", REFUSED)
def test_by_default_the_same_proposals_are_judged_by_the_ordinary_guards_only(monkeypatch, orig, new):
    """GUARD (passes on the old code): the flag is off by default and changes nothing."""
    monkeypatch.delenv("REPAIR_GUARD_TERMINAL_PUNCT", raising=False)
    assert repair.rejecting_guard(orig, new, "", 6.0, GL) != "terminal_punct"


@pytest.mark.parametrize("orig,new", PASSING)
def test_benign_punctuation_changes_still_pass_with_the_flag(monkeypatch, orig, new):
    monkeypatch.setenv("REPAIR_GUARD_TERMINAL_PUNCT", "1")
    assert repair.rejecting_guard(orig, new, "", 6.0, GL) != "terminal_punct"


def test_terminal_punctuation_is_read_past_closing_quotes_and_spaces():
    assert repair.terminal_punct_changed('"Really?" ', '"Really." ')
    assert not repair.terminal_punct_changed("Is it? Yes.", "Is it, yes.")  # a mid-line '?' is not terminal


def test_the_summary_counts_the_refusals_only_when_the_flag_is_on(tmp_path, monkeypatch):
    monkeypatch.delenv("REPAIR_GUARD_TERMINAL_PUNCT", raising=False)
    off, off_items = run_episode(tmp_path, monkeypatch, ["Don't laugh at me?"], ["Don't laugh at me!"], name="off")
    assert "rejected_terminal_punct" not in off and off["repaired"] == 1  # shipped by the ordinary guards
    monkeypatch.setenv("REPAIR_GUARD_TERMINAL_PUNCT", "1")
    on, on_items = run_episode(tmp_path, monkeypatch, ["Don't laugh at me?"], ["Don't laugh at me!"], name="on")
    assert on["rejected_terminal_punct"] == 1 and on["repaired"] == 0 and on["rejected_guard"] == 1
    assert [e["guard"] for e in on_items] == ["terminal_punct"]
