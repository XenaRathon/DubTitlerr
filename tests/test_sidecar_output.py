"""DUB_OUTPUT=sidecar (#38): the assembled subtitle stays beside the video and the video is never rewritten.

Three layers, bottom up:

* common: the mode itself, the stamp field that marks sidecar output, and kept_sidecar(), the one predicate that tells a
  finished sidecar from a sidecar still waiting for the merge pass.
* mux.process: stamps and records instead of muxing, and never stamps a subtitle it did not just get handed.
* merge_pass.sh end to end, with the REAL mux.py and stub repair / signs stages that log their calls. The pass is where the
  feature can go wrong quietly: under mux output a subtitle on disk always meant "work waiting", so a pass that kept that
  assumption would run repair again on every finished dialogue-only episode, every MERGE_INTERVAL, for good.
"""

import json
import os
import shlex
import stat
import subprocess
import sys

import pysubs2
import pytest

import common
import dub_signs_merge as dsm
import mux

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MERGE_PASS = os.path.join(REPO, "merge_pass.sh")
ASS, SRT, STAMP = ".eng.dubtitles.ass", ".eng.dubtitles.srt", common.STAMP_SUFFIX


def _age(path, seconds):
    """Move a file's mtime ``seconds`` away from now-as-the-file-knows-it (negative: older)."""
    st = os.stat(path)
    os.utime(path, (st.st_atime, st.st_mtime + seconds))


def _episode(tmp_path, video="ep.mkv", sidecar=ASS):
    """A video with one finished subtitle sidecar beside it, not stamped. Returns (video path, stem)."""
    v = tmp_path / video
    v.write_bytes(b"original-video-bytes")
    stem = str(tmp_path / "ep")
    with open(stem + sidecar, "w") as f:
        f.write("the subtitle\n")
    return str(v), stem


def _sidecar_stamp(v, stem, **overrides):
    """What sidecar output leaves behind: the stamp written AFTER the subtitle. ``overrides`` rewrite stamp fields."""
    for suff in common.SUBTITLE_SUFFIXES:
        if os.path.exists(stem + suff):
            _age(stem + suff, -120)
    common.write_stamp(stem + STAMP, v, output="sidecar")
    if overrides:
        doc = common.read_stamp(stem + STAMP)
        doc.update(overrides)
        with open(stem + STAMP, "w") as f:
            json.dump(doc, f)


# --- common: the mode ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value, expected", [(None, "mux"), ("", "mux"), ("mux", "mux"), ("sidecar", "sidecar")])
def test_output_mode_defaults_to_mux_and_knows_sidecar(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("DUB_OUTPUT", raising=False)
    else:
        monkeypatch.setenv("DUB_OUTPUT", value)
    assert common.output_mode() == expected


@pytest.mark.parametrize("value", ["Sidecar", "sidecars", "SIDECAR", " sidecar", "external", "0"])
def test_an_unknown_output_mode_raises_instead_of_falling_back_to_mux(monkeypatch, value):
    """The fallback would be the one mode that rewrites video files, given to someone who asked for something else."""
    monkeypatch.setenv("DUB_OUTPUT", value)
    with pytest.raises(ValueError, match="DUB_OUTPUT"):
        common.output_mode()


# --- common: the stamp field ----------------------------------------------------------------------------------------------


def test_the_output_field_is_additive_and_a_mux_stamp_does_not_carry_it(tmp_path):
    v, stem = _episode(tmp_path)
    common.write_stamp(stem + STAMP, v)
    assert "output" not in common.read_stamp(stem + STAMP)
    assert common.stamp_valid(common.read_stamp(stem + STAMP), v)

    common.write_stamp(stem + STAMP, v, output="sidecar")
    doc = common.read_stamp(stem + STAMP)
    assert doc["output"] == "sidecar"
    assert doc["muxed"] is True, "every reader takes `muxed` to mean done; a sidecar stamp without it reads as unprocessed"
    assert common.stamp_valid(doc, v)


# --- common: kept_sidecar ------------------------------------------------------------------------------------------------


def test_a_subtitle_that_predates_a_sidecar_stamp_is_kept_output(tmp_path):
    v, stem = _episode(tmp_path)
    _sidecar_stamp(v, stem)
    assert common.kept_sidecar(stem) is True


def test_a_subtitle_with_no_stamp_is_work(tmp_path):
    v, stem = _episode(tmp_path)
    assert common.kept_sidecar(stem) is False


def test_a_subtitle_beside_a_mux_stamp_is_never_kept_output(tmp_path):
    """Nothing changes for mux output: a sidecar left beside a stamp mux wrote is treated exactly as before."""
    v, stem = _episode(tmp_path)
    _age(stem + ASS, -120)
    common.write_stamp(stem + STAMP, v)
    assert common.kept_sidecar(stem) is False


_STALE = {"text_version": common.TEXT_VERSION - 1, "version": common.TEXT_VERSION - 1}


def test_a_subtitle_newer_than_a_stale_sidecar_stamp_is_work_again(tmp_path):
    """generate.py's replacement: it is written after the stamp it supersedes."""
    v, stem = _episode(tmp_path, sidecar=SRT)
    _sidecar_stamp(v, stem, **_STALE)
    _age(stem + SRT, +600)
    assert common.kept_sidecar(stem) is False


def test_one_new_subtitle_beside_an_old_one_under_a_stale_stamp_is_work(tmp_path):
    v, stem = _episode(tmp_path)
    _sidecar_stamp(v, stem, **_STALE)
    with open(stem + SRT, "w") as f:
        f.write("regenerated dialogue\n")
    _age(stem + SRT, +600)
    assert common.kept_sidecar(stem) is False


def test_a_subtitle_newer_than_a_current_sidecar_stamp_is_still_finished(tmp_path):
    """Corrected by hand, or copied without its timestamps. Nothing else writes beside a current stamp (generate.py skips
    it, review_apply.py drops it first), and repair would rebuild the file from conf.json and undo the correction."""
    v, stem = _episode(tmp_path, sidecar=SRT)
    _sidecar_stamp(v, stem)
    _age(stem + SRT, +600)
    assert common.kept_sidecar(stem) is True


def test_a_subtitle_with_its_stamp_dropped_is_work(tmp_path):
    """How review_apply.py re-opens an episode: fresh srt, no stamp."""
    v, stem = _episode(tmp_path, sidecar=SRT)
    _sidecar_stamp(v, stem)
    os.remove(stem + STAMP)
    assert common.kept_sidecar(stem) is False


def test_a_sidecar_stamp_with_no_subtitle_left_is_not_kept_output(tmp_path):
    v, stem = _episode(tmp_path)
    _sidecar_stamp(v, stem)
    os.remove(stem + ASS)
    assert common.kept_sidecar(stem) is False


def test_kept_output_stays_kept_when_its_stamp_goes_stale(tmp_path):
    """Stale means generate.py will replace it. Until it has, the merge pass must not repair it or stamp it current."""
    v, stem = _episode(tmp_path)
    _sidecar_stamp(v, stem, text_version=common.TEXT_VERSION - 1, version=common.TEXT_VERSION - 1)
    assert not common.stamp_valid(common.read_stamp(stem + STAMP), v)
    assert common.kept_sidecar(stem) is True


def test_kept_output_stays_kept_when_the_video_is_replaced(tmp_path):
    v, stem = _episode(tmp_path)
    _sidecar_stamp(v, stem)
    with open(v, "wb") as f:
        f.write(b"a different release of the same episode")
    assert not common.stamp_valid(common.read_stamp(stem + STAMP), v)
    assert common.kept_sidecar(stem) is True


def test_an_unreadable_stamp_is_not_kept_output(tmp_path):
    v, stem = _episode(tmp_path)
    with open(stem + STAMP, "w") as f:
        f.write('["not", "a", "stamp"]')
    assert common.kept_sidecar(stem) is False


def test_sidecar_outlived_video_only_for_a_sidecar_stamp_of_another_file(tmp_path):
    v, stem = _episode(tmp_path)
    assert common.sidecar_outlived_video(None, v) is False
    common.write_stamp(stem + STAMP, v, output="sidecar")
    sidecar_doc = common.read_stamp(stem + STAMP)
    common.write_stamp(stem + STAMP, v)
    mux_doc = common.read_stamp(stem + STAMP)
    assert common.sidecar_outlived_video(sidecar_doc, v) is False, "same file: not outlived"
    with open(v, "wb") as f:
        f.write(b"a different release of the same episode")
    assert common.sidecar_outlived_video(sidecar_doc, v) is True
    assert common.sidecar_outlived_video(mux_doc, v) is False, "a replaced MUXED video is plain unprocessed, as before"


# --- mux.process ---------------------------------------------------------------------------------------------------------


def _no_mux_tools(monkeypatch):
    """Sidecar output must not run a single media tool: any attempt fails the test."""

    def boom(*a, **k):
        raise AssertionError("sidecar output touched a media tool")

    monkeypatch.setattr(mux.subprocess, "run", boom)
    monkeypatch.setattr(mux, "identify", boom)
    monkeypatch.setattr(mux, "verify", boom)


def _sidecar_mode(monkeypatch, tmp_path, video="ep.mkv", sidecar=ASS):
    monkeypatch.setenv("DUB_OUTPUT", "sidecar")
    monkeypatch.setattr(common, "OUTPUT_ROOT", "")
    _no_mux_tools(monkeypatch)
    return _episode(tmp_path, video, sidecar)


def test_sidecar_output_stamps_and_keeps_the_subtitle_without_touching_the_video(tmp_path, monkeypatch):
    v, stem = _sidecar_mode(monkeypatch, tmp_path)
    before = os.stat(v)

    assert mux.process(v, apply=True) == "sidecar-kept"

    after = os.stat(v)
    assert open(v, "rb").read() == b"original-video-bytes"
    assert (after.st_size, after.st_mtime_ns, after.st_ino) == (before.st_size, before.st_mtime_ns, before.st_ino)
    assert open(stem + ASS).read() == "the subtitle\n"
    doc = common.read_stamp(stem + STAMP)
    assert common.stamp_valid(doc, v)
    assert doc["output"] == "sidecar"
    assert doc["stages"]["signs_merge"] is True
    rec = common.read_stages(stem)["mux"]
    assert (rec["outcome"], rec["detail"]) == ("ok", "sidecar")
    assert common.failed_stage(stem) is None
    assert sorted(os.listdir(tmp_path)) == sorted(
        ["ep.mkv", "ep" + ASS, "ep" + STAMP, "ep" + common.STAGES_SUFFIX]
    ), "no temp file, no mux log, nothing else"


def test_sidecar_output_leaves_an_mp4_an_mp4(tmp_path, monkeypatch):
    """mux turns every source into an mkv and removes the original. Sidecar output does neither."""
    v, stem = _sidecar_mode(monkeypatch, tmp_path, video="ep.mp4", sidecar=SRT)
    assert mux.process(v, apply=True) == "sidecar-kept"
    assert os.path.exists(v) and not os.path.exists(stem + ".mkv")
    assert os.path.exists(stem + SRT)
    assert common.read_stamp(stem + STAMP)["stages"]["signs_merge"] is False


def test_sidecar_output_is_done_on_the_second_call(tmp_path, monkeypatch):
    v, stem = _sidecar_mode(monkeypatch, tmp_path)
    assert mux.process(v, apply=True) == "sidecar-kept"
    stamped = os.stat(stem + STAMP).st_mtime_ns
    assert mux.process(v, apply=True) == "already-muxed"
    assert os.stat(stem + STAMP).st_mtime_ns == stamped


def test_sidecar_output_dry_run_writes_nothing(tmp_path, monkeypatch):
    v, stem = _sidecar_mode(monkeypatch, tmp_path)
    assert mux.process(v, apply=False) == "plan"
    assert sorted(os.listdir(tmp_path)) == sorted(["ep.mkv", "ep" + ASS])


def test_sidecar_output_needs_no_disk_headroom(tmp_path, monkeypatch):
    """Nothing is copied, so the low-disk skip that guards a remux must not hold a sidecar back."""
    v, stem = _sidecar_mode(monkeypatch, tmp_path)
    monkeypatch.setattr(mux, "_free_bytes", lambda p: 0)
    assert mux.process(v, apply=True) == "sidecar-kept"


def test_a_stamp_that_cannot_be_written_is_a_failed_stage_not_a_done_episode(tmp_path, monkeypatch):
    v, stem = _sidecar_mode(monkeypatch, tmp_path)

    def boom(path, video, **_kw):
        raise OSError("read-only file system")

    monkeypatch.setattr(mux, "write_stamp", boom)
    assert mux.process(v, apply=True) == "stamp-write-failed"
    assert not os.path.exists(stem + STAMP)
    assert os.path.exists(stem + ASS), "the subtitle is the product: it stays"
    assert common.read_stages(stem)["mux"]["outcome"] == "unwritable"
    assert common.failed_stage(stem) == "mux"


def test_a_failed_signs_stage_still_blocks_the_stamp_in_sidecar_mode(tmp_path, monkeypatch):
    """The dialogue-only .srt of an episode whose signs build failed must not become "done" by another route."""
    v, stem = _sidecar_mode(monkeypatch, tmp_path, sidecar=SRT)
    common.write_stage(stem, "signs", "build-error")
    assert mux.process(v, apply=True) == "signs-regression-refused"
    assert not os.path.exists(stem + STAMP)


def test_the_review_gate_still_holds_in_sidecar_mode(tmp_path, monkeypatch):
    v, stem = _sidecar_mode(monkeypatch, tmp_path)
    monkeypatch.setattr(mux, "held_for_review", lambda s: True)
    assert mux.process(v, apply=True) == "held-for-review"
    assert not os.path.exists(stem + STAMP)


@pytest.mark.parametrize("mode", ["sidecar", "mux"])
def test_kept_output_under_a_stale_stamp_is_never_stamped_current_or_muxed(tmp_path, monkeypatch, mode):
    """The version bump that silently does nothing: last version's subtitle, still on disk, stamped as this version's.
    Under mux output too, for someone who switched back: the stamp decides, not the mode."""
    monkeypatch.setenv("DUB_OUTPUT", mode)
    monkeypatch.setattr(common, "OUTPUT_ROOT", "")
    _no_mux_tools(monkeypatch)
    v, stem = _episode(tmp_path)
    old = common.TEXT_VERSION - 1
    _sidecar_stamp(v, stem, text_version=old, version=old)
    stamped = os.stat(stem + STAMP).st_mtime_ns

    assert mux.process(v, apply=True) == "awaiting-regeneration"

    assert common.read_stamp(stem + STAMP)["text_version"] == old
    assert os.stat(stem + STAMP).st_mtime_ns == stamped
    assert open(v, "rb").read() == b"original-video-bytes"
    assert os.path.exists(stem + ASS)


def test_a_regenerated_subtitle_beside_a_stale_sidecar_stamp_is_stamped_current(tmp_path, monkeypatch):
    v, stem = _sidecar_mode(monkeypatch, tmp_path)
    old = common.TEXT_VERSION - 1
    _sidecar_stamp(v, stem, text_version=old, version=old)
    _age(stem + ASS, +600)  # generate.py parked the old one and the pass assembled a new one

    assert mux.process(v, apply=True) == "sidecar-kept"

    doc = common.read_stamp(stem + STAMP)
    assert doc["text_version"] == common.TEXT_VERSION
    assert common.stamp_valid(doc, v)


def test_mux_main_refuses_an_unknown_output_mode_before_touching_anything(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DUB_OUTPUT", "Sidecar")
    monkeypatch.setattr(common, "OUTPUT_ROOT", "")
    _no_mux_tools(monkeypatch)
    v, stem = _episode(tmp_path)
    assert mux.main(["--apply", v]) == 2
    assert "FATAL" in capsys.readouterr().out
    assert sorted(os.listdir(tmp_path)) == sorted(["ep.mkv", "ep" + ASS])


def test_mux_main_still_returns_none_on_a_normal_run(tmp_path, monkeypatch):
    monkeypatch.delenv("DUB_OUTPUT", raising=False)
    assert mux.main([str(tmp_path / "no-such-video.mkv")]) is None


# --- dub_signs_merge: the dialogue font ----------------------------------------------------------------------------------


def _build_with_dialogue_font(tmp_path, monkeypatch, fontname, attachments):
    track = pysubs2.SSAFile()
    track.styles["Default"] = pysubs2.SSAStyle(fontname=fontname)
    track.styles["Sign"] = pysubs2.SSAStyle(fontname="SignFont")
    track.events = [
        pysubs2.SSAEvent(start=1000, end=3000, style="Default", text="Spoken dialogue line 1"),
        pysubs2.SSAEvent(start=3500, end=5500, style="Default", text="Spoken dialogue line 2"),
        pysubs2.SSAEvent(start=6000, end=7000, style="Sign", text=r"{\pos(10,20)}A sign"),
    ]
    monkeypatch.setattr(dsm, "signs_sub_streams", lambda video, langs: [0])
    monkeypatch.setattr(dsm, "extract", lambda video, idx, out: track.save(out) or True)
    monkeypatch.setattr(dsm, "list_attachment_filenames", attachments)
    dub_srt = tmp_path / "dub.srt"
    dub_srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nDub line\n\n", encoding="utf-8")
    out_ass = str(tmp_path / "out.ass")
    status, _signs, _dub = dsm.build("fake.mkv", str(dub_srt), out_ass)
    assert status == "ok"
    return pysubs2.load(out_ass)


def test_sidecar_output_does_not_trust_a_font_attached_to_the_video(tmp_path, monkeypatch, capsys):
    """Under mux output the attached font ships with the track. A sidecar ships no fonts, so only the safe set is kept."""
    monkeypatch.setenv("DUB_OUTPUT", "sidecar")
    res = _build_with_dialogue_font(tmp_path, monkeypatch, "WildWords", lambda video: ["wildwords-regular.ttf"])
    assert res.styles["Dubtitles"].fontname == dsm.DEFAULT_DUB_FONT
    assert "sidecar output: font 'WildWords' not in safe set" in capsys.readouterr().out
    assert res.styles["Sign"].fontname == "SignFont", "signs keep the styles their source gave them"


def test_sidecar_output_does_not_probe_the_video_for_attachments(tmp_path, monkeypatch):
    def boom(video):
        raise AssertionError("attachments were listed for a sidecar")

    monkeypatch.setenv("DUB_OUTPUT", "sidecar")
    res = _build_with_dialogue_font(tmp_path, monkeypatch, "WildWords", boom)
    assert res.styles["Dubtitles"].fontname == dsm.DEFAULT_DUB_FONT


def test_sidecar_output_keeps_a_safe_set_font(tmp_path, monkeypatch):
    monkeypatch.setenv("DUB_OUTPUT", "sidecar")
    res = _build_with_dialogue_font(tmp_path, monkeypatch, "Verdana", lambda video: [])
    assert res.styles["Dubtitles"].fontname == "Verdana"


def test_mux_output_still_trusts_the_attached_font(tmp_path, monkeypatch):
    monkeypatch.delenv("DUB_OUTPUT", raising=False)
    res = _build_with_dialogue_font(tmp_path, monkeypatch, "WildWords", lambda video: ["wildwords-regular.ttf"])
    assert res.styles["Dubtitles"].fontname == "WildWords"


# --- merge_pass.sh, end to end -------------------------------------------------------------------------------------------
#
# The real script and the real mux.py. repair and signs are stubs that log each call and record "ok"; the signs stub merges
# an .ass only when EPISODE_HAS_SIGNS=1, otherwise it leaves the dialogue-only .srt as the real stage does for an mp4 or an
# mkv with no signs track. mkvmerge and ffmpeg are stubs that log each call, so "the video was never touched" is asserted
# from the tool side as well as from the file.

_STAGE_STUB = """\
import os, sys
sys.path.insert(0, {repo!r})
import common
common.OUTPUT_ROOT = ""
name = {name!r}
arg = sys.argv[-1]
for suffix in (".dubtitles.conf.json", ".eng.dubtitles.srt"):
    if arg.endswith(suffix):
        stem = arg[: -len(suffix)]
with open(os.environ["CALLLOG"], "a") as f:
    f.write(name + " " + os.path.basename(stem) + "\\n")
common.write_stage(stem, name, "ok")
if name == "signs" and os.environ.get("EPISODE_HAS_SIGNS") == "1":
    with open(stem + ".eng.dubtitles.ass", "w") as f:
        f.write("merged\\n")
    os.remove(stem + ".eng.dubtitles.srt")
"""

# Logs the call, then runs the real mux.py as __main__ with the stub folder off the import path (so `import repair` and
# friends inside the real modules can never pick up a stub).
_REAL_MUX = """\
import os, runpy, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [{repo!r}] + [p for p in sys.path if os.path.abspath(p or ".") != here]
with open(os.environ["CALLLOG"], "a") as f:
    f.write("mux " + os.path.basename(os.path.splitext(sys.argv[-1])[0]) + "\\n")
sys.argv[0] = os.path.join({repo!r}, "mux.py")
runpy.run_path(sys.argv[0], run_name="__main__")
"""


class _Library:
    def __init__(self, tmp_path, video="ep01.mkv"):
        self.tmp = tmp_path
        self.root = tmp_path / "library"
        show = self.root / "Show"
        show.mkdir(parents=True)
        self.video = show / video
        self.video.write_bytes(b"original-video-bytes")
        self.stem = str(show / "ep01")
        self.calllog = tmp_path / "calls.log"
        self.toollog = tmp_path / "tools.log"
        self.calllog.write_text("")
        self.toollog.write_text("")
        self.write_srt()

        self.app = tmp_path / "app"
        self.app.mkdir()
        (self.app / "repair.py").write_text(_STAGE_STUB.format(repo=REPO, name="repair"))
        (self.app / "dub_signs_merge.py").write_text(_STAGE_STUB.format(repo=REPO, name="signs"))
        (self.app / "mux.py").write_text(_REAL_MUX.format(repo=REPO))
        (self.app / "shell").mkdir()
        with open(os.path.join(REPO, "shell", "lib.sh")) as f:
            (self.app / "shell" / "lib.sh").write_text(f.read())

        self.bindir = tmp_path / "fakebin"
        self.bindir.mkdir()
        for tool in ("mkvmerge", "ffmpeg", "ffprobe"):
            p = self.bindir / tool
            p.write_text(f'#!/bin/sh\necho "{tool} $*" >> {shlex.quote(str(self.toollog))}\nexit 0\n')
            p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    def write_srt(self):
        with open(self.stem + SRT, "w") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nA line\n\n")

    def run(self, output="sidecar", signs=False, **extra_env):
        env = dict(os.environ)
        env.pop("DUB_OUTPUT", None)
        env.pop("OUTPUT_ROOT", None)
        env["PATH"] = str(self.bindir) + os.pathsep + env["PATH"]
        env.update(MERGE_ROOTS=str(self.root), APP_DIR=str(self.app), PYTHONPATH=REPO, CALLLOG=str(self.calllog))
        env["EPISODE_HAS_SIGNS"] = "1" if signs else "0"
        if output is not None:
            env["DUB_OUTPUT"] = output
        env.update(extra_env)
        before = len(self.calls())
        res = subprocess.run(["/bin/sh", MERGE_PASS], env=env, cwd=str(self.root), capture_output=True, text=True, timeout=120)
        return res, self.calls()[before:]

    def calls(self):
        return self.calllog.read_text().split("\n")[:-1]

    def stamp(self):
        return common.read_stamp(self.stem + STAMP)

    def video_untouched(self):
        return self.video.read_bytes() == b"original-video-bytes" and self.toollog.read_text() == ""


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "OUTPUT_ROOT", "")
    return _Library(tmp_path)


def test_a_sidecar_pass_assembles_stamps_and_never_touches_the_video(lib):
    before = os.stat(lib.video)
    res, calls = lib.run(signs=True)

    assert calls == ["repair ep01", "signs ep01", "mux ep01"], (calls, res.stdout, res.stderr)
    assert os.path.exists(lib.stem + ASS), "the assembled subtitle is the output and stays"
    assert lib.video_untouched(), lib.toollog.read_text()
    assert os.stat(lib.video).st_mtime_ns == before.st_mtime_ns
    assert common.stamp_valid(lib.stamp(), str(lib.video))
    assert lib.stamp()["output"] == "sidecar"
    assert common.failed_stage(lib.stem) is None
    assert "MERGE PASS COMPLETE" in res.stdout, res.stdout + res.stderr
    assert "MERGE_PASS_DONE new=1 total_done=1" in res.stdout, "the Plex refresh keys on this count"


def test_a_finished_dialogue_only_sidecar_is_not_repaired_again_on_the_next_pass(lib):
    """The loop this file exists for. An .srt with no .ass is how the pass recognises an episode to assemble, and under
    sidecar output a finished mp4 (or an mkv with no signs) looks exactly like that for good. Without the stamp check every
    pass ran repair on it again: one LLM call per low-confidence line, per episode, per MERGE_INTERVAL."""
    res, calls = lib.run(signs=False)
    assert calls == ["repair ep01", "signs ep01", "mux ep01"], (calls, res.stdout, res.stderr)
    assert os.path.exists(lib.stem + SRT) and not os.path.exists(lib.stem + ASS)
    stamped = os.stat(lib.stem + STAMP).st_mtime_ns

    for _ in range(2):
        res, calls = lib.run(signs=False)
        assert calls == [], (calls, res.stdout, res.stderr)
        assert "MERGE PASS COMPLETE" in res.stdout, res.stdout + res.stderr
    assert os.stat(lib.stem + STAMP).st_mtime_ns == stamped
    assert lib.video_untouched()


def test_a_finished_sidecar_corrected_by_hand_is_not_repaired_over(lib):
    """The reason to want a sidecar at all (#38): a bad line can be fixed in the file. repair rebuilds the srt from
    conf.json, so a pass that took the newer file for pending work would undo the fix, and do it again every pass."""
    lib.run(signs=False)
    with open(lib.stem + SRT, "w") as f:
        f.write("1\n00:00:01,000 --> 00:00:02,000\nA line, corrected by hand\n\n")
    _age(lib.stem + SRT, +600)

    for _ in range(2):
        res, calls = lib.run(signs=False)
        assert calls == [], (calls, res.stdout, res.stderr)
    assert "corrected by hand" in open(lib.stem + SRT).read()


def test_a_finished_ass_sidecar_is_left_alone_on_the_next_pass(lib):
    lib.run(signs=True)
    res, calls = lib.run(signs=True)
    assert calls == [], (calls, res.stdout, res.stderr)
    assert "MERGE PASS COMPLETE" in res.stdout


def test_a_version_bump_is_not_papered_over_by_the_merge_pass(lib):
    """After a bump every finished sidecar sits beside a stale stamp, and the merge pass gets to it long before generate.py
    does. It must neither repair the old text again nor stamp it current. Once generate has written the replacement, the
    same pass picks it up as ordinary work."""
    lib.run(signs=False)
    old = common.TEXT_VERSION - 1
    doc = lib.stamp()
    doc.update(text_version=old, version=old)
    with open(lib.stem + STAMP, "w") as f:
        json.dump(doc, f)

    res, calls = lib.run(signs=False)
    assert calls == [], (calls, res.stdout, res.stderr)
    assert lib.stamp()["text_version"] == old, "last version's subtitle was stamped as this version's"

    lib.write_srt()  # generate.py's text tier writes the new srt in place
    _age(lib.stem + SRT, +600)
    res, calls = lib.run(signs=False)
    assert calls == ["repair ep01", "signs ep01", "mux ep01"], (calls, res.stdout, res.stderr)
    assert common.stamp_valid(lib.stamp(), str(lib.video))
    assert lib.video_untouched()


def test_switching_back_to_mux_does_not_reprocess_finished_sidecars(lib):
    """A finished sidecar is done whatever the mode says later: it is not repaired again and the video is not muxed behind
    the operator's back. (To embed it after all, delete its .dubtitles.done: then it is ordinary pending work.)"""
    lib.run(signs=False)
    for output in ("mux", None):
        res, calls = lib.run(output=output, signs=False)
        assert calls == [], (output, calls, res.stdout, res.stderr)
    assert lib.video_untouched()


@pytest.mark.parametrize("value", ["Sidecar", "sidecars", "external"])
def test_an_unknown_output_mode_stops_the_pass_before_any_stage(lib, value):
    res, calls = lib.run(output=value, signs=True)
    assert res.returncode != 0
    assert calls == []
    assert res.stdout.count("configuration error") == 1, res.stdout
    assert f"DUB_OUTPUT='{value}'" in res.stdout
    assert common.read_stages(lib.stem) == {}
    assert not os.path.exists(lib.stem + STAMP)
    assert lib.video_untouched()
    assert "MERGE PASS" not in res.stdout


def test_a_stamp_check_that_cannot_run_skips_the_stem(lib):
    """Fails closed, like the stage gates: when the pass cannot tell finished output from pending work, it does nothing to
    the stem rather than repair and stamp it blind."""
    lib.run(signs=False)
    wrapper = lib.bindir / "python3"
    wrapper.write_text(f'#!/bin/sh\ncase "$2" in *kept_sidecar*) exit 1 ;;\nesac\nexec {shlex.quote(sys.executable)} "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    stamped = os.stat(lib.stem + STAMP).st_mtime_ns

    res, calls = lib.run(signs=False)

    assert calls == [], (calls, res.stdout, res.stderr)
    assert "cannot tell whether" in res.stdout and "(gate-error)" in res.stdout
    assert os.stat(lib.stem + STAMP).st_mtime_ns == stamped


def test_a_stem_mux_stamped_is_handled_as_before_in_mux_mode(lib):
    """Nothing changes for mux output. A sidecar left beside a stamp mux wrote (its post-stamp cleanup failed) reaches the
    stages exactly as it did before this mode existed; here the real mux.py answers already-muxed from the stamp."""
    _age(lib.stem + SRT, -120)
    common.write_stamp(lib.stem + STAMP, str(lib.video))
    res, calls = lib.run(output=None, signs=False)
    assert calls == ["repair ep01", "signs ep01", "mux ep01"], (calls, res.stdout, res.stderr)
    assert lib.video_untouched(), "a valid stamp: mux.py must not have reached mkvmerge"
