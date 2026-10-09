"""Bare names stay bare in repair: a dub line that says only 'Momonosuke' keeps saying only that, a full name stays full.

Synthetic names; no network."""

import json

import pytest

import glossary
import repair

# The production shape (verify writes long forms into PHRASES; no real glossary has a multi-word NAME).
NAMES = ["Momonosuke", "Kouzuki", "Oden", "Zoro", "Nico", "Robin"]
PHRASES = ["Kouzuki Momonosuke", "Kozuki Oden", "Roronoa Zoro", "Nico Robin"]


def gl():
    return glossary.load_dict({"names": NAMES, "phrases": PHRASES})


@pytest.fixture
def keep(monkeypatch):
    monkeypatch.setenv("REPAIR_KEEP_NAME_PARTS", "1")


def accept(orig, new, ref=""):
    return repair.accept_repair(orig, new, ref, dur=6.0, gloss=gl())


# ---- the prompt ---------------


def test_the_prompt_tells_the_model_to_write_each_name_as_the_line_says_it():
    p = repair.build_prompt("asr line", "", gl())
    assert "exactly as the line says it" in p
    assert "given name or surname said alone stays alone" in p and "a full name stays full" in p
    assert "never add or remove a name part" in p


def test_the_instruction_sits_in_the_rules_before_the_asr_line():
    p = repair.build_prompt("asr line", "the official sub", gl())
    assert p.index("exactly as the line says it") < p.index("Return ONLY") < p.index("ASR line: asr line")
    assert p.endswith("ASR line: asr line\nCorrected line:")  # nothing trails the ASR line


# ---- the deterministic post-check ---------------


def test_a_bare_given_name_stays_bare(keep):
    assert not accept("Momonosuke is going to Wano.", "Kouzuki Momonosuke is going to Wano.")


def test_a_full_name_stays_full(keep):
    assert not accept("Kouzuki Momonosuke is going.", "Momonosuke is going.")


def test_a_surname_alone_stays_alone(keep):
    assert not accept("Kouzuki is very angry at the guards.", "Kouzuki Momonosuke is very angry at the guards.")


def test_a_bare_name_can_not_gain_a_part_even_with_a_reference_that_has_it(keep):
    assert not accept("Zoro is very angry at the guards.", "Roronoa Zoro is very angry at the guards.", "Roronoa Zoro is angry.")


@pytest.mark.parametrize(
    "orig,new",
    [
        ("Kojuki is very angry at the guards.", "Kouzuki is very angry at the guards."),  # a misheard surname
        ("Kojuki Momonosuke is here with us.", "Kouzuki Momonosuke is here with us."),  # one token of a full name
        ("Kouzuki Momonosuk is here with us.", "Kouzuki Momonosuke is here with us."),
        ("Odin is brave and he is strong.", "Oden is brave and he is strong."),
        ("Kozuki Odin is brave and strong.", "Kozuki Oden is brave and strong."),
        ("Roronoa Soro is brave and strong.", "Roronoa Zoro is brave and strong."),
    ],
)
def test_a_misheard_single_token_is_still_fixed(keep, orig, new):
    assert accept(orig, new)


def test_a_line_that_repeats_the_full_name_and_fixes_punctuation_is_fine(keep):
    assert accept("kouzuki momonosuke is here", "Kouzuki Momonosuke is here.")


def test_an_unrelated_edit_next_to_a_bare_name_is_fine(keep):
    assert accept("Momonosuke is going to wano now", "Momonosuke is going to Wano now.")


def test_the_check_is_off_unless_asked_so_the_default_ships_what_it_did_before(monkeypatch):
    """GUARD (passes on the old code): without REPAIR_KEEP_NAME_PARTS nothing changes."""
    monkeypatch.delenv("REPAIR_KEEP_NAME_PARTS", raising=False)
    assert accept("Momonosuke is going to Wano.", "Kouzuki Momonosuke is going to Wano.")


def test_the_check_is_exactly_the_helper(keep, monkeypatch):
    """Mutation guard: if the helper stops firing, the accept path accepts the bare->full rewrite again."""
    assert repair.changes_name_parts("Momonosuke is here", "Kouzuki Momonosuke is here", gl())
    monkeypatch.setattr(repair, "changes_name_parts", lambda *a: False)
    assert accept("Momonosuke is going to Wano.", "Kouzuki Momonosuke is going to Wano.")  # the mutated check lets it through


def test_changes_name_parts_reports_nothing_for_a_glossary_without_full_names():
    g = glossary.load_dict({"names": ["Momonosuke", "Zoro"]})
    assert not repair.changes_name_parts("Zoro is here", "Roronoa Zoro is here", g)


# ---- the summary ---------------------------------------------------------------------------------------------------------------


def _write_conf(conf_path, srt_path, segs):
    import test_repair

    test_repair._write_conf(conf_path, srt_path, segs)


def test_the_summary_counts_the_name_part_rejection_under_its_own_key(tmp_path, monkeypatch, keep):
    stem = str(tmp_path / "ep_parts")
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(
        conf_path,
        stem + repair.SRT_SUFFIX,
        [{"start": 0.0, "end": 6.0, "text": "Momonosuke is going to Wano.", "avg_logprob": -0.6, "no_speech_prob": 0.1}],
    )
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_parts.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl())
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 6.0, "Momonosuke is going to Wano.")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "Kouzuki Momonosuke is going to Wano.")
    recorded = []
    monkeypatch.setattr(repair.unresolved, "record", lambda stem, *a, **k: recorded.append(a))
    repair.process(conf_path)
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["rejected_name_part"] == 1 and summary["rejected_guard"] == 1 and summary["repaired"] == 0
    assert ("repair", "rejected_name_part") == recorded[0][:2]


def test_without_the_flag_the_summary_key_is_zero(tmp_path, monkeypatch):
    monkeypatch.delenv("REPAIR_KEEP_NAME_PARTS", raising=False)
    monkeypatch.setattr(repair, "KEEP_NAME_PARTS_DEFAULT", "0")
    stem = str(tmp_path / "ep_off")
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(
        conf_path,
        stem + repair.SRT_SUFFIX,
        [{"start": 0.0, "end": 6.0, "text": "Momonosuke is going to Wano.", "avg_logprob": -0.6, "no_speech_prob": 0.1}],
    )
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_off.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl())
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 6.0, "Momonosuke is going to Wano.")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "Kouzuki Momonosuke is going to Wano.")
    repair.process(conf_path)
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["rejected_name_part"] == 0 and summary["repaired"] == 1


def test_the_check_is_opt_in_until_a_live_measurement_exists(monkeypatch):
    monkeypatch.delenv("REPAIR_KEEP_NAME_PARTS", raising=False)
    assert repair.KEEP_NAME_PARTS_DEFAULT == "0"
    assert accept("Momonosuke is going to Wano.", "Kouzuki Momonosuke is going to Wano.")  # the default ships it
    monkeypatch.setenv("REPAIR_KEEP_NAME_PARTS", "1")
    assert not accept("Momonosuke is going to Wano.", "Kouzuki Momonosuke is going to Wano.")


# ---- review findings: phrases, grown replaces, possessives, unrelated names ----------------------------------------------------


def test_the_check_works_on_phrases_the_shape_verify_writes(keep):
    g = glossary.load_dict({"names": ["Momonosuke"], "phrases": ["Kouzuki Momonosuke"]})
    assert repair.changes_name_parts("Momonosuke is here", "Kouzuki Momonosuke is here", g)
    assert not repair.changes_name_parts(
        "Momonosuke is here", "Kouzuki Momonosuke is here", glossary.load_dict({"names": ["Momonosuke"]})
    )


def test_a_fixed_and_grown_name_is_refused(keep):
    assert repair.changes_name_parts("Zorro, behind you!", "Roronoa Zoro, behind you!", gl())
    assert repair.changes_name_parts("Kojuki is very angry today.", "Kouzuki Momonosuke is very angry today.", gl())
    assert not accept("Zorro, behind you, quickly!", "Roronoa Zoro, behind you, quickly!")


def test_a_respacing_that_is_not_a_new_name_part_is_not_refused(keep):
    g = glossary.load_dict({"names": ["Grand", "Line"], "phrases": ["Grand Line"]})
    assert not repair.changes_name_parts("the Grandline is wide", "the Grand Line is wide", g)


def test_a_same_length_replace_stays_unjudged(keep):
    assert not repair.changes_name_parts("Kojuki Momonosuke is here", "Kouzuki Momonosuke is here", gl())
    assert not repair.changes_name_parts("Odin is brave", "Oden is brave", gl())


def test_possessives_are_judged_like_the_name(keep):
    assert repair.changes_name_parts("Kouzuki Momonosuke's sword!", "Momonosuke's sword!", gl())
    assert repair.changes_name_parts("Momonosuke's sword is here!", "Kouzuki Momonosuke's sword is here!", gl())
    assert not repair.changes_name_parts("Kouzuki Momonosuke's sword!", "Kouzuki Momonosuke's sword.", gl())


def test_an_unrelated_full_name_with_no_kept_part_is_not_this_checks_business(keep):
    """Mutation guard for the kept-token requirement: inventing a name from nothing is invents_name's job."""
    assert not repair.changes_name_parts("I'm here.", "Nico Robin, I'm here.", gl())
    assert not repair.changes_name_parts("Nico Robin, I'm here.", "I'm here.", gl())


# ---- the prompt rule needs names to refer to ---------------


def test_a_prompt_without_a_glossary_has_no_name_rule():
    p = repair.build_prompt("asr line", "", glossary.load_dict({}))
    assert "exactly as the line says it" not in p and "reference spellings" not in p.split("Rules:")[1]


# ---- the reviewer can see and overrule a refusal ---------------


def test_a_name_part_refusal_is_in_the_review_queue_and_can_be_forced(tmp_path):
    import review_server
    import unresolved

    key = ("repair", "rejected_name_part")
    assert "rejected_name_part" in unresolved.REASONS["repair"] and key in unresolved.PRIMARY
    assert unresolved._EVIDENCE["rejected_name_part"] == unresolved._EVIDENCE["rejected_guard"]
    assert unresolved._CLI_VERDICT[key] == {"k": "reject", "f": "force"}
    assert review_server.OFFERED[key] == ("force", "reject", "correct")
    stem = str(tmp_path / "ep")
    unresolved.record(
        stem, "repair", "rejected_name_part", original_text="Momonosuke is here", proposed_text="Kouzuki Momonosuke is here"
    )
    assert [e["reason"] for e in unresolved.pending(stem, primary_only=True)] == ["rejected_name_part"]
