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
import types

import pysubs2

import common
import mine_glossary


def test_mine_text():
    # 1. capitalized word mid-sentence -> counted + tracked in midsentence
    counter, mid = {}, set()
    mine_glossary.mine_text("I saw Luffy today.", counter, mid)
    assert counter == {"Luffy": 1}
    assert mid == {"Luffy"}

    # 2. capitalized word at sentence start -> counted, NOT tracked in midsentence
    counter, mid = {}, set()
    mine_glossary.mine_text("Zoro drew his blade.", counter, mid)
    assert counter == {"Zoro": 1}
    assert mid == set()

    # 3. lowercase word -> ignored entirely (not counted, not tracked)
    counter, mid = {}, set()
    mine_glossary.mine_text("he saw luffy today", counter, mid)
    assert counter == {}
    assert mid == set()

    # 4. word in the COMMON deny-set -> mine_text() does NOT filter it (see divergence
    #    note above); it's counted/tracked like any other capitalized candidate. The
    #    downstream `t.lower() not in COMMON` exclusion in main() is what actually drops it.
    assert "doctor" in mine_glossary.COMMON
    counter, mid = {}, set()
    mine_glossary.mine_text("I saw the Doctor again.", counter, mid)
    assert counter == {"Doctor": 1}
    assert mid == {"Doctor"}

    # 5. word shorter than 3 chars -> ignored (the word-candidate regex itself requires
    #    >= 3 characters, before the capitalization check is even applied)
    counter, mid = {}, set()
    mine_glossary.mine_text("I saw Oz today", counter, mid)
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
