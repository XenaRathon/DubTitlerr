"""Targeted re-open for a MERGE-STAGE fix (the 166e88d song-span drop).

The state this targets is the one mux.py leaves behind: conf.json + a stamp, NO sidecar.
Nothing in the pipeline re-derives the signs/song merge for such an episode, so a fix to
dub_signs_merge reaches only work done after it. These tests pin the three things that
make the re-open safe: the sidecar exists before the stamp is dropped, the stale .ass is
gone so the merge actually re-runs, and an already-open episode is left alone."""

import json
import os

from tools import reopen_for_signs as rfs

CONF = ".dubtitles.conf.json"
SRT = ".eng.dubtitles.srt"
ASS = ".eng.dubtitles.ass"
STAMP = ".dubtitles.done"


def _muxed(tmp_path, name, ass=False):
    """An episode as mux.py leaves it: conf.json and a stamp, no sidecar."""
    stem = str(tmp_path / name)
    with open(stem + CONF, "w") as f:
        json.dump([{"start": 0.0, "end": 2.0, "text": "I saw Spandam"}], f)
    with open(stem + STAMP, "w") as f:
        json.dump({"muxed": True, "version": 8}, f)
    if ass:
        with open(stem + ASS, "w") as f:
            f.write("[Events]\nDialogue: 0,0:00:00.00,0:00:02.00,Dubtitles,,0,0,0,,old signs decisions\n")
    return stem


def test_a_muxed_episode_gets_a_sidecar_and_loses_its_stamp(tmp_path):
    stem = _muxed(tmp_path, "ep_a")

    assert rfs.main([str(tmp_path), "--apply"]) == 0

    assert os.path.exists(stem + SRT), "no sidecar means merge_pass.sh never sees the episode"
    assert not os.path.exists(stem + STAMP), "the stamp is mux's only skip guard"
    assert "I saw Spandam" in open(stem + SRT).read()


def test_a_stale_ass_is_removed_so_the_merge_actually_re_runs(tmp_path):
    """mux.sub_source prefers the ass over the srt, and merge_pass only re-runs the merge
    when no ass is present. Leaving one behind re-muxes the OLD signs decisions -- the fix
    silently does not land, and every other part of the run reports success."""
    stem = _muxed(tmp_path, "ep_b", ass=True)

    rfs.main([str(tmp_path), "--apply"])

    assert not os.path.exists(stem + ASS)
    assert os.path.exists(stem + SRT)


def test_an_already_open_episode_is_left_completely_alone(tmp_path):
    """No stamp means it is already in the merge queue, or mid-run. Rebuilding its srt
    would race whichever pass owns it."""
    stem = str(tmp_path / "ep_c")
    with open(stem + CONF, "w") as f:
        json.dump([{"start": 0.0, "end": 2.0, "text": "already queued"}], f)
    with open(stem + ASS, "w") as f:
        f.write("[Events]\n")

    rfs.main([str(tmp_path), "--apply"])

    assert os.path.exists(stem + ASS), "an in-flight episode's ass must survive"
    assert not os.path.exists(stem + SRT)


def test_a_dry_run_writes_nothing(tmp_path):
    stem = _muxed(tmp_path, "ep_d", ass=True)

    assert rfs.main([str(tmp_path)]) == 0

    assert os.path.exists(stem + STAMP) and os.path.exists(stem + ASS)
    assert not os.path.exists(stem + SRT)


def test_a_dry_run_counts_the_stale_ass_it_did_not_remove(tmp_path):
    """A dry run used to report "0 stale .ass removed" because the count was only ever set
    on the apply path -- a number that reads as "there are none" while meaning "did not
    look". The count is taken before the dry-run return now, and the summary says "to
    remove" rather than "removed"."""
    _muxed(tmp_path, "ep_e", ass=True)
    _muxed(tmp_path, "ep_f", ass=False)

    assert rfs.process(str(tmp_path / "ep_e") + CONF, apply=False)["stale_ass"] is True
    assert rfs.process(str(tmp_path / "ep_f") + CONF, apply=False)["stale_ass"] is False


def test_no_conf_json_anywhere_is_reported_not_a_silent_success(tmp_path):
    assert rfs.main([str(tmp_path), "--apply"]) == 1
