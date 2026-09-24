"""[S-7] merge_pass.sh's fail-closed exit-code capture and final COMPLETE/INCOMPLETE
messaging (v0-2-0-hardening spec, Story S-7).

The per-stem loop is a pipe into `while` (`merge_pass.sh:46-73`), which runs in a
SUBSHELL under /bin/sh -- nothing incremented inside it survives past `done`. These
tests seed `.dubtitles.stages.json` sidecars directly (no real transcode/repair/mux
involved) and drive the real script end-to-end via subprocess, stubbing only the two
binary-presence checks (`mkvmerge`, which is not installed on this dev box) so the
script reaches its own logic instead of exiting at the FATAL guard."""

import os
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
