import json
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _setup_app(tmp_path, include_exporter=True):
    app = tmp_path / "app"
    (app / "shell").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "shell" / "lib.sh", app / "shell" / "lib.sh")
    shutil.copy(REPO / "review_requests.py", app / "review_requests.py")
    if include_exporter and (REPO / "review_settings_write.py").exists():
        shutil.copy(REPO / "review_settings_write.py", app / "review_settings_write.py")
        if (REPO / "glossary_lock.py").exists():
            shutil.copy(REPO / "glossary_lock.py", app / "glossary_lock.py")
        for module in ("settings_registry.py", "settings_store.py"):
            shutil.copy(REPO / module, app / module)
    (app / "mine_glossary.py").write_text("")
    return app


def _acquire_apply_flags(value):
    """Run gen_loop.sh's own ACQ_FLAGS block with ACQUIRE_APPLY=value (None = unset) -> the resulting flags."""
    src = (REPO / "gen_loop.sh").read_text()
    start = src.index('ACQ_FLAGS=""')
    end = src.index("# acquire_cache", start)
    snippet = src[start:end]
    script = f'{snippet}\nprintf "[%s]" "$ACQ_FLAGS"'
    env = {k: v for k, v in os.environ.items() if k != "ACQUIRE_APPLY"}
    if value is not None:
        env["ACQUIRE_APPLY"] = value
    return subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, check=True).stdout


def test_acquire_apply_off_values_do_not_enable_apply():
    for off in ("0", "false", "False", "NO", "off", "Off", "dry-run", "DRY-RUN", " 0 ", "0 ", "\toff\n"):
        assert _acquire_apply_flags(off) == "[]", f"ACQUIRE_APPLY={off!r} must mean dry-run"


def test_acquire_apply_on_values_enable_apply():
    for on in ("1", "true", "yes", "on", "anything"):
        assert _acquire_apply_flags(on) == "[--apply]", f"ACQUIRE_APPLY={on!r} must mean apply"


def test_acquire_apply_unset_or_empty_means_apply():
    for unset_or_empty in (None, "", "  "):
        assert _acquire_apply_flags(unset_or_empty) == "[--apply]", f"ACQUIRE_APPLY={unset_or_empty!r} must mean apply"


# --- a drained run request runs the same per-show prep as the sweep -------------------------------------------------


def _prep_env(tmp_path, order_text, stubs):
    """An app dir with logging stubs for every stage, a glossary for Frieren, and an env ready for gen_loop.sh.
    `stubs` maps a stage ("mine", "acquire", "verify", "generate") to extra python run after the stage logs itself."""
    app = _setup_app(tmp_path)
    log_file = tmp_path / "stages.log"
    header = f"import os, sys, pathlib\nLOG = r'{log_file}'\n"

    def stub(stage, show_expr, extra=""):
        return header + f"open(LOG, 'a').write('{stage} ' + {show_expr} + '\\n')\n" + extra

    (app / "mine_glossary.py").write_text(stub("mine", "os.path.basename(sys.argv[1])", stubs.get("mine", "")))
    (app / "glossary_acquire.py").write_text(
        stub(
            "acquire",
            "os.path.basename(sys.argv[1])[:-5] + (' apply' if '--apply' in sys.argv else ' dry')",
            stubs.get("acquire", ""),
        )
    )
    (app / "glossary_verify.py").write_text(stub("verify", "os.path.basename(sys.argv[1])[:-5]", stubs.get("verify", "")))
    (app / "generate.py").write_text(stub("generate", "os.environ['SHOW_NAME']", stubs.get("generate", "")))
    config_dir = tmp_path / "config"
    (config_dir / "requests").mkdir(parents=True)
    gloss = tmp_path / "glossaries"
    gloss.mkdir()
    (gloss / "Frieren.json").write_text("{}")
    anime = tmp_path / "anime"
    for name in ("Frieren", "Show1", "Show2"):
        (anime / name).mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text(order_text)
    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS", "ACQUIRE", "ACQUIRE_APPLY")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(config_dir),
        REQUESTS_DIR=str(config_dir / "requests"),
        GLOSSARY_DIR=str(gloss),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
    )
    return env, log_file, config_dir / "requests"


def _write_request(requests_dir, show="Frieren", rid="20261012T100000Z-11111111"):
    path = requests_dir / f"{rid}.json"
    path.write_text(json.dumps({"id": rid, "show": show, "generate_only_re": "E01", "status": "pending"}))
    return path


def _run_gen_loop(env):
    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def test_a_run_request_runs_mine_acquire_verify_then_generate(tmp_path):
    touch_stop = "pathlib.Path(os.environ['STOP_FLAG']).touch()\n"
    stop_on_show1 = f"if os.environ['SHOW_NAME'] == 'Show1':\n    {touch_stop}"
    env, log_file, requests_dir = _prep_env(tmp_path, "Show1\n", {"generate": stop_on_show1})
    req = _write_request(requests_dir)
    _run_gen_loop(env)
    stages = log_file.read_text().splitlines()
    # The request's own pass comes first and is the full sweep recipe (acquire applies by default); then the sweep runs Show1.
    assert stages[:4] == ["mine Frieren", "acquire Frieren apply", "verify Frieren", "generate Frieren"]
    assert json.loads((req.parent / "done" / req.name).read_text())["status"] == "done"


def test_a_soft_stop_during_a_requests_prep_requeues_it_without_generating(tmp_path):
    touch_stop = "if os.path.basename(sys.argv[1]) == 'Frieren':\n    pathlib.Path(os.environ['STOP_FLAG']).touch()\n"
    env, log_file, requests_dir = _prep_env(tmp_path, "Show1\n", {"mine": touch_stop})
    req = _write_request(requests_dir)
    _run_gen_loop(env)
    assert log_file.read_text().splitlines() == ["mine Frieren"]
    assert json.loads(req.read_text())["status"] == "pending", "a stop mid-prep hands the request back, never leaves it running"


def test_a_request_drained_mid_sweep_does_not_disturb_the_sweeps_current_show(tmp_path):
    env, log_file, requests_dir = _prep_env(tmp_path, "Show1\nShow2\n", {})
    # Show1's generate files a request; it is drained at the top of Show2's turn, inside the sweep's read loop.
    (Path(env["APP_DIR"]) / "generate.py").write_text(
        f"""\
import os, json, pathlib
show = os.environ['SHOW_NAME']
open(r'{log_file}', 'a').write('generate ' + show + '\\n')
if show == 'Show1':
    pathlib.Path(r'{requests_dir}/20261012T100000Z-11111111.json').write_text(json.dumps(
        {{"id": "20261012T100000Z-11111111", "show": "Frieren", "generate_only_re": "E01", "status": "pending"}}))
elif show == 'Show2':
    pathlib.Path(os.environ['STOP_FLAG']).touch()
"""
    )
    _run_gen_loop(env)
    stages = log_file.read_text().splitlines()
    assert stages[stages.index("generate Show1") + 1 :] == [
        "mine Frieren",
        "acquire Frieren apply",
        "verify Frieren",
        "generate Frieren",
        "mine Show2",
        "generate Show2",
    ]


def test_the_shell_and_the_registry_agree_on_every_off_spelling():
    import settings_registry as reg

    def registry_applies(raw):
        value, ok = reg.from_env("ACQUIRE_APPLY", raw)
        return reg.REGISTRY["ACQUIRE_APPLY"]["default"] if value is None else (value if ok else True)

    spellings = ("0", "false", "False", "NO", "off", "OFF", "dry-run", "Dry-Run", " dry-run ")
    for spelling in spellings + ("1", "true", "yes", "on", "", "  ", "anything"):
        assert (_acquire_apply_flags(spelling) == "[--apply]") == registry_applies(spelling), repr(spelling)
    assert (_acquire_apply_flags(None) == "[--apply]") == registry_applies(None)


def test_a_stop_already_set_when_a_request_is_claimed_requeues_it_instead_of_exiting(tmp_path):
    env, log_file, requests_dir = _prep_env(tmp_path, "Show1\n", {})
    app = Path(env["APP_DIR"])
    # Raise the stop flag the moment the request is claimed, i.e. after drain_requests' own head check.
    (app / "review_requests_real.py").write_text((app / "review_requests.py").read_text())
    (app / "review_requests.py").write_text(
        "import os, pathlib, runpy, sys\n"
        "if sys.argv[1:2] == ['start']:\n"
        "    pathlib.Path(os.environ['STOP_FLAG']).touch()\n"
        "sys.argv[0] = os.path.join(os.path.dirname(__file__), 'review_requests_real.py')\n"
        "runpy.run_path(sys.argv[0], run_name='__main__')\n"
    )
    req = _write_request(requests_dir)
    _run_gen_loop(env)
    assert not log_file.exists() or log_file.read_text() == "", "no stage may start"
    assert json.loads(req.read_text())["status"] == "pending", "the request goes back to the queue, not left running"


def test_a_hostile_key_in_settings_json_cannot_inject_through_the_gen_loop(tmp_path):
    app = _setup_app(tmp_path)
    runs_file = tmp_path / "runs.jsonl"
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    work = tmp_path / "work"
    work.mkdir()
    (config_dir / "settings.json").write_text(
        json.dumps({"version": 1, "values": {"x; touch PWNED; #": "v", "WHISPER_BEAM_SIZE": 5}})
    )
    (app / "generate.py").write_text(
        f"""\
import os, json, pathlib
with open(r"{runs_file}", "a") as f:
    f.write(json.dumps({{"beam": os.environ.get("WHISPER_BEAM_SIZE")}}) + "\\n")
pathlib.Path(os.environ["STOP_FLAG"]).touch()
"""
    )
    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")
    env = {k: v for k, v in os.environ.items() if k not in ("WHISPER_BEAM_SIZE", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(config_dir),
        REQUESTS_DIR=str(config_dir / "requests"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
    )
    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, cwd=work, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(runs_file.read_text().splitlines()[0])["beam"] == "5"
    for root in (work, config_dir, tmp_path, app):
        assert not (root / "PWNED").exists()
