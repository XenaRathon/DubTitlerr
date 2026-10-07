"""Soft exit at window close: on SIGTERM the container stops STARTING new work, lets the
unit in flight finish, then exits 0. A SIGTERM must never reach gen_loop.sh, merge_pass.sh,
generate.py or mux.py (a killed generate.py leaves a permanent .dubtitles.fail marker).

The pieces: STOP_FLAG (a file) is the only signal. shell/lib.sh and common.py both expose
stop_requested(); container_run.sh is the supervisor that touches the flag on SIGTERM."""

import os
import re
import signal
import subprocess
import sys
import time

import pytest

import common


def _stub_faster_whisper():
    """generate.py imports faster_whisper at module scope; it only exists in the CUDA image."""
    if "faster_whisper" in sys.modules:
        return
    import types

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = object
    sys.modules["faster_whisper"] = fake


_stub_faster_whisper()
import generate  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(REPO, "shell", "lib.sh")
CONTAINER_RUN = os.path.join(REPO, "container_run.sh")
GEN_LOOP = os.path.join(REPO, "gen_loop.sh")


# --- (i) helpers --------------------------------------------------------------------------


def _sh(script, **env):
    e = {k: v for k, v in os.environ.items() if k != "STOP_FLAG"}
    e.update(env)
    return subprocess.run(["sh", "-c", f". {LIB}; {script}"], env=e, capture_output=True, text=True, timeout=30)


def test_shell_stop_requested_false_when_flag_unset():
    assert _sh("stop_requested").returncode == 1


def test_shell_stop_requested_false_when_flag_path_absent(tmp_path):
    assert _sh("stop_requested", STOP_FLAG=str(tmp_path / "nope")).returncode == 1


def test_shell_stop_requested_true_when_flag_exists(tmp_path):
    flag = tmp_path / "stop"
    flag.write_text("")
    assert _sh("stop_requested", STOP_FLAG=str(flag)).returncode == 0


def test_shell_sleep_unless_stopped_returns_early_once_flag_appears(tmp_path):
    flag = tmp_path / "stop"
    flag.write_text("")
    t0 = time.monotonic()
    res = _sh("sleep_unless_stopped 60", STOP_FLAG=str(flag))
    assert time.monotonic() - t0 < 10
    assert res.returncode == 0


def test_shell_sleep_unless_stopped_sleeps_when_no_flag():
    t0 = time.monotonic()
    res = _sh("sleep_unless_stopped 2")
    assert 1.5 <= time.monotonic() - t0 < 8
    assert res.returncode == 0


def test_shell_helpers_are_safe_under_set_e(tmp_path):
    res = _sh("set -e; stop_requested || true; sleep_unless_stopped 1; echo alive", STOP_FLAG=str(tmp_path / "nope"))
    assert res.stdout.strip() == "alive", res


def test_common_stop_requested(tmp_path, monkeypatch):
    monkeypatch.delenv("STOP_FLAG", raising=False)
    assert common.stop_requested() is False
    flag = tmp_path / "stop"
    monkeypatch.setenv("STOP_FLAG", str(flag))
    assert common.stop_requested() is False
    flag.write_text("")
    assert common.stop_requested() is True


# --- (iii) generate.main stops between episodes --------------------------------------------


def test_generate_main_stops_between_episodes_and_returns_normally(tmp_path, monkeypatch):
    flag = tmp_path / "stop"
    monkeypatch.setenv("STOP_FLAG", str(flag))
    monkeypatch.setattr(generate, "GLOSS_DIR", str(tmp_path / "gloss"))
    monkeypatch.setenv("SHOW_NAME", "Stopper")
    vids = []
    for n in ("ep1.mkv", "ep2.mkv"):
        v = tmp_path / n
        v.write_bytes(b"x" * 1000)
        vids.append(str(v))
    monkeypatch.setattr(generate, "WhisperModel", lambda *a, **kw: object())
    seen = []

    def _process(video):
        seen.append(os.path.basename(video))
        flag.write_text("")  # the stop arrives while episode 1 is in flight
        return "ok"

    monkeypatch.setattr(generate, "process", _process)
    marker = tmp_path / "other.dubtitles.fail"  # unrelated poison marker must survive untouched
    marker.write_text("keep")
    monkeypatch.setattr(sys, "argv", ["generate.py", *vids])

    generate.main()  # must return, not sys.exit

    assert seen == ["ep1.mkv"]
    assert marker.read_text() == "keep"
    assert not list(tmp_path.glob("ep*.dubtitles.fail"))
    assert (tmp_path / "gloss" / "Stopper.lastrun.json").exists()


def test_generate_main_does_not_load_the_model_when_stop_already_requested(tmp_path, monkeypatch):
    flag = tmp_path / "stop"
    flag.write_text("")
    monkeypatch.setenv("STOP_FLAG", str(flag))
    monkeypatch.setattr(generate, "GLOSS_DIR", str(tmp_path / "gloss"))
    monkeypatch.setenv("SHOW_NAME", "Stopper")
    v = tmp_path / "ep1.mkv"
    v.write_bytes(b"x" * 1000)

    def _no_model(*a, **kw):
        raise AssertionError("model loaded after stop was requested")

    monkeypatch.setattr(generate, "WhisperModel", _no_model)
    monkeypatch.setattr(generate, "process", lambda video: pytest.fail("episode started after stop"))
    monkeypatch.setattr(sys, "argv", ["generate.py", str(v)])

    generate.main()


# --- (iv) gen_loop.sh static shape -----------------------------------------------------------


def _gen_loop_lines():
    return open(GEN_LOOP).read().splitlines()


def test_gen_loop_has_no_trap_and_no_bare_wait():
    code = [ln for ln in _gen_loop_lines() if not ln.lstrip().startswith("#")]
    assert not [ln for ln in code if re.search(r"(^|[;&|\s])trap\s", ln)], "gen_loop.sh must not trap signals"
    assert not [ln for ln in code if re.search(r"(^|[;&|]\s*)wait(\s|$)", ln)], "gen_loop.sh must not wait"


def test_gen_loop_checks_stop_at_every_loop_head_and_inside_if():
    src = open(GEN_LOOP).read()
    uses = [m.start() for m in re.finditer(r"stop_requested", src)]
    assert len(uses) >= 4, "outer loop, show loop, resume loop and the sleeps all need a stop check"
    for ln in _gen_loop_lines():
        if "stop_requested" in ln and not ln.lstrip().startswith("#") and "stop_requested()" not in ln:
            assert re.match(r"\s*(if|elif)\s", ln) or "||" in ln or "&&" in ln, (
                f"stop check must sit inside if/&&/|| (set -e): {ln!r}"
            )
    assert "sleep 300" not in src and 'sleep "${RESCAN_INTERVAL' not in src, "plain sleeps cannot be interrupted"
    assert "sleep_unless_stopped" in src
    assert "lib.sh" in src


# --- (v) container_run.sh as supervisor --------------------------------------------------------

_STUB_MERGE = """#!/bin/sh
echo "merge_pass ran" >> "$CALLLOG"
"""

_STUB_GEN = """#!/bin/sh
echo "gen_loop started" >> "$CALLLOG"
trap 'echo "gen_loop GOT SIGNAL" >> "$CALLLOG"; exit 99' TERM INT
while :; do
	if [ -e "$STOP_FLAG" ]; then echo "gen_loop saw flag" >> "$CALLLOG"; exit 0; fi
	if [ -e "$GEN_DIE" ]; then echo "gen_loop dying" >> "$CALLLOG"; exit 7; fi
	sleep 1
done
"""

_STUB_REVIEW = """import time, os
open(os.environ["CALLLOG"], "a").write("review started\\n")
while True:
    time.sleep(1)
"""


def _supervisor(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "merge_pass.sh").write_text(_STUB_MERGE)
    (app / "gen_loop.sh").write_text(_STUB_GEN)
    (app / "review_server.py").write_text(_STUB_REVIEW)
    (app / "shell").mkdir()
    (app / "shell" / "lib.sh").write_text(open(LIB).read())
    log = tmp_path / "calls.log"
    log.write_text("")
    flag = tmp_path / "stop.flag"
    env = dict(os.environ)
    env.update(
        APP_DIR=str(app),
        STOP_FLAG=str(flag),
        CALLLOG=str(log),
        GEN_DIE=str(tmp_path / "die"),
        MERGE_INTERVAL="1",
        REVIEW_RESTART="1",
        RESCAN_INTERVAL="1",
        PYTHONPATH=REPO,
    )
    p = subprocess.Popen(
        ["sh", CONTAINER_RUN], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True
    )
    return p, log, flag


def _wait_for(path, text, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if text in path.read_text():
            return True
        time.sleep(0.2)
    return False


def _pgroup_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def _reap(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    p.wait(timeout=10)


def test_supervisor_removes_a_stale_flag_and_soft_stops_on_sigterm(tmp_path):
    flag = tmp_path / "stop.flag"
    flag.write_text("stale from an earlier docker stop")
    p, log, flag = _supervisor(tmp_path)
    try:
        assert _wait_for(log, "gen_loop started"), (log.read_text(), p.poll())
        assert _wait_for(log, "review started")
        assert _wait_for(log, "merge_pass ran")
        assert not flag.exists(), "stale flag must be removed at startup"
        p.send_signal(signal.SIGTERM)
        out, _ = p.communicate(timeout=30)
        assert p.returncode == 0, (p.returncode, out)
        assert "soft stop requested" in out and "soft stop complete" in out, out
        calls = log.read_text()
        assert "gen_loop saw flag" in calls
        assert "GOT SIGNAL" not in calls, "gen_loop must never be signalled"
        time.sleep(0.5)
        assert not _pgroup_alive(p.pid), "leftover child processes"
    finally:
        _reap(p)


def test_supervisor_fails_loud_when_gen_loop_dies_on_its_own(tmp_path):
    p, log, flag = _supervisor(tmp_path)
    try:
        assert _wait_for(log, "gen_loop started")
        assert _wait_for(log, "review started")
        (tmp_path / "die").write_text("")
        out, _ = p.communicate(timeout=30)
        assert p.returncode == 7, (p.returncode, out)
        assert "soft stop complete" not in out
        time.sleep(0.5)
        assert not _pgroup_alive(p.pid), "merge/review loops must be killed too"
    finally:
        _reap(p)


# --- gen_loop.sh runtime: the per-show prep steps honour the stop flag ----------------------

_STUB_PY = """import os, sys
name = {name!r}
if name == "generate":
    show = os.environ["SHOW_NAME"]
else:
    show = os.path.basename(sys.argv[-1])
    if show.endswith(".json"):
        show = show[:-5]
with open(os.environ["CALLLOG"], "a") as f:
    f.write(name + " " + show + "\\n")
if os.environ.get("STOP_AFTER") == name + ":" + show:
    open(os.environ["STOP_FLAG"], "w").close()
"""


def _gen_loop_run(tmp_path, stop_after=None):
    app = tmp_path / "app"
    (app / "shell").mkdir(parents=True)
    (app / "shell" / "lib.sh").write_text(open(LIB).read())
    for name, script in (
        ("mine", "mine_glossary.py"),
        ("acquire", "glossary_acquire.py"),
        ("verify", "glossary_verify.py"),
        ("generate", "generate.py"),
    ):
        (app / script).write_text(_STUB_PY.format(name=name))
    anime, gloss = tmp_path / "anime", tmp_path / "gloss"
    gloss.mkdir()
    for show in ("Show1", "Show2"):
        (anime / show).mkdir(parents=True)
        (gloss / (show + ".json")).write_text("{}")
    order = tmp_path / "order.txt"
    order.write_text("Show1\nShow2\n")
    log = tmp_path / "calls.log"
    log.write_text("")
    env = dict(os.environ)
    env.pop("WATCH_QUEUE_WINDOW_DAYS", None)
    env.update(
        APP_DIR=str(app),
        ANIME_ORDER=str(order),
        ANIME_ROOT=str(anime),
        GLOSSARY_DIR=str(gloss),
        STOP_FLAG=str(tmp_path / "stop.flag"),
        CALLLOG=str(log),
        RESCAN_INTERVAL="1",
    )
    if stop_after:
        env["STOP_AFTER"] = stop_after
    res = subprocess.run(["sh", GEN_LOOP], env=env, capture_output=True, text=True, timeout=60)
    return res, log.read_text().split("\n")[:-1]


def test_stop_during_mine_skips_acquire_verify_generate_and_the_next_show(tmp_path):
    res, calls = _gen_loop_run(tmp_path, stop_after="mine:Show1")
    assert res.returncode == 0, (res.stdout, res.stderr)
    assert calls == ["mine Show1"], calls


def test_stop_during_acquire_skips_verify_and_generate(tmp_path):
    res, calls = _gen_loop_run(tmp_path, stop_after="acquire:Show1")
    assert res.returncode == 0, (res.stdout, res.stderr)
    assert calls == ["mine Show1", "acquire Show1"], calls


def test_stop_during_verify_skips_generate(tmp_path):
    res, calls = _gen_loop_run(tmp_path, stop_after="verify:Show1")
    assert res.returncode == 0, (res.stdout, res.stderr)
    assert calls == ["mine Show1", "acquire Show1", "verify Show1"], calls


def test_gen_loop_without_a_stop_runs_the_whole_sequence_for_both_shows(tmp_path):
    # guard: the stop is raised only after the last generate, so the idle wait ends the script
    res, calls = _gen_loop_run(tmp_path, stop_after="generate:Show2")
    assert res.returncode == 0, (res.stdout, res.stderr)
    assert calls == [
        "mine Show1", "acquire Show1", "verify Show1", "generate Show1",
        "mine Show2", "acquire Show2", "verify Show2", "generate Show2",
    ], calls


# --- sleep_unless_stopped with arguments that are not whole seconds ---------------------------


@pytest.mark.parametrize("arg", ["0.3", "1s", ""])
def test_sleep_unless_stopped_non_integer_argument_falls_back_to_plain_sleep(arg):
    t0 = time.monotonic()
    res = _sh(f"sleep_unless_stopped '{arg}'; echo rc=$?")
    took = time.monotonic() - t0
    assert "rc=0" in res.stdout, res
    if arg:
        assert took >= 0.25, f"returned immediately for {arg!r} (loops would spin): {took}"


def test_sleep_unless_stopped_integer_still_returns_early_on_flag(tmp_path):
    flag = tmp_path / "stop"
    flag.write_text("")
    t0 = time.monotonic()
    assert _sh("sleep_unless_stopped 30", STOP_FLAG=str(flag)).returncode == 0
    assert time.monotonic() - t0 < 5
