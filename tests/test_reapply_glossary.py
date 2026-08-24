"""Checks for tools/reapply_glossary.py -- the card-text re-correction path.

This tool is the pipeline's only way to fix what a caption SAYS without re-running
the GPU, and it mutates finished output: it rewrites conf.json, re-renders the srt,
and deletes the .dubtitles.done stamp so merge_pass re-muxes. The tests below pin
the three properties that make that safe -- a dry run writes nothing, the stamp is
dropped only after the sidecar is on disk, and an unreadable conf is reported rather
than crashing the sweep.
"""

import json
import os

import common
from tools import reapply_glossary as rg

GLOSS = {"show": "Test", "names": ["Haki"], "hard_fixes": {"hockey": "Haki"}}


def _episode(tmp_path, cards, *, with_stamp=True):
    """Lay out <show>/<Season 01>/<episode> the way glossary_for() expects, since it
    derives the show from the episode's GRANDPARENT directory."""
    season = tmp_path / "Test" / "Season 01"
    season.mkdir(parents=True)
    stem = str(season / "Test - S01E01")
    with open(stem + rg.CONF_SUFFIX, "w") as f:
        json.dump(cards, f)
    if with_stamp:
        with open(stem + rg.STAMP_SUFFIX, "w") as f:
            json.dump({"muxed": True, "version": 4}, f)
    gdir = tmp_path / "glossaries"
    gdir.mkdir()
    with open(gdir / "Test.json", "w") as f:
        json.dump(GLOSS, f)
    return stem, str(gdir)


def test_a_dry_run_changes_nothing_on_disk(tmp_path, monkeypatch):
    """The default is a dry run. If it ever writes, an operator inspecting the
    proposed diff would silently mutate finished episodes."""
    stem, gdir = _episode(tmp_path, [{"text": "He used hockey", "start": 0.0, "end": 1.0}])
    monkeypatch.setattr(rg, "GLOSSARY_DIR", gdir)
    before = open(stem + rg.CONF_SUFFIX).read()

    res = rg.process(stem + rg.CONF_SUFFIX, apply=False, samples=[])

    assert res["changed"] == 1, "fixture proves nothing if the correction did not fire"
    assert open(stem + rg.CONF_SUFFIX).read() == before
    assert not os.path.exists(stem + rg.SRT_SUFFIX)
    assert os.path.exists(stem + rg.STAMP_SUFFIX), "dry run must not re-open the episode"


def test_apply_writes_the_sidecar_before_dropping_the_stamp(tmp_path, monkeypatch):
    """mux treats a valid stamp as its only skip guard. Dropping it before the srt
    exists would leave a window with neither a stamp nor corrected output."""
    stem, gdir = _episode(tmp_path, [{"text": "He used hockey", "start": 0.0, "end": 1.0}])
    monkeypatch.setattr(rg, "GLOSSARY_DIR", gdir)

    res = rg.process(stem + rg.CONF_SUFFIX, apply=True, samples=[])

    assert res["stamp_dropped"] is True
    assert not os.path.exists(stem + rg.STAMP_SUFFIX)
    assert os.path.exists(stem + rg.SRT_SUFFIX), "stamp dropped without output to replace it"
    assert json.load(open(stem + rg.CONF_SUFFIX))[0]["text"] == "He used Haki"


def test_an_unchanged_episode_is_left_completely_alone(tmp_path, monkeypatch):
    """No edits must mean no rewrite and no stamp drop -- otherwise every sweep
    re-muxes the whole library for nothing."""
    stem, gdir = _episode(tmp_path, [{"text": "Nothing to fix", "start": 0.0, "end": 1.0}])
    monkeypatch.setattr(rg, "GLOSSARY_DIR", gdir)

    res = rg.process(stem + rg.CONF_SUFFIX, apply=True, samples=[])

    assert res["changed"] == 0
    assert os.path.exists(stem + rg.STAMP_SUFFIX)
    assert not os.path.exists(stem + rg.SRT_SUFFIX)


def test_an_unreadable_conf_is_reported_not_raised(tmp_path, monkeypatch):
    """One corrupt sidecar must not abort a sweep over hundreds of episodes."""
    stem, gdir = _episode(tmp_path, [{"text": "x", "start": 0.0, "end": 1.0}])
    monkeypatch.setattr(rg, "GLOSSARY_DIR", gdir)
    with open(stem + rg.CONF_SUFFIX, "w") as f:
        f.write("{not json")

    res = rg.process(stem + rg.CONF_SUFFIX, apply=True, samples=[])

    assert "error" in res
    assert os.path.exists(stem + rg.STAMP_SUFFIX), "a crash path must not drop the stamp"


def test_render_srt_matches_the_shape_generate_writes(tmp_path):
    """The srt is consumed by mux; a format drift here is invisible until playback."""
    out = rg.render_srt([{"text": "One", "start": 0.0, "end": 1.5}, {"text": "Two", "start": 2.0, "end": 3.0}])
    assert out.startswith("1\n00:00:00,000 --> 00:00:01,500\nOne\n\n")
    assert "2\n00:00:02,000 --> 00:00:03,000\nTwo\n\n" in out


def test_find_confs_walks_a_directory_and_sorts(tmp_path):
    stem, _ = _episode(tmp_path, [{"text": "x", "start": 0.0, "end": 1.0}])
    found = rg.find_confs(str(tmp_path))
    assert found == [stem + rg.CONF_SUFFIX]


# --- tier classification (spec v5-two-tier-idempotency, S-3) -------------------


def _episode_with_words(tmp_path, cards, stored_prompt, gloss):
    """An episode carrying both a conf.json and a words.json, laid out so
    glossary_for()/show_for() derive the show from the grandparent directory the way
    gen_loop.sh's SHOW_NAME="$show" does."""
    season = tmp_path / "One Pace" / "Season 01"
    season.mkdir(parents=True)
    stem = str(season / "One Pace - S01E01")
    with open(stem + rg.CONF_SUFFIX, "w") as f:
        json.dump(cards, f)
    with open(stem + common.WORDS_SUFFIX, "w") as f:
        json.dump(
            {
                "schema_version": common.WORDS_SCHEMA_VERSION,
                "transcribe_version": common.TRANSCRIBE_VERSION,
                "initial_prompt": stored_prompt,
                "audio_duration": 10.0,
                "segments": [],
                "words": [{"text": "x", "start": 0.0, "end": 1.0, "prob": 1.0, "seg": 0}],
            },
            f,
        )
    gdir = tmp_path / "glossaries"
    gdir.mkdir()
    with open(gdir / "One Pace.json", "w") as f:
        json.dump(gloss, f)
    return stem, str(gdir)


def test_show_for_matches_the_name_gen_loop_uses(tmp_path):
    """gen_loop.sh runs generate with SHOW_NAME="$show", the show DIRECTORY name. If this
    derived a different string, prompt_for() would produce a different prompt here than
    the one whisper actually got, and every episode would read as transcription-stale
    forever -- a permanent silent GPU queue."""
    season = tmp_path / "One Pace" / "Season 01"
    season.mkdir(parents=True)
    assert rg.show_for(str(season / "One Pace - S01E01")) == "One Pace"


def test_a_hard_fixes_only_edit_flags_nothing_for_the_gpu(tmp_path, monkeypatch):
    """The count is asserted, not just the flag: mine_glossary appends hard_fixes on every
    sweep, so a file-hash design would re-queue a whole series for work that changed
    nothing about audio -> words."""
    import glossary as g

    gloss = {"show": "One Pace", "hard_fixes": {"hockey": "Haki"}}
    prompt = g.prompt_for(g.load_dict({"show": "One Pace"}))
    stem, gdir = _episode_with_words(tmp_path, [{"text": "He used hockey", "start": 0.0, "end": 1.0}], prompt, gloss)
    monkeypatch.setattr(rg, "GLOSSARY_DIR", gdir)

    res = rg.process(stem + rg.CONF_SUFFIX, apply=True, samples=[])

    assert res["tier"] is None, "a hard_fixes edit must not reach the GPU"
    assert res["changed"] == 1, "but the correction must still be applied"
    assert json.load(open(stem + rg.CONF_SUFFIX))[0]["text"] == "He used Haki"


def test_a_prompt_changing_edit_is_flagged_transcription_stale(tmp_path, monkeypatch):
    """The correction is still applied -- it is cheap and it improves the output -- but
    the episode is ALSO reported as needing the decoder, rather than a partial text fix
    quietly hiding that its transcript is out of date."""
    gloss = {"show": "One Pace", "initial_prompt": "Luffy, Zoro, Nami", "hard_fixes": {"hockey": "Haki"}}
    stem, gdir = _episode_with_words(tmp_path, [{"text": "He used hockey", "start": 0.0, "end": 1.0}], "Luffy, Zoro", gloss)
    monkeypatch.setattr(rg, "GLOSSARY_DIR", gdir)

    res = rg.process(stem + rg.CONF_SUFFIX, apply=True, samples=[])

    assert res["tier"] == "transcribe"
    assert res["changed"] == 1


def test_an_episode_with_no_words_sidecar_is_transcription_stale(tmp_path, monkeypatch):
    """All 813 stamped episodes are in this state until they are next transcribed. No
    stored prompt is no evidence the transcript matches this glossary."""
    stem, gdir = _episode(tmp_path, [{"text": "He used hockey", "start": 0.0, "end": 1.0}])
    monkeypatch.setattr(rg, "GLOSSARY_DIR", gdir)

    res = rg.process(stem + rg.CONF_SUFFIX, apply=True, samples=[])

    assert res["tier"] == "transcribe"


def test_a_dry_run_still_reports_the_tier(tmp_path, monkeypatch):
    """Classification is a read; it must not require --apply to tell you what is stale."""
    gloss = {"show": "One Pace", "initial_prompt": "changed"}
    stem, gdir = _episode_with_words(tmp_path, [{"text": "x", "start": 0.0, "end": 1.0}], "original", gloss)
    monkeypatch.setattr(rg, "GLOSSARY_DIR", gdir)

    assert rg.process(stem + rg.CONF_SUFFIX, apply=False, samples=[])["tier"] == "transcribe"
