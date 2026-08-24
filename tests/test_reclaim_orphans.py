"""Checks for tools/reclaim_orphans.py.

Sidecar LOOKUP is by filename stem while sidecar VALIDATION is by content (size+mtime),
so an external transcoder renaming a video orphans a stamp that still describes it
perfectly. Measured on the live library 2026-08-24: 67 orphaned stamps, 46 matching a
video by size, 31 by size and mtime.

This tool renames finished output, so every test below pins a refusal rather than a
capability: what it must NOT move, when it must not run at all, and what it must leave
alone when the evidence is ambiguous.
"""

import json
import os

import common
from tools import reclaim_orphans as ro


def _video(path, payload):
    with open(path, "wb") as f:
        f.write(payload)
    return path


def _orphan(tmp_path, stem_name, payload, *, mtime=None, extra=(".dubtitles.conf.json",)):
    """A stamp (plus sidecars) describing a video that no longer exists under that stem."""
    stem = str(tmp_path / stem_name)
    doc = {"size": len(payload), "mtime": mtime if mtime is not None else 1000.0, "muxed": True, "version": 4}
    with open(stem + common.STAMP_SUFFIX, "w") as f:
        json.dump(doc, f)
    for suff in extra:
        with open(stem + suff, "w") as f:
            f.write("[]")
    return stem


def test_a_renamed_identical_video_is_reclaimed(tmp_path):
    """The 31 orphans matching on size AND mtime: a plain rename, nothing rewritten."""
    payload = b"A" * 500
    new = _video(str(tmp_path / "renamed.mkv"), payload)
    os.utime(new, (1000.0, 1000.0))
    stem = _orphan(tmp_path, "old-name", payload, mtime=1000.0)

    matches = ro.find_matches(str(tmp_path))
    assert len(matches) == 1
    assert matches[0].verdict == "reclaimable"
    assert matches[0].video == new
    assert matches[0].stem == stem


def test_a_size_only_match_is_probable_not_reclaimable(tmp_path):
    """The 15 matching on size but NOT mtime -- consistent with a cp that lost its
    timestamp, and equally consistent with coincidence. A stamp records no digest of the
    original, so there is nothing to confirm identity against; re-keying these on a guess
    would point a stamp at the wrong episode. They are reported and left alone."""
    payload = b"B" * 500
    new = _video(str(tmp_path / "copied.mkv"), payload)
    os.utime(new, (9999.0, 9999.0))
    stem = _orphan(tmp_path, "old-copy", payload, mtime=1000.0)

    m = ro.find_matches(str(tmp_path))[0]
    assert m.mtime_agrees is False
    assert m.verdict == "probable"

    ro.reclaim(str(tmp_path), apply=True)
    assert os.path.exists(stem + common.STAMP_SUFFIX), "a probable match must not move by default"


def test_include_probable_opts_into_the_size_only_matches(tmp_path):
    """The operator can take the risk deliberately -- but has to say so."""
    payload = b"B" * 500
    new = _video(str(tmp_path / "copied.mkv"), payload)
    os.utime(new, (9999.0, 9999.0))
    stem = _orphan(tmp_path, "old-copy", payload, mtime=1000.0)

    ro.reclaim(str(tmp_path), apply=True, include_probable=True)

    assert not os.path.exists(stem + common.STAMP_SUFFIX)
    assert os.path.exists(str(tmp_path / "copied") + common.STAMP_SUFFIX)


def test_a_video_of_a_different_size_is_unrecoverable(tmp_path):
    """A re-encode changes the byte count, so no candidate exists at all. This is the
    honest limit of the tool: with no digest recorded at stamp time, a re-encode that
    happened to land on the SAME size would be indistinguishable from a rename, which is
    exactly why a size-only match is graded `probable` rather than acted on."""
    _video(str(tmp_path / "reencoded.mkv"), b"C" * 400)
    _orphan(tmp_path, "old-reencode", b"D" * 500, mtime=1000.0)

    m = ro.find_matches(str(tmp_path))[0]
    assert m.video is None
    assert m.verdict == "unrecoverable"


def test_two_orphans_matching_one_video_reclaim_neither(tmp_path):
    payload = b"E" * 500
    _video(str(tmp_path / "one.mkv"), payload)
    _orphan(tmp_path, "orphan-a", payload)
    _orphan(tmp_path, "orphan-b", payload)

    assert [m.verdict for m in ro.find_matches(str(tmp_path))] == ["ambiguous", "ambiguous"]


def test_one_orphan_matching_two_videos_reclaims_neither(tmp_path):
    """The mirror of the case above, which the spec's edge list originally missed."""
    payload = b"F" * 500
    _video(str(tmp_path / "twin-1.mkv"), payload)
    _video(str(tmp_path / "twin-2.mkv"), payload)
    _orphan(tmp_path, "orphan-twin", payload)

    assert ro.find_matches(str(tmp_path))[0].verdict == "ambiguous"


def test_dry_run_changes_nothing(tmp_path):
    payload = b"G" * 500
    v = _video(str(tmp_path / "renamed.mkv"), payload)
    os.utime(v, (1000.0, 1000.0))
    stem = _orphan(tmp_path, "old-name", payload)
    before = sorted(os.listdir(tmp_path))

    ro.reclaim(str(tmp_path), apply=False)

    assert sorted(os.listdir(tmp_path)) == before
    assert os.path.exists(stem + common.STAMP_SUFFIX)


def test_apply_rekeys_the_whole_sidecar_set(tmp_path):
    payload = b"H" * 500
    v = _video(str(tmp_path / "renamed.mkv"), payload)
    os.utime(v, (1000.0, 1000.0))
    stem = _orphan(
        tmp_path,
        "old-name",
        payload,
        extra=(".dubtitles.conf.json", ".dubtitles.qc.json", common.WORDS_SUFFIX),
    )

    ro.reclaim(str(tmp_path), apply=True)

    new_stem = str(tmp_path / "renamed")
    for suff in (common.STAMP_SUFFIX, ".dubtitles.conf.json", ".dubtitles.qc.json", common.WORDS_SUFFIX):
        assert os.path.exists(new_stem + suff), f"{suff} not re-keyed"
        assert not os.path.exists(stem + suff), f"{suff} left behind at the old stem"


def test_apply_never_moves_the_markers(tmp_path):
    """.fail is a poison marker for THAT stem, .stale is parked output, .muxtmp.mkv is an
    in-flight mux. Moving any of them onto a live stem would corrupt state rather than
    recover it."""
    payload = b"I" * 500
    v = _video(str(tmp_path / "renamed.mkv"), payload)
    os.utime(v, (1000.0, 1000.0))
    stem = _orphan(tmp_path, "old-name", payload, extra=(".dubtitles.fail", ".eng.dubtitles.srt.stale"))

    ro.reclaim(str(tmp_path), apply=True)

    assert os.path.exists(stem + ".dubtitles.fail"), ".fail must not follow the rename"
    assert os.path.exists(stem + ".eng.dubtitles.srt.stale"), ".stale must not follow the rename"


def test_apply_never_deletes_anything(tmp_path):
    """Unrecoverable orphans are REPORTED, never cleaned up: the stamp is the only record
    that the episode was ever processed."""
    _video(str(tmp_path / "reencoded.mkv"), b"J" * 500)
    stem = _orphan(tmp_path, "old-name", b"K" * 500)

    ro.reclaim(str(tmp_path), apply=True)

    assert os.path.exists(stem + common.STAMP_SUFFIX)


def test_apply_refuses_while_the_pipeline_is_live(tmp_path, monkeypatch):
    """generate and mux write and delete exactly the files this renames. A re-key racing
    a live mux re-creates the silent-corruption class this whole epic is about."""
    payload = b"L" * 500
    v = _video(str(tmp_path / "renamed.mkv"), payload)
    os.utime(v, (1000.0, 1000.0))
    stem = _orphan(tmp_path, "old-name", payload)
    monkeypatch.setattr(ro, "pipeline_is_live", lambda: True)

    ro.reclaim(str(tmp_path), apply=True)

    assert os.path.exists(stem + common.STAMP_SUFFIX), "re-keyed despite a live pipeline"


def test_a_stamp_whose_video_still_exists_is_not_an_orphan(tmp_path):
    payload = b"M" * 500
    v = _video(str(tmp_path / "present.mkv"), payload)
    os.utime(v, (1000.0, 1000.0))
    _orphan(tmp_path, "present", payload, mtime=1000.0)

    assert ro.find_matches(str(tmp_path)) == []
