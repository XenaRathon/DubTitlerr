"""OUTPUT_MODE=sidecar (#38): assemble without muxing.

The video must never be opened for writing, the assembled sidecar must stay beside it, and a
.dubtitles.done stamp must keep the pass idempotent. Switching back to mux must mux those
episodes rather than treat them as done."""

import json
import os
import stat
import subprocess

import pytest

import common
import generate
import mux

SRT = "1\n00:00:00,000 --> 00:00:01,000\nhi\n"


@pytest.fixture(autouse=True)
def _no_output_root(monkeypatch):
    monkeypatch.setattr(common, "OUTPUT_ROOT", "")


def _never_remux(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("sidecar mode must not run mkvmerge / ffprobe")

    monkeypatch.setattr(mux.subprocess, "run", boom)
    monkeypatch.setattr(mux, "identify", boom)


def _episode(tmp_path, ext="mkv", ass=True, srt=False):
    v = tmp_path / f"ep.{ext}"
    v.write_bytes(b"x" * 100)
    if ass:
        (tmp_path / ("ep" + mux.ASS_SUFFIX)).write_text("[Script Info]\n")
    if srt:
        (tmp_path / ("ep" + mux.SRT_SUFFIX)).write_text(SRT)
    return v, str(tmp_path / "ep")


def test_output_mode_default_and_parsing(monkeypatch):
    monkeypatch.delenv("OUTPUT_MODE", raising=False)
    assert common.output_mode() == "mux"
    monkeypatch.setenv("OUTPUT_MODE", " Sidecar ")
    assert common.output_mode() == "sidecar"
    # an unknown value must never be the thing that rewrites media in place
    monkeypatch.setenv("OUTPUT_MODE", "sidecars")
    assert common.output_mode() == "sidecar"


def test_sidecar_mode_stamps_untouched_video_and_keeps_the_ass(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_MODE", "sidecar")
    _never_remux(monkeypatch)
    v, stem = _episode(tmp_path)
    before = os.stat(v)

    assert mux.process(str(v), apply=True) == "sidecar"

    after = os.stat(v)
    assert (after.st_size, after.st_mtime_ns, after.st_ino) == (before.st_size, before.st_mtime_ns, before.st_ino)
    assert v.read_bytes() == b"x" * 100
    assert os.path.exists(stem + mux.ASS_SUFFIX)
    stamp = common.read_stamp(stem + common.STAMP_SUFFIX)
    assert stamp["output"] == "sidecar"
    assert common.stamp_valid(stamp, str(v))
    assert common.read_stages(stem)["mux"]["outcome"] == "ok"
    assert not os.path.exists(stem + ".muxtmp.mkv")


def test_sidecar_mode_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_MODE", "sidecar")
    _never_remux(monkeypatch)
    v, _ = _episode(tmp_path)
    assert mux.process(str(v), apply=True) == "sidecar"
    assert mux.process(str(v), apply=True) == "already-muxed"


def test_sidecar_mode_mp4_keeps_srt_and_mp4(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_MODE", "sidecar")
    _never_remux(monkeypatch)
    v, stem = _episode(tmp_path, ext="mp4", ass=False, srt=True)
    assert mux.process(str(v), apply=True) == "sidecar"
    assert v.exists() and not (tmp_path / "ep.mkv").exists()
    assert (tmp_path / ("ep" + mux.SRT_SUFFIX)).read_text() == SRT


def test_sidecar_mode_drops_the_redundant_srt_beside_an_ass(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_MODE", "sidecar")
    _never_remux(monkeypatch)
    v, stem = _episode(tmp_path, ass=True, srt=True)
    assert mux.process(str(v), apply=True) == "sidecar"
    assert os.path.exists(stem + mux.ASS_SUFFIX)
    assert not os.path.exists(stem + mux.SRT_SUFFIX)


def test_sidecar_mode_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_MODE", "sidecar")
    _never_remux(monkeypatch)
    v, stem = _episode(tmp_path)
    assert mux.process(str(v), apply=False) == "plan"
    assert not os.path.exists(stem + common.STAMP_SUFFIX)


def test_sidecar_mode_still_refuses_a_signs_regression(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_MODE", "sidecar")
    _never_remux(monkeypatch)
    v, stem = _episode(tmp_path, ass=False, srt=True)
    common.write_stage(stem, "signs", "build-error", "forced")
    assert mux.process(str(v), apply=True) == "signs-regression-refused"
    assert not os.path.exists(stem + common.STAMP_SUFFIX)


def test_sidecar_mode_still_honours_the_review_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_MODE", "sidecar")
    _never_remux(monkeypatch)
    v, stem = _episode(tmp_path)
    monkeypatch.setattr(mux, "held_for_review", lambda s: True)
    assert mux.process(str(v), apply=True) == "held-for-review"
    assert not os.path.exists(stem + common.STAMP_SUFFIX)


def test_sidecar_stamp_write_failure_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_MODE", "sidecar")
    _never_remux(monkeypatch)
    v, stem = _episode(tmp_path)

    def boom(*a, **kw):
        raise OSError("read-only")

    monkeypatch.setattr(mux, "write_stamp", boom)
    assert mux.process(str(v), apply=True) == "stamp-write-failed"
    assert os.path.exists(stem + mux.ASS_SUFFIX)
    assert common.read_stages(stem)["mux"]["outcome"] == "unwritable"


def test_switching_back_to_mux_muxes_a_sidecar_episode(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_MODE", "sidecar")
    _never_remux(monkeypatch)
    v, _ = _episode(tmp_path)
    assert mux.process(str(v), apply=True) == "sidecar"

    monkeypatch.setenv("OUTPUT_MODE", "mux")
    monkeypatch.setattr(mux, "identify", lambda p: {"tracks": [{"id": 0, "type": "audio", "properties": {"language": "eng"}}]})
    assert mux.process(str(v), apply=False) == "plan"


def test_a_mux_stamp_counts_as_done_in_sidecar_mode(tmp_path, monkeypatch):
    v, stem = _episode(tmp_path)
    common.write_stamp(stem + common.STAMP_SUFFIX, str(v))
    monkeypatch.setenv("OUTPUT_MODE", "sidecar")
    _never_remux(monkeypatch)
    assert mux.process(str(v), apply=True) == "already-muxed"


def test_generate_skips_a_sidecar_delivered_episode(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_MODE", "sidecar")
    _never_remux(monkeypatch)
    v, _ = _episode(tmp_path)
    assert mux.process(str(v), apply=True) == "sidecar"
    assert generate.process(str(v)) == "already-muxed"
    assert generate.partition_todo([str(v)]) == ([], [])


def test_sidecar_stamp_goes_stale_on_a_text_version_bump(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_MODE", "sidecar")
    _never_remux(monkeypatch)
    v, stem = _episode(tmp_path)
    assert mux.process(str(v), apply=True) == "sidecar"
    monkeypatch.setattr(common, "TEXT_VERSION", common.TEXT_VERSION + 1)
    assert common.stale_tiers(common.read_stamp(stem + common.STAMP_SUFFIX), str(v)) == {"text"}


# --- merge_pass.sh end to end ------------------------------------------------

MERGE_PASS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "merge_pass.sh")


def _fakebin(tmp_path):
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    for name in ("mkvmerge", "ffmpeg"):
        p = d / name
        # mkvmerge would only be reached by a remux: make it loud
        p.write_text("#!/bin/sh\necho RAN-$0 >&2\nexit 1\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(d)


def _fake_app(tmp_path):
    """APP_DIR whose repair.py / dub_signs_merge.py count their calls; everything else is real."""
    real = os.path.dirname(MERGE_PASS)
    app = tmp_path / "app"
    app.mkdir()
    for f in os.listdir(real):
        if f.endswith(".py") and f not in ("repair.py", "dub_signs_merge.py"):
            os.symlink(os.path.join(real, f), app / f)
    for d in ("shell", "data"):
        if os.path.isdir(os.path.join(real, d)):
            os.symlink(os.path.join(real, d), app / d)
    calls = tmp_path / "calls.log"
    for f, stage in (("repair.py", "repair"), ("dub_signs_merge.py", "signs")):
        (app / f).write_text(
            "import sys, common\n"
            f"open({str(calls)!r}, 'a').write({f!r} + '\\n')\n"
            "a = sys.argv[1]\n"
            "stem = a.split('.dubtitles.conf.json')[0].split('.eng.dubtitles.srt')[0]\n"
            f"common.write_stage(stem, {stage!r}, 'ok')\n"
        )
    return str(app), calls


def _merge_pass(tmp_path, root, app, mode):
    env = dict(os.environ)
    env["PATH"] = _fakebin(tmp_path) + os.pathsep + env["PATH"]
    env["MERGE_ROOTS"] = str(root)
    env["APP_DIR"] = app
    env["PYTHONPATH"] = app
    env["OUTPUT_MODE"] = mode
    env["CONFIG_DIR"] = str(tmp_path / "noconfig")
    return subprocess.run(["/bin/sh", MERGE_PASS], env=env, cwd=str(root), capture_output=True, text=True, timeout=120)


def test_merge_pass_sidecar_mode_end_to_end_mp4(tmp_path):
    root = tmp_path / "lib"
    show = root / "Show"
    show.mkdir(parents=True)
    v = show / "ep.mp4"
    v.write_bytes(b"x" * 100)
    (show / ("ep" + mux.SRT_SUFFIX)).write_text(SRT)
    (show / "ep.dubtitles.conf.json").write_text(json.dumps({}))
    app, calls = _fake_app(tmp_path)

    r1 = _merge_pass(tmp_path, root, app, "sidecar")
    assert "MERGE_PASS_DONE new=1" in r1.stdout, r1.stdout + r1.stderr
    assert "RAN-" not in r1.stderr
    assert v.read_bytes() == b"x" * 100
    assert (show / ("ep" + mux.SRT_SUFFIX)).exists()
    assert common.read_stamp(str(show / "ep") + common.STAMP_SUFFIX)["output"] == "sidecar"
    n_calls = len(calls.read_text().splitlines())

    # the second pass must not re-assemble (re-run repair) the sidecar it left behind
    r2 = _merge_pass(tmp_path, root, app, "sidecar")
    assert "MERGE_PASS_DONE new=0" in r2.stdout, r2.stdout + r2.stderr
    assert "### assemble" not in r2.stdout
    assert len(calls.read_text().splitlines()) == n_calls
