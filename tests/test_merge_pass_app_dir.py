"""#39: merge_pass.sh run by hand (no APP_DIR) must find its own stages, and a wrong APP_DIR
must fail as a configuration error, never as a repair "crashed" stage record."""

import os
import shutil
import stat
import subprocess

import common

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRT = "1\n00:00:00,000 --> 00:00:01,000\nhi\n"


def _env(tmp_path, root, **extra):
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    for name in ("mkvmerge", "ffmpeg"):
        p = d / name
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    env = {k: v for k, v in os.environ.items() if k != "APP_DIR"}
    env.update(PATH=str(d) + os.pathsep + env["PATH"], MERGE_ROOTS=str(root), CONFIG_DIR=str(tmp_path / "nocfg"), **extra)
    return env


def _library(tmp_path):
    root = tmp_path / "lib"
    (root / "Show").mkdir(parents=True)
    (root / "Show" / "ep01.eng.dubtitles.srt").write_text(SRT)
    return root, str(root / "Show" / "ep01")


def test_wrong_app_dir_is_fatal_and_records_no_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "OUTPUT_ROOT", "")
    root, stem = _library(tmp_path)
    empty = tmp_path / "scripts"
    empty.mkdir()
    r = subprocess.run(
        ["/bin/sh", os.path.join(REPO, "merge_pass.sh")],
        env=_env(tmp_path, root, APP_DIR=str(empty), PYTHONPATH=REPO),
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FATAL:" in r.stdout and "repair.py not found" in r.stdout
    assert "### assemble" not in r.stdout
    assert common.read_stages(stem) == {}


def test_without_app_dir_the_scripts_own_directory_is_used(tmp_path, monkeypatch):
    """Copy the script next to stub stages, as /app/merge_pass.sh sits next to /app/repair.py."""
    monkeypatch.setattr(common, "OUTPUT_ROOT", "")
    root, stem = _library(tmp_path)
    app = tmp_path / "app"
    app.mkdir()
    shutil.copy(os.path.join(REPO, "merge_pass.sh"), app / "merge_pass.sh")
    shutil.copy(os.path.join(REPO, "common.py"), app / "common.py")
    calls = tmp_path / "calls.log"
    for f in ("repair.py", "dub_signs_merge.py", "mux.py"):
        (app / f).write_text(f"open({str(calls)!r}, 'a').write({f!r} + '\\n')\nraise SystemExit(1)\n")
    r = subprocess.run(
        ["/bin/sh", str(app / "merge_pass.sh")],
        env=_env(tmp_path, root),
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "can't open file" not in r.stderr, r.stderr
    assert "repair.py" in calls.read_text(), r.stdout + r.stderr
