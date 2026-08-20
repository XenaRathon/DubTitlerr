"""Unit tests for mine_glossary.py's mine_text() (T19): the pure counting/tracking pass
over a block of subtitle plaintext that main() runs per-episode, before its own
COMMON-word + MIN_COUNT + already-known filtering of the accumulated results.

DIVERGENCE from specs/v1-polish/tasks.md T19 / spec.md Phase 4 ("word in the COMMON
deny-set -> ignored"): mine_text() itself does NOT consult COMMON at all -- it counts
and tracks every capitalized candidate word unconditionally. The COMMON exclusion is
applied downstream in main(): `t.lower() not in COMMON` (mine_glossary.py). The case
below documents mine_text()'s real (unfiltered) behavior for a COMMON word instead of
asserting the false claim that mine_text() ignores it.
"""
import json
import sys
import types

import pysubs2

import common
import mine_glossary


def test_mine_text():
    # 1. capitalized word mid-sentence -> counted + tracked in midsentence
    counter, poss, mid = {}, {}, set()
    mine_glossary.mine_text("I saw Luffy today.", counter, poss, mid)
    assert counter == {"Luffy": 1}
    assert poss == {}
    assert mid == {"Luffy"}

    # 2. capitalized word at sentence start -> counted, NOT tracked in midsentence
    counter, poss, mid = {}, {}, set()
    mine_glossary.mine_text("Zoro drew his blade.", counter, poss, mid)
    assert counter == {"Zoro": 1}
    assert mid == set()

    # 3. lowercase word -> ignored entirely (not counted, not tracked)
    counter, poss, mid = {}, {}, set()
    mine_glossary.mine_text("he saw luffy today", counter, poss, mid)
    assert counter == {}
    assert mid == set()

    # 4. word in the COMMON deny-set -> mine_text() does NOT filter it (see divergence
    #    note above); it's counted/tracked like any other capitalized candidate. The
    #    downstream `t.lower() not in COMMON` exclusion in main() is what actually drops it.
    assert "doctor" in mine_glossary.COMMON
    counter, poss, mid = {}, {}, set()
    mine_glossary.mine_text("I saw the Doctor again.", counter, poss, mid)
    assert counter == {"Doctor": 1}
    assert mid == {"Doctor"}

    # 5. word shorter than 3 chars -> ignored (the word-candidate regex itself requires
    #    >= 3 characters, before the capitalization check is even applied)
    counter, poss, mid = {}, {}, set()
    mine_glossary.mine_text("I saw Oz today", counter, poss, mid)
    assert counter == {}
    assert mid == set()


# --- V2 C8: COMMON loaded from data/common_proper_noun_deny.txt, inline fallback -------

def test_common_loads_from_data_file():
    """The real data/common_proper_noun_deny.txt (repo-relative, present in this
    checkout) reproduces the exact same set as the inline fallback."""
    loaded = mine_glossary._load_common("data/common_proper_noun_deny.txt")
    fallback = mine_glossary._load_common("data/does_not_exist.txt")
    assert loaded == fallback == set(mine_glossary._COMMON_FALLBACK)


def test_common_falls_back_when_data_file_missing():
    common = mine_glossary._load_common("data/nope_this_file_does_not_exist.txt")
    assert "doctor" in common and "luffy" not in common


def test_common_data_file_comments_and_blanks_are_skipped(tmp_path):
    f = tmp_path / "deny.txt"
    f.write_text("# a comment\n\nFoo\n  \nBAR\n")
    common = mine_glossary._load_common(str(f))
    assert common == {"foo", "bar"}


# --- context isolation: never mine our own previously-muxed dubtitle -----------
#
# mine_glossary has its OWN ffprobe subtitle selector (it does not go through
# common.eng_sub_streams), so the chokepoint fix in common.py does not reach it. Without
# the exclusion below, a regeneration would re-mine last version's spellings out of our
# own output and reinforce its mistakes into the glossary.

def _fake_subprocess(streams, monkeypatch):
    """Stub mine_glossary's subprocess: ffprobe answers with `streams`, ffmpeg writes a
    one-line .ass at the requested output path. Records every argv for assertions."""
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "ffprobe":
            return types.SimpleNamespace(stdout=json.dumps({"streams": streams}), returncode=0)
        sub = pysubs2.SSAFile()
        sub.events = [pysubs2.SSAEvent(start=0, end=1000, text="Luffy went to Alabasta.")]
        sub.save(cmd[-1])
        return types.SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(mine_glossary, "subprocess",
                        types.SimpleNamespace(run=run, DEVNULL=-3))
    return calls


def _stream(index, title=None, lang="eng", codec="ass"):
    tags = {"language": lang}
    if title is not None:
        tags["title"] = title
    return {"index": index, "codec_name": codec, "tags": tags}


def test_eng_sub_text_ffprobe_query_requests_the_title_tag(monkeypatch):
    calls = _fake_subprocess([], monkeypatch)
    mine_glossary.eng_sub_text("fake.mkv")
    entries = calls[0][calls[0].index("-show_entries") + 1]
    assert "title" in entries.split(":")[-1]


def test_eng_sub_text_skips_our_own_dubtitles_track(monkeypatch):
    """Two English tracks: the human fansub and our old output. The fansub must win."""
    calls = _fake_subprocess([_stream(2, title=common.TRACK_NAME),
                             _stream(3, title="English (Fansub)")], monkeypatch)
    assert "Luffy" in mine_glossary.eng_sub_text("fake.mkv")
    ffmpeg = [c for c in calls if c[0] == "ffmpeg"][0]
    assert ffmpeg[ffmpeg.index("-map") + 1] == "0:3"       # extracted the fansub, not ours


def test_eng_sub_text_mines_nothing_when_only_track_is_our_dubtitle(monkeypatch):
    """No fallback -- an episode whose only English sub is our old dubtitle contributes
    no glossary terms at all rather than re-mining itself."""
    calls = _fake_subprocess([_stream(2, title=common.TRACK_NAME)], monkeypatch)
    assert mine_glossary.eng_sub_text("fake.mkv") == ""
    assert not [c for c in calls if c[0] == "ffmpeg"]      # never even extracted it


def test_eng_sub_text_keeps_an_untitled_english_track(monkeypatch):
    _fake_subprocess([_stream(2)], monkeypatch)
    assert "Alabasta" in mine_glossary.eng_sub_text("fake.mkv")


# --- D5 (task 12): possessive folding, two admission lanes ---------------------
#
# `Brownbeard's` used to match nothing: the `^[A-Z][a-z]{3,}$` test ran against a core
# that still carried its `'s`, so the occurrence was counted as neither the possessive
# nor the base form and the evidence was discarded. Folding it back is only safe under a
# rule that lets possessive evidence REINFORCE a candidate but never ORIGINATE one --
# hence two counters and two admission lanes. No English-dictionary gate is added here:
# 13 of this show's 81 glossary names ARE dictionary words (Brook, Robin, Chopper,
# Crocodile, Buggy, Smoker, Shanks, Marco, Roger, ...), so a gate would make 16% of the
# cast permanently unmineable.

def test_fold_strips_an_ascii_possessive():
    assert mine_glossary._fold("Brownbeard's") == "Brownbeard"


def test_curly_apostrophe_possessive_folds_too():
    # chr(0x2019) is built, never typed: a literal curly apostrophe has been silently
    # normalised to ASCII in this repo's source before, disabling a guard while leaving
    # a test that still looked right.
    assert mine_glossary._fold("Brownbeard" + chr(0x2019) + "s") == "Brownbeard"


def test_fold_leaves_plain_and_internal_apostrophe_words_alone():
    assert mine_glossary._fold("Brownbeard") == "Brownbeard"
    assert mine_glossary._fold("Kin'emon") == "Kin'emon"
    assert mine_glossary._fold("D'Arby") == "D'Arby"
    assert mine_glossary._fold("Boss'") == "Boss'"          # bare trailing quote is not an 's fold


def test_internal_apostrophe_names_are_still_ignored_by_the_candidate_regex():
    """Unchanged from before D5: the capitalisation test rejects them, fold or no fold."""
    bare, poss, mid = {}, {}, set()
    mine_glossary.mine_text("I met Kin'emon and D'Arby, and also Kin'emon's brother.", bare, poss, mid)
    assert bare == {} and poss == {} and mid == set()


def test_mine_text_splits_bare_and_possessive_lanes():
    bare, poss, mid = {}, {}, set()
    mine_glossary.mine_text("I saw Brownbeard once.\nI saw Brownbeard's crew.\n"
                            "I saw Brownbeard" + chr(0x2019) + "s ship.", bare, poss, mid)
    assert bare == {"Brownbeard": 1}
    assert poss == {"Brownbeard": 2}
    assert mid == {"Brownbeard"}


def test_a_possessive_never_enters_the_midsentence_set():
    """The mid-sentence set is the capitalisation-ambiguity guard on the auto-append lane.
    Possessives stay out of it, so they cannot supply evidence the bare form lacks."""
    bare, poss, mid = {}, {}, set()
    mine_glossary.mine_text("I saw Vegapunk's lab.", bare, poss, mid)
    assert bare == {} and poss == {"Vegapunk": 1} and mid == set()


def test_possessives_may_not_push_a_weak_candidate_over_the_floor():
    text = "I told the Boss to wait.\nBoss's men arrived.\nBoss's ship moved."
    added, queue = mine_glossary.mine(text, min_count=3, common=set(), existing=set())
    assert "Boss" not in added
    assert queue["Boss"] == {"reason": "possessive_floor_crossing", "bare": 1, "possessive": 2}


def test_possessives_cannot_originate_through_the_midsentence_gate():
    """Bare count clears the floor but only sentence-initially. A mid-sentence POSSESSIVE
    must not supply the mid-sentence evidence the bare form never provided."""
    text = "Boss walked.\nBoss waited.\nBoss left.\nI saw Boss's ship."
    added, queue = mine_glossary.mine(text, min_count=3, common=set(), existing=set())
    assert added == [] and queue == {}


def test_possessives_reinforce_a_term_that_already_qualifies():
    # DIVERGENCE from the brief's fixture ("Brownbeard came." etc): every sentence there
    # puts the token FIRST, so mine_text never marks it mid-sentence and main()'s
    # long-standing `t in mid` gate drops it -- the test could not pass against a correct
    # implementation. Reworded so the token is genuinely mid-sentence; assertion unchanged.
    text = ("I saw Brownbeard come.\nI saw Brownbeard leave.\nI saw Brownbeard sing.\n"
            "I saw Brownbeard's crew flee.")
    added, queue = mine_glossary.mine(text, min_count=3, common=set(), existing=set())
    assert "Brownbeard" in added
    assert queue == {}                       # reinforcement, not a second lane entry


def test_reinforcing_possessives_are_counted_but_do_not_change_the_verdict():
    bare, poss, mid = {}, {}, set()
    mine_glossary.mine_text("I saw Vegapunk go.\nI saw Vegapunk again.\nI saw Vegapunk thrice.\n"
                            "I saw Vegapunk's lab.\nI saw Vegapunk's crew.", bare, poss, mid)
    assert bare == {"Vegapunk": 3} and poss == {"Vegapunk": 2}
    assert mine_glossary.admit(bare, poss, mid, 3, set(), set()) == (["Vegapunk"], {})


def test_a_dictionary_word_name_is_still_mineable():
    """Brook, Robin and Chopper are Straw Hats AND English words. No dictionary gate.
    (Fixture reworded from the brief for the same mid-sentence reason as above.)"""
    text = "I saw Brook play.\nI saw Brook laugh.\nI saw Brook sing."
    added, _ = mine_glossary.mine(text, min_count=3, common=set(), existing=set())
    assert "Brook" in added


def test_a_folded_contraction_is_still_caught_by_the_common_deny_list():
    bare, poss, mid = {}, {}, set()
    mine_glossary.mine_text("Oh, That's it. He's gone. It's over.", bare, poss, mid)
    assert bare == {} and poss == {"That": 1}      # He's/It's are too short to be candidates
    assert "that" in mine_glossary.COMMON          # ...and the fold target is denied downstream


def test_admit_skips_common_and_already_known_terms():
    bare, poss, mid = {"Doctor": 4, "Luffy": 4}, {}, {"Doctor", "Luffy"}
    assert mine_glossary.admit(bare, poss, mid, 3, {"doctor"}, {"luffy"}) == ([], {})


# --- main(): the crossing lane is persisted, never appended --------------------

def _run_main(tmp_path, text, monkeypatch, cfg=None):
    show = tmp_path / "Some Show"
    show.mkdir()
    (show / "E01.mkv").write_text("")
    gloss = tmp_path / "gloss"
    gloss.mkdir()
    gpath = gloss / "Some Show.json"
    if cfg is not None:
        gpath.write_text(json.dumps(cfg))
    monkeypatch.setattr(mine_glossary, "GLOSS_DIR", str(gloss))
    monkeypatch.setattr(mine_glossary, "MIN_COUNT", 3)
    monkeypatch.setattr(mine_glossary, "eng_sub_text", lambda p: text)
    monkeypatch.setattr(sys, "argv", ["mine_glossary.py", str(show)])
    mine_glossary.main()
    return json.loads(gpath.read_text()) if gpath.exists() else None


def test_main_queues_a_crossing_term_for_review_instead_of_appending_it(tmp_path, monkeypatch):
    out = _run_main(tmp_path, "I told the Boss to wait.\nBoss's men arrived.\nBoss's ship moved.",
                    monkeypatch)
    assert "Boss" not in out["names"]
    assert out["flagged"]["Boss"] == {"reason": "possessive_floor_crossing", "bare": 1, "possessive": 2}


def test_main_appends_a_term_that_qualifies_on_bare_count_alone(tmp_path, monkeypatch):
    out = _run_main(tmp_path, "I saw Brownbeard come.\nI saw Brownbeard leave.\n"
                              "I saw Brownbeard sing.\nI saw Brownbeard's crew flee.", monkeypatch)
    assert out["names"] == ["Brownbeard"]
    assert not out.get("flagged")


def test_main_never_clobbers_a_stronger_flagged_entry(tmp_path, monkeypatch):
    """The crossing lane is the weakest evidence in the file; it must not displace a
    reason glossary_verify/glossary_acquire already put in front of a human."""
    cfg = {"show": "Some Show", "names": [], "flagged": {"Boss": {"reason": "share-too-close"}}}
    out = _run_main(tmp_path, "I told the Boss to wait.\nBoss's men arrived.\nBoss's ship moved.",
                    monkeypatch, cfg=cfg)
    assert out["flagged"]["Boss"] == {"reason": "share-too-close"}
    assert "Boss" not in out["names"]


def test_mine_text_optionally_reports_the_surface_spellings(monkeypatch):
    """D3a: a consumer needs the forms behind a folded key, not just the count -- a review
    queue entry stripped of the evidence it escalated on cannot be reviewed."""
    bare, poss, mid, forms = {}, {}, set(), {}
    mine_glossary.mine_text("We fought Brownbeard here. The Brownbeard" + chr(0x2019) + "s crew fled. "
                 "I know Brownbeard's ship.", bare, poss, mid, forms)
    assert forms["Brownbeard"] == {"Brownbeard": 1, "Brownbeard" + chr(0x2019) + "s": 1,
                                   "Brownbeard's": 1}
    assert bare["Brownbeard"] == 1 and poss["Brownbeard"] == 2   # lanes unaffected by `forms`


def test_mine_text_forms_is_optional_and_changes_nothing():
    a = ({}, {}, set())
    b = ({}, {}, set())
    text = "We fought Brownbeard here. Brownbeard's crew fled."
    mine_glossary.mine_text(text, *a)
    mine_glossary.mine_text(text, *b, None)
    assert a == b
