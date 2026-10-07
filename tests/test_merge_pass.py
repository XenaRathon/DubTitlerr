"""[S-7] merge_pass.sh's fail-closed exit-code capture and final COMPLETE/INCOMPLETE
messaging (v0-2-0-hardening spec, Story S-7).

The per-stem loop is a pipe into `while` (`merge_pass.sh:46-73`), which runs in a
SUBSHELL under /bin/sh -- nothing incremented inside it survives past `done`. These
tests seed `.dubtitles.stages.json` sidecars directly (no real transcode/repair/mux
involved) and drive the real script end-to-end via subprocess, stubbing only the two
binary-presence checks (`mkvmerge`, which is not installed on this dev box) so the
script reaches its own logic instead of exiting at the FATAL guard."""

import os
import shlex
import stat
import subprocess
import sys

import common

MERGE_PASS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "merge_pass.sh")


def _fake_bin(tmp_path, name):
    """A stub executable on PATH so merge_pass.sh's `command -v` guards pass."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    p = bindir / name
    p.write_text("#!/bin/sh\nexit 0\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(bindir)


def _run(tmp_path, root):
    # merge_pass.sh guards check ffmpeg (line 16), mkvmerge (line 20), and pysubs2 import (line 24).
    # We stub the binaries; pysubs2 resolves via the real sys.path in CI.
    fakebin_mkvmerge = _fake_bin(tmp_path, "mkvmerge")
    fakebin_ffmpeg = _fake_bin(tmp_path, "ffmpeg")
    env = dict(os.environ)
    env["PATH"] = fakebin_mkvmerge + os.pathsep + fakebin_ffmpeg + os.pathsep + env["PATH"]
    env["MERGE_ROOTS"] = str(root)
    env["APP_DIR"] = os.path.dirname(MERGE_PASS)
    return subprocess.run(
        ["/bin/sh", MERGE_PASS],
        env=env,
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_zero_failed_stages_prints_exactly_merge_pass_complete(tmp_path, monkeypatch):
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setattr(common, "OUTPUT_ROOT", "")
    stem = str(root / "Show" / "ep01")
    os.makedirs(os.path.dirname(stem), exist_ok=True)
    common.write_stage(stem, "repair", "ok")
    common.write_stage(stem, "signs", "ok")
    common.write_stage(stem, "mux", "ok")

    res = _run(tmp_path, root)
    assert "MERGE PASS COMPLETE" in res.stdout, res.stdout + res.stderr
    assert "MERGE PASS INCOMPLETE" not in res.stdout


def test_one_failed_stage_of_two_episodes_prints_incomplete_with_count(tmp_path, monkeypatch):
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setattr(common, "OUTPUT_ROOT", "")
    ok_stem = str(root / "Show" / "ep01")
    bad_stem = str(root / "Show" / "ep02")
    os.makedirs(os.path.dirname(ok_stem), exist_ok=True)
    common.write_stage(ok_stem, "repair", "ok")
    common.write_stage(ok_stem, "signs", "ok")
    common.write_stage(ok_stem, "mux", "ok")
    common.write_stage(bad_stem, "repair", "backend-unreachable")

    res = _run(tmp_path, root)
    assert "MERGE PASS INCOMPLETE: 1 episodes with a failed stage" in res.stdout, res.stdout + res.stderr


def test_crashed_record_written_only_when_stage_left_none(tmp_path):
    """merge_pass.sh's inline python3 -c writes a 'crashed' record for rc!=0 ONLY when the
    stage itself left no record -- a stage that already recorded its own real outcome (e.g.
    repair.py writing 'no-reference' then exiting non-zero for an unrelated reason) must not
    be clobbered with a less informative 'crashed'."""
    stem = str(tmp_path / "ep")
    common.write_stage(stem, "repair", "no-reference")
    # simulate the exact guard merge_pass.sh runs after a non-zero rc
    subprocess.run(
        [
            sys.executable,
            "-c",
            f"import common,sys; s={stem!r}; "
            "sys.exit(0 if 'repair' in common.read_stages(s) else common.write_stage(s, 'repair', 'crashed', 'rc=1') or 1)",
        ],
        cwd=os.path.dirname(MERGE_PASS),
        check=False,
    )
    assert common.read_stages(stem)["repair"]["outcome"] == "no-reference"

    stem2 = str(tmp_path / "ep2")
    subprocess.run(
        [
            sys.executable,
            "-c",
            f"import common,sys; s={stem2!r}; "
            "sys.exit(0 if 'repair' in common.read_stages(s) else common.write_stage(s, 'repair', 'crashed', 'rc=1') or 1)",
        ],
        cwd=os.path.dirname(MERGE_PASS),
        check=False,
    )
    assert common.read_stages(stem2)["repair"]["outcome"] == "crashed"


def test_apostrophe_stem_records_real_crash_fallback(tmp_path, monkeypatch):
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setattr(common, "OUTPUT_ROOT", "")
    monkeypatch.setenv("OUTPUT_ROOT", "")

    stem = str(root / "JoJo's Bizarre Adventure" / "S01E01")
    os.makedirs(os.path.dirname(stem), exist_ok=True)
    for suffix in (".eng.dubtitles.ass", ".mkv"):
        with open(stem + suffix, "w"):
            pass

    _fake_bin(tmp_path, "ffmpeg")
    bindir = tmp_path / "fakebin"
    wrapper = bindir / "python3"
    wrapper.write_text(
        f'#!/bin/sh\ncase "$1" in\n  */mux.py) [ "$2" = "--apply" ] && exit 1 ;;\nesac\nexec {shlex.quote(sys.executable)} "$@"\n'
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    res = _run(tmp_path, root)
    stages = common.read_stages(stem)
    record = stages.get("mux", {})
    output = res.stdout + res.stderr

    assert "SyntaxError" not in output, output
    assert record.get("outcome") == "crashed", (output, stages)
    assert record.get("detail") == "rc=1", (output, stages)
    assert common.failed_stage(stem) == "mux", stages
    assert "MERGE PASS INCOMPLETE" in res.stdout, output


# --- stage gating: a failed repair/signs must not be muxed -------------------------------
#
# These drive the real merge_pass.sh against a stub APP_DIR whose repair/signs/mux scripts
# log every call and record the stage outcome the env asks for. The real common.py is reached
# through PYTHONPATH, so stage records, failed_stage() and clear_stage() are the real ones.

_REPO = os.path.dirname(MERGE_PASS)

_STUB = """\
import os, sys
sys.path.insert(0, {repo!r})
import common
common.OUTPUT_ROOT = ""
name = {name!r}
arg = sys.argv[-1]
for suffix in (".dubtitles.conf.json", ".eng.dubtitles.srt", ".mkv", ".mp4"):
    if arg.endswith(suffix):
        stem = arg[: -len(suffix)]
        break
with open(os.environ["CALLLOG"], "a") as f:
    f.write(name + " " + os.path.basename(stem) + "\\n")
mode = os.environ.get("STUB_" + name.upper(), "ok")
if mode == "exit3":  # dies without recording anything
    sys.exit(3)
if mode != "ok":
    common.write_stage(stem, name, mode)
    sys.exit(0)
common.write_stage(stem, name, "ok")
if name == "signs":
    open(stem + ".eng.dubtitles.ass", "w").close()
    os.remove(stem + ".eng.dubtitles.srt")
"""


def _stub_app(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    for name, script in (("repair", "repair.py"), ("signs", "dub_signs_merge.py"), ("mux", "mux.py")):
        (app / script).write_text(_STUB.format(repo=_REPO, name=name))
    return app


def _episode(tmp_path, with_ass=False):
    root = tmp_path / "library"
    stem = root / "Show" / "ep01"
    stem.parent.mkdir(parents=True)
    (tmp_path / "calls.log").write_text("")
    (stem.parent / "ep01.mkv").write_text("")
    (stem.parent / "ep01.eng.dubtitles.srt").write_text("")
    if with_ass:
        (stem.parent / "ep01.eng.dubtitles.ass").write_text("")
    return root, str(stem)


def _gated_run(tmp_path, root, **stub_modes):
    app = _stub_app(tmp_path) if not (tmp_path / "app").exists() else tmp_path / "app"
    bindir = _fake_bin(tmp_path, "mkvmerge")
    _fake_bin(tmp_path, "ffmpeg")
    env = dict(os.environ)
    env["PATH"] = bindir + os.pathsep + env["PATH"]
    env.update(MERGE_ROOTS=str(root), APP_DIR=str(app), PYTHONPATH=_REPO, CALLLOG=str(tmp_path / "calls.log"))
    for k, v in stub_modes.items():
        env["STUB_" + k.upper()] = v
    res = subprocess.run(["/bin/sh", MERGE_PASS], env=env, cwd=str(root), capture_output=True, text=True, timeout=60)
    return res, (tmp_path / "calls.log").read_text().split("\n")[:-1]


def test_failed_repair_skips_signs_and_mux_and_the_stem_is_retried(tmp_path):
    root, stem = _episode(tmp_path)
    res, calls = _gated_run(tmp_path, root, repair="backend-unreachable")
    assert calls == ["repair ep01"], (calls, res.stdout, res.stderr)
    assert "skip mux: repair failed (backend-unreachable)" in res.stdout
    assert "MERGE PASS INCOMPLETE" in res.stdout
    # the srt is still there and no .ass exists, so the next pass retries
    res2, calls2 = _gated_run(tmp_path, root, repair="backend-unreachable")
    assert calls2 == ["repair ep01", "repair ep01"], calls2


def test_a_repair_that_dies_silently_is_not_masked_by_a_stale_ok_record(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "OUTPUT_ROOT", "")
    root, stem = _episode(tmp_path)
    common.write_stage(stem, "repair", "ok")  # stale, from an older run
    res, calls = _gated_run(tmp_path, root, repair="exit3")
    assert calls == ["repair ep01"], (calls, res.stdout, res.stderr)
    assert common.read_stages(stem)["repair"]["outcome"] == "crashed"


def test_failed_signs_skips_mux(tmp_path):
    root, stem = _episode(tmp_path)
    res, calls = _gated_run(tmp_path, root, signs="build-error")
    assert calls == ["repair ep01", "signs ep01"], (calls, res.stdout, res.stderr)
    assert "skip mux: signs failed (build-error)" in res.stdout
    res2, calls2 = _gated_run(tmp_path, root, signs="build-error")
    assert calls2[2:] == ["repair ep01", "signs ep01"], "the next pass must retry from repair"


def test_repair_and_signs_passing_runs_mux(tmp_path):
    root, stem = _episode(tmp_path)
    res, calls = _gated_run(tmp_path, root)
    assert calls == ["repair ep01", "signs ep01", "mux ep01"], (calls, res.stdout, res.stderr)


def test_existing_ass_runs_mux_even_with_an_old_failure_record(tmp_path, monkeypatch):
    """Guard: stale records must never block mux when the assemble block did not run, or the
    episode would be stuck forever with no retry path."""
    monkeypatch.setattr(common, "OUTPUT_ROOT", "")
    root, stem = _episode(tmp_path, with_ass=True)
    common.write_stage(stem, "repair", "crashed")
    common.write_stage(stem, "signs", "build-error")
    res, calls = _gated_run(tmp_path, root)
    assert calls == ["mux ep01"], (calls, res.stdout, res.stderr)


def test_mux_that_dies_silently_is_recorded_crashed_despite_a_stale_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "OUTPUT_ROOT", "")
    root, stem = _episode(tmp_path, with_ass=True)
    common.write_stage(stem, "mux", "ok")  # stale
    res, calls = _gated_run(tmp_path, root, mux="exit3")
    assert calls == ["mux ep01"]
    rec = common.read_stages(stem)["mux"]
    assert (rec["outcome"], rec.get("detail")) == ("crashed", "rc=3"), (rec, res.stdout, res.stderr)


def test_a_failed_stage_scan_never_prints_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "OUTPUT_ROOT", "")
    root = tmp_path / "library"
    stem = str(root / "Show" / "ep01")
    os.makedirs(os.path.dirname(stem))
    common.write_stage(stem, "repair", "ok")
    bindir = _fake_bin(tmp_path, "ffmpeg")
    wrapper = tmp_path / "fakebin" / "python3"
    wrapper.write_text(
        f'#!/bin/sh\ncase "$2" in *failed_stage*) exit 1 ;;\nesac\nexec {shlex.quote(sys.executable)} "$@"\n'
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    res = _run(tmp_path, root)
    assert "MERGE PASS COMPLETE" not in res.stdout, res.stdout + res.stderr
    assert "MERGE PASS INCOMPLETE: failed-stage scan error" in res.stdout
    assert "MERGE_PASS_DONE" in res.stdout
