import datetime
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _setup_app(tmp_path):
    app = tmp_path / "app"
    (app / "shell").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "shell" / "lib.sh", app / "shell" / "lib.sh")
    shutil.copy(REPO / "review_requests.py", app / "review_requests.py")
    (app / "mine_glossary.py").write_text("")
    return app


def test_pending_request_runs_with_env_and_moves_to_done(tmp_path):
    # Mutation caught: requests not drained, SHOW_NAME/GENERATE_ONLY_RE/REQUIRE_ENG
    # not passed to generate.py, or request not marked done on success.
    app = _setup_app(tmp_path)
    record = tmp_path / "record.json"
    stub_generate = f"""\
import os, json, pathlib
data = {{
    "SHOW_NAME": os.environ.get("SHOW_NAME"),
    "GENERATE_ONLY_RE": os.environ.get("GENERATE_ONLY_RE"),
    "REQUIRE_ENG": os.environ.get("REQUIRE_ENG"),
}}
if os.environ.get("GENERATE_ONLY_RE"):
    pathlib.Path(r"{record}").write_text(json.dumps(data))
else:
    pathlib.Path(os.environ["STOP_FLAG"]).touch()
"""
    (app / "generate.py").write_text(stub_generate)

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    requests_dir = tmp_path / "config" / "requests"
    requests_dir.mkdir(parents=True)
    req_file = requests_dir / "20261012T100000Z-11111111.json"
    req_file.write_text(
        json.dumps({
            "id": "20261012T100000Z-11111111",
            "show": "Frieren",
            "season": 1,
            "episode_re": "E01",
            "generate_only_re": r"Frieren.*S01E01",
            "require_eng": 0,
            "status": "pending",
        })
    )

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(tmp_path / "config"),
        REQUESTS_DIR=str(requests_dir),
        GLOSSARY_DIR=str(tmp_path / "gloss"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # Check generate ran with request parameters
    rec = json.loads(record.read_text())
    assert rec["SHOW_NAME"] == "Frieren"
    assert rec["GENERATE_ONLY_RE"] == r"Frieren.*S01E01"
    assert rec["REQUIRE_ENG"] == "0"

    # Request moved to done/
    done_file = requests_dir / "done" / "20261012T100000Z-11111111.json"
    assert done_file.exists()
    assert not req_file.exists()
    data = json.loads(done_file.read_text())
    assert data["status"] == "done"


def test_failing_request_moves_to_failed_and_loop_continues(tmp_path):
    # Mutation caught: generate failure trips set -e killing gen_loop,
    # or failing request is not moved to failed/ with error details.
    app = _setup_app(tmp_path)
    count_file = tmp_path / "count"
    count_file.write_text("0")

    stub_generate = f"""\
import os, pathlib, sys
cpath = pathlib.Path(r"{count_file}")
c = int(cpath.read_text()) + 1
cpath.write_text(str(c))
if os.environ.get("GENERATE_ONLY_RE"):
    sys.exit(2) # Fail the request pass
pathlib.Path(os.environ["STOP_FLAG"]).touch()
"""
    (app / "generate.py").write_text(stub_generate)

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    requests_dir = tmp_path / "config" / "requests"
    requests_dir.mkdir(parents=True)
    req_file = requests_dir / "20261012T100000Z-22222222.json"
    req_file.write_text(
        json.dumps({
            "id": "20261012T100000Z-22222222",
            "show": "Frieren",
            "season": 1,
            "episode_re": "E01",
            "generate_only_re": r"Frieren.*S01E01",
            "require_eng": 1,
            "status": "pending",
        })
    )

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(tmp_path / "config"),
        REQUESTS_DIR=str(requests_dir),
        GLOSSARY_DIR=str(tmp_path / "gloss"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # Failing request moved to failed/
    failed_file = requests_dir / "failed" / "20261012T100000Z-22222222.json"
    assert failed_file.exists()
    assert not req_file.exists()
    data = json.loads(failed_file.read_text())
    assert data["status"] == "failed"
    assert "rc=2" in str(data.get("error"))

    # The regular show sweep ran after request failure
    assert int(count_file.read_text()) >= 2


def test_window_closed_holds_request(tmp_path):
    # Mutation caught: requests run while schedule window is closed,
    # violating quiet-hours / schedule-window constraint.
    app = _setup_app(tmp_path)
    record = tmp_path / "record"
    stub_generate = f"""\
import os, pathlib
pathlib.Path(r"{record}").write_text("ran")
pathlib.Path(os.environ["STOP_FLAG"]).touch()
"""
    (app / "generate.py").write_text(stub_generate)

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    config_dir = tmp_path / "config"
    requests_dir = config_dir / "requests"
    requests_dir.mkdir(parents=True)
    req_file = requests_dir / "20261012T100000Z-33333333.json"
    req_file.write_text(
        json.dumps({
            "id": "20261012T100000Z-33333333",
            "show": "Frieren",
            "generate_only_re": r"Frieren.*S01E01",
            "status": "pending",
        })
    )

    # Schedule window closed: 00:00 to 00:01 in UTC
    schedule_file = config_dir / "schedule.json"
    schedule_file.write_text(
        json.dumps({
            "enabled": True,
            "open": "00:00",
            "close": "00:01",
            "tz": "UTC",
        })
    )

    stop_file = tmp_path / "stop"

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(config_dir),
        REQUESTS_DIR=str(requests_dir),
        SCHEDULE_FILE=str(schedule_file),
        SCHEDULE_CHECK_INTERVAL="1",
        GLOSSARY_DIR=str(tmp_path / "gloss"),
        STOP_FLAG=str(stop_file),
        RESCAN_INTERVAL="0",
    )

    proc = subprocess.Popen(["sh", str(REPO / "gen_loop.sh")], env=env)
    try:
        time.sleep(1.0)
    finally:
        stop_file.touch()
        proc.wait(timeout=10)
        if proc.poll() is None:
            proc.kill()

    assert proc.returncode == 0
    # Request still pending because window is closed!
    assert req_file.exists()
    assert not (requests_dir / "done" / "20261012T100000Z-33333333.json").exists()


def test_schedule_closed_starts_no_work(tmp_path):
    # Decision 1: When schedule.json is enabled and the window is closed,
    # the loop must start no NEW work at all (neither requests nor show sweep).
    app = _setup_app(tmp_path)
    call_log = tmp_path / "calls.txt"
    stub_generate = f"""\
import pathlib
pathlib.Path(r"{call_log}").write_text("called")
"""
    (app / "generate.py").write_text(stub_generate)

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    config_dir = tmp_path / "config"
    requests_dir = config_dir / "requests"
    requests_dir.mkdir(parents=True)

    # Calculate open and closed windows relative to now in UTC
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    closed_open = (now_utc + datetime.timedelta(hours=2)).strftime("%H:%M")
    closed_close = (now_utc + datetime.timedelta(hours=3)).strftime("%H:%M")
    open_open = (now_utc - datetime.timedelta(hours=2)).strftime("%H:%M")
    open_close = (now_utc + datetime.timedelta(hours=2)).strftime("%H:%M")

    # Schedule window closed
    schedule_file = config_dir / "schedule.json"
    schedule_file.write_text(
        json.dumps({
            "enabled": True,
            "open": closed_open,
            "close": closed_close,
            "tz": "UTC",
        })
    )

    stop_file = tmp_path / "stop"

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(config_dir),
        REQUESTS_DIR=str(requests_dir),
        SCHEDULE_FILE=str(schedule_file),
        SCHEDULE_CHECK_INTERVAL="1",
        STOP_FLAG=str(stop_file),
        RESCAN_INTERVAL="0",
    )

    proc = subprocess.Popen(["sh", str(REPO / "gen_loop.sh")], env=env)
    try:
        # Loop sleeps when closed; verify no work was started
        time.sleep(1.5)
        assert not call_log.exists(), "generate.py was called while window was closed"

        # Open the schedule window and verify generate.py IS called
        schedule_file.write_text(
            json.dumps({
                "enabled": True,
                "open": open_open,
                "close": open_close,
                "tz": "UTC",
            })
        )
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if call_log.exists():
                break
            time.sleep(0.05)
        assert call_log.exists(), "generate.py was not called within 30s after opening window"
    finally:
        stop_file.touch()
        proc.wait(timeout=10)
        if proc.poll() is None:
            proc.kill()


def test_idle_wait_pickup(tmp_path):
    # Decision 2: The request file appears while the loop is idle;
    # verify it runs within REQUEST_POLL_INTERVAL.
    app = _setup_app(tmp_path)
    sweep_marker = tmp_path / "sweep_marker"
    record = tmp_path / "record"
    stub_generate = f"""\
import os, pathlib
if os.environ.get("GENERATE_ONLY_RE"):
    pathlib.Path(r"{record}").write_text("request_ran")
else:
    pathlib.Path(r"{sweep_marker}").write_text("sweep_done")
"""
    (app / "generate.py").write_text(stub_generate)

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    requests_dir = tmp_path / "config" / "requests"
    requests_dir.mkdir(parents=True)

    stop_file = tmp_path / "stop"

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(tmp_path / "config"),
        REQUESTS_DIR=str(requests_dir),
        GLOSSARY_DIR=str(tmp_path / "gloss"),
        STOP_FLAG=str(stop_file),
        RESCAN_INTERVAL="120",
        REQUEST_POLL_INTERVAL="1",
    )

    proc = subprocess.Popen(["sh", str(REPO / "gen_loop.sh")], env=env)
    try:
        # Wait until the initial show sweep is done and loop is IDLE
        sweep_deadline = time.monotonic() + 30.0
        while time.monotonic() < sweep_deadline:
            if sweep_marker.exists():
                break
            time.sleep(0.05)
        assert sweep_marker.exists(), "initial show sweep did not complete within 30s"

        # Submit request WHILE loop is idle
        req_file = requests_dir / "20261012T100000Z-44444444.json"
        req_file.write_text(
            json.dumps({
                "id": "20261012T100000Z-44444444",
                "show": "Frieren",
                "generate_only_re": r"Frieren.*S01E01",
                "status": "pending",
            })
        )

        # Poll for request completion with a generous deadline (30s)
        done_file = requests_dir / "done" / "20261012T100000Z-44444444.json"
        done_deadline = time.monotonic() + 30.0
        while time.monotonic() < done_deadline:
            if done_file.exists():
                break
            time.sleep(0.05)
        assert done_file.exists(), f"request did not finish within 30s deadline: {done_file} not found"
        assert record.read_text() == "request_ran"
    finally:
        stop_file.touch()
        proc.wait(timeout=10)
        if proc.poll() is None:
            proc.kill()


def test_effective_env_content_and_masking(tmp_path):
    # Mutation caught: effective.env not written at sweep start or
    # secret environment variables leaked into effective.env.
    app = _setup_app(tmp_path)
    (app / "generate.py").write_text("""\
import os, pathlib
pathlib.Path(os.environ["STOP_FLAG"]).touch()
""")

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    effective_env_file = config_dir / "effective.env"

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(config_dir),
        EFFECTIVE_ENV_FILE=str(effective_env_file),
        GLOSSARY_DIR=str(tmp_path / "gloss"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
        REPAIR_MODEL="qwen3-4b-instruct",
        REPAIR_OPENAI_API_KEY="sk-secret123",
        WEBHOOK_TOKEN="supersecret",
        REQUIRE_ENG="1",
        GLOSSARY_ARC_TAGS="1",
        SECRET_TOKEN_PASSWORD="bad",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    assert effective_env_file.exists()
    content = effective_env_file.read_text()
    assert "REPAIR_MODEL=qwen3-4b-instruct" in content
    assert "REQUIRE_ENG=1" in content
    assert "GLOSSARY_ARC_TAGS=1" in content
    # Secrets must NEVER be leaked
    assert "sk-secret123" not in content
    assert "REPAIR_OPENAI_API_KEY" not in content
    assert "WEBHOOK_TOKEN" not in content
    assert "SECRET_TOKEN_PASSWORD" not in content


def test_recovery_of_running_file(tmp_path):
    # Mutation caught: interrupted/crashed .running file is not moved to
    # failed/ with 'interrupted by restart' on startup.
    app = _setup_app(tmp_path)
    (app / "generate.py").write_text("""\
import os, pathlib
pathlib.Path(os.environ["STOP_FLAG"]).touch()
""")

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    requests_dir = tmp_path / "config" / "requests"
    requests_dir.mkdir(parents=True)
    running_file = requests_dir / "20261012T100000Z-55555555.running"
    running_file.write_text(
        json.dumps({
            "id": "20261012T100000Z-55555555",
            "show": "Frieren",
            "status": "running",
        })
    )

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(tmp_path / "config"),
        REQUESTS_DIR=str(requests_dir),
        GLOSSARY_DIR=str(tmp_path / "gloss"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # .running was moved to failed/
    assert not running_file.exists()
    failed_file = requests_dir / "failed" / "20261012T100000Z-55555555.json"
    assert failed_file.exists()
    data = json.loads(failed_file.read_text())
    assert data["status"] == "failed"
    assert data["error"] == "interrupted by restart"


def test_hostile_show_name_rejected_by_loop(tmp_path):
    # Mutation caught: hostile show name with newline/PATH injection
    # executes in shell or passes into gen_loop without rejection.
    app = _setup_app(tmp_path)
    (app / "generate.py").write_text("""\
import os, pathlib
pathlib.Path(os.environ["STOP_FLAG"]).touch()
""")

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    requests_dir = tmp_path / "config" / "requests"
    requests_dir.mkdir(parents=True)
    hostile_file = requests_dir / "20261012T100000Z-66666666.json"
    hostile_file.write_text(
        json.dumps({
            "id": "20261012T100000Z-66666666",
            "show": "Frieren\nPATH=/evil",
            "generate_only_re": r"Frieren.*S01E01",
            "status": "pending",
        })
    )

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(tmp_path / "config"),
        REQUESTS_DIR=str(requests_dir),
        GLOSSARY_DIR=str(tmp_path / "gloss"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # Hostile request moved to failed/ and never executed
    assert not hostile_file.exists()
    failed_file = requests_dir / "failed" / "20261012T100000Z-66666666.json"
    assert failed_file.exists()
    data = json.loads(failed_file.read_text())
    assert data["status"] == "failed"
    assert data.get("error") == "invalid request file"


def test_claim_failure_skips_request(tmp_path):
    # Decision 4: A request that cannot be claimed (start returns non-zero)
    # must be skipped, not executed.
    app = _setup_app(tmp_path)
    real_rr = REPO / "review_requests.py"
    (app / "review_requests.py").write_text(f"""\
import sys, pathlib, subprocess
if len(sys.argv) > 1 and sys.argv[1] == "start":
    pathlib.Path(sys.argv[2]).unlink(missing_ok=True)
    sys.exit(1)
res = subprocess.run([sys.executable, "{real_rr}"] + sys.argv[1:])
sys.exit(res.returncode)
""")

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    requests_dir = tmp_path / "config" / "requests"
    requests_dir.mkdir(parents=True)
    req_file = requests_dir / "20261012T100000Z-77777777.json"
    req_file.write_text(
        json.dumps({
            "id": "20261012T100000Z-77777777",
            "show": "Frieren",
            "generate_only_re": r"Frieren.*S01E01",
            "status": "pending",
        })
    )

    (app / "generate.py").write_text("""\
import os, pathlib
pathlib.Path(os.environ["STOP_FLAG"]).touch()
""")

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(tmp_path / "config"),
        REQUESTS_DIR=str(requests_dir),
        GLOSSARY_DIR=str(tmp_path / "gloss"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # Request was skipped, not executed
    assert "failed to claim request" in proc.stdout
    assert not (requests_dir / "done" / "20261012T100000Z-77777777.json").exists()


def test_finish_failure_breaks_drain_loop(tmp_path):
    # Decision 5: If finish returns non-zero, break out of drain_requests
    # to prevent infinite retry loops.
    app = _setup_app(tmp_path)
    call_log = tmp_path / "runs.txt"
    stub_generate = f"""\
import os, pathlib
with open(r"{call_log}", "a") as f:
    f.write(os.environ.get("GENERATE_ONLY_RE", "sweep") + "\\n")
"""
    (app / "generate.py").write_text(stub_generate)

    real_rr = REPO / "review_requests.py"
    (app / "review_requests.py").write_text(f"""\
import sys, subprocess, os, pathlib
if len(sys.argv) > 1 and sys.argv[1] == "finish":
    pathlib.Path(os.environ["STOP_FLAG"]).touch()
    sys.exit(1)
res = subprocess.run([sys.executable, "{real_rr}"] + sys.argv[1:])
sys.exit(res.returncode)
""")

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    requests_dir = tmp_path / "config" / "requests"
    requests_dir.mkdir(parents=True)
    req1 = requests_dir / "20261012T100000Z-11111111.json"
    req1.write_text(
        json.dumps({
            "id": "20261012T100000Z-11111111",
            "show": "Frieren",
            "generate_only_re": r"Frieren.*S01E01",
            "status": "pending",
        })
    )
    req2 = requests_dir / "20261012T100000Z-22222222.json"
    req2.write_text(
        json.dumps({
            "id": "20261012T100000Z-22222222",
            "show": "Frieren",
            "generate_only_re": r"Frieren.*S01E02",
            "status": "pending",
        })
    )

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(tmp_path / "config"),
        REQUESTS_DIR=str(requests_dir),
        GLOSSARY_DIR=str(tmp_path / "gloss"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    assert "stopping drain" in proc.stdout
    runs = call_log.read_text().splitlines()
    assert "Frieren.*S01E01" in runs
    assert "Frieren.*S01E02" not in runs
    assert req2.exists()


def test_loop_newline_injection_does_not_move_victim(tmp_path):
    # H1: A hostile request injecting a newline and PATH=victim must not move or unlink the victim.
    app = _setup_app(tmp_path)
    (app / "generate.py").write_text("""\
import os, pathlib
pathlib.Path(os.environ["STOP_FLAG"]).touch()
""")

    victim = tmp_path / "victim.json"
    victim.write_text('{"secret": "data"}\n')

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    requests_dir = tmp_path / "config" / "requests"
    requests_dir.mkdir(parents=True)
    bad_req = requests_dir / "20261012T100000Z-11111111.json"
    bad_req.write_text(
        json.dumps({
            "id": "20261012T100000Z-11111111",
            "show": "Frieren",
            "generate_only_re": f"E01\nPATH={victim}\nSHOW=..",
            "status": "pending",
        })
    )

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(tmp_path / "config"),
        REQUESTS_DIR=str(requests_dir),
        GLOSSARY_DIR=str(tmp_path / "gloss"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # Victim must be completely untouched
    assert victim.exists()
    assert victim.read_text() == '{"secret": "data"}\n'
    assert not (tmp_path / "failed").exists()
    assert not (requests_dir / "done" / "victim.json").exists()


def test_request_progress_resumes_after_crash(tmp_path):
    # L6: A request whose generate.py crashes after making progress (after > before)
    # is retried using the sweep's crash-resume loop and finishes successfully.
    app = _setup_app(tmp_path)
    runs_file = tmp_path / "attempts.txt"
    anime = tmp_path / "anime"
    show_dir = anime / "Frieren"
    show_dir.mkdir(parents=True)

    stub_generate = f"""\
import os, sys, pathlib
attempt_count = 0
if os.path.exists(r"{runs_file}"):
    attempt_count = int(pathlib.Path(r"{runs_file}").read_text())
attempt_count += 1
pathlib.Path(r"{runs_file}").write_text(str(attempt_count))

show_dir = pathlib.Path(r"{show_dir}")
if attempt_count == 1:
    # First attempt: make progress on ep1, then crash (exit 1)
    (show_dir / "Frieren - S01E01.eng.dubtitles.srt").touch()
    sys.exit(1)
elif attempt_count == 2:
    # Second attempt: finish ep2 cleanly
    (show_dir / "Frieren - S01E02.eng.dubtitles.srt").touch()
    sys.exit(0)
else:
    # Sweep pass: signal stop flag
    pathlib.Path(os.environ["STOP_FLAG"]).touch()
    sys.exit(0)
"""
    (app / "generate.py").write_text(stub_generate)

    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    requests_dir = tmp_path / "config" / "requests"
    requests_dir.mkdir(parents=True)
    req = requests_dir / "20261012T100000Z-99999999.json"
    req.write_text(
        json.dumps({
            "id": "20261012T100000Z-99999999",
            "show": "Frieren",
            "status": "pending",
        })
    )

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(tmp_path / "config"),
        REQUESTS_DIR=str(requests_dir),
        GLOSSARY_DIR=str(tmp_path / "gloss"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # Both episodes were produced because it resumed
    assert (show_dir / "Frieren - S01E01.eng.dubtitles.srt").exists()
    assert (show_dir / "Frieren - S01E02.eng.dubtitles.srt").exists()
    # Request completed successfully
    done_req = requests_dir / "done" / "20261012T100000Z-99999999.json"
    assert done_req.exists()
    assert "resume pass 2" in proc.stdout


def test_drain_requests_invokes_prune(tmp_path):
    # L3: Prune is invoked during drain_requests once per sweep
    app = _setup_app(tmp_path)
    (app / "generate.py").write_text("""\
import os, pathlib
pathlib.Path(os.environ["STOP_FLAG"]).touch()
""")

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    requests_dir = tmp_path / "config" / "requests"
    done_dir = requests_dir / "done"
    done_dir.mkdir(parents=True)
    old_file = done_dir / "20261001T000000Z-old.json"
    old_file.write_text("{}")
    old_time = time.time() - 10 * 86400
    os.utime(old_file, (old_time, old_time))

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(tmp_path / "config"),
        REQUESTS_DIR=str(requests_dir),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # The 10-day old file was pruned by drain_requests
    assert not old_file.exists()


def test_first_wins_path_in_unpack(tmp_path):
    # L3: gen_loop.sh enforces first-wins for PATH (defence-in-depth against duplicate keys)
    app = _setup_app(tmp_path)
    real_rr = REPO / "review_requests.py"
    evil_victim = tmp_path / "victim.json"
    evil_victim.write_text(json.dumps({"id": "victim", "status": "pending"}))

    (app / "review_requests.py").write_text(f"""\
import sys, subprocess
res = subprocess.run([sys.executable, "{real_rr}"] + sys.argv[1:], capture_output=True, text=True)
if len(sys.argv) > 1 and sys.argv[1] == "unpack":
    # Inject a duplicate duplicate PATH key pointing to victim
    sys.stdout.write(res.stdout + "\\nPATH={evil_victim}\\n")
else:
    sys.stdout.write(res.stdout)
sys.stderr.write(res.stderr)
sys.exit(res.returncode)
""")

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    requests_dir = tmp_path / "config" / "requests"
    requests_dir.mkdir(parents=True)
    real_req = requests_dir / "20261012T100000Z-12341234.json"
    real_req.write_text(
        json.dumps({
            "id": "20261012T100000Z-12341234",
            "show": "Frieren",
            "generate_only_re": r"Frieren.*S01E01",
            "status": "pending",
        })
    )

    (app / "generate.py").write_text("""\
import os, pathlib
if not os.environ.get("GENERATE_ONLY_RE"):
    pathlib.Path(os.environ["STOP_FLAG"]).touch()
""")

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(tmp_path / "config"),
        REQUESTS_DIR=str(requests_dir),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # First-wins kept real_req as req_path: real_req completed to done/
    assert (requests_dir / "done" / "20261012T100000Z-12341234.json").exists()
    # Victim was untouched
    assert evil_victim.exists()
    assert json.loads(evil_victim.read_text())["status"] == "pending"


def test_soft_stop_before_generate_requeues_request(tmp_path):
    # N1: A soft stop right after claiming the request must return it to pending, not mark it done
    app = _setup_app(tmp_path)
    real_rr = REPO / "review_requests.py"
    stop_flag = tmp_path / "stop"
    gen_called = tmp_path / "gen_called"

    (app / "review_requests.py").write_text(f"""\
import sys, subprocess, pathlib, os
res = subprocess.run([sys.executable, "{real_rr}"] + sys.argv[1:], capture_output=True, text=True)
sys.stdout.write(res.stdout)
sys.stderr.write(res.stderr)
if len(sys.argv) > 1 and sys.argv[1] == "start" and res.returncode == 0:
    pathlib.Path(os.environ["STOP_FLAG"]).touch()
sys.exit(res.returncode)
""")

    (app / "generate.py").write_text(f"""\
import pathlib
pathlib.Path(r"{gen_called}").touch()
""")

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    requests_dir = tmp_path / "config" / "requests"
    requests_dir.mkdir(parents=True)
    req_file = requests_dir / "20261012T100000Z-55555555.json"
    req_file.write_text(
        json.dumps({
            "id": "20261012T100000Z-55555555",
            "show": "Frieren",
            "generate_only_re": r"Frieren.*S01E01",
            "status": "pending",
        })
    )

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(tmp_path / "config"),
        REQUESTS_DIR=str(requests_dir),
        STOP_FLAG=str(stop_flag),
        RESCAN_INTERVAL="0",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # generate was not called
    assert not gen_called.exists()
    # request is not in done/
    assert not (requests_dir / "done" / "20261012T100000Z-55555555.json").exists()
    # request is back in requests/ with status pending
    assert req_file.exists()
    assert not (requests_dir / "20261012T100000Z-55555555.running").exists()
    data = json.loads(req_file.read_text())
    assert data["status"] == "pending"


def test_soft_stop_during_generate_requeues_request(tmp_path):
    # N1b: A soft stop that arrives DURING generate makes generate exit 0,
    # but the request must be requeued to pending, not marked done.
    app = _setup_app(tmp_path)
    stop_flag = tmp_path / "stop"
    state_file = tmp_path / "gen_runs"

    stub_generate = f"""\
import os, pathlib, sys
gen_re = os.environ.get("GENERATE_ONLY_RE")
runs = 0
if os.path.exists(r"{state_file}"):
    runs = int(pathlib.Path(r"{state_file}").read_text())
runs += 1
pathlib.Path(r"{state_file}").write_text(str(runs))

if gen_re:
    if runs == 1:
        # First request run: soft stop arrives during generate, generate touches STOP_FLAG and exits 0
        pathlib.Path(os.environ["STOP_FLAG"]).touch()
        sys.exit(0)
    else:
        # Second request run: completes cleanly
        sys.exit(0)
else:
    # Normal show sweep: touch STOP_FLAG so gen_loop exits after sweep
    pathlib.Path(os.environ["STOP_FLAG"]).touch()
    sys.exit(0)
"""
    (app / "generate.py").write_text(stub_generate)

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    requests_dir = tmp_path / "config" / "requests"
    requests_dir.mkdir(parents=True)
    req_file = requests_dir / "20261012T100000Z-88888888.json"
    req_file.write_text(
        json.dumps({
            "id": "20261012T100000Z-88888888",
            "show": "Frieren",
            "generate_only_re": r"Frieren.*S01E01",
            "status": "pending",
        })
    )

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(tmp_path / "config"),
        REQUESTS_DIR=str(requests_dir),
        STOP_FLAG=str(stop_flag),
        RESCAN_INTERVAL="0",
    )

    # First loop run: stop flag touched during generate
    proc1 = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc1.returncode == 0, proc1.stdout + proc1.stderr

    # Must be pending again, not done!
    assert not (requests_dir / "done" / "20261012T100000Z-88888888.json").exists()
    assert req_file.exists()
    assert json.loads(req_file.read_text())["status"] == "pending"

    # Second loop run with flag removed: completes request to done!
    stop_flag.unlink(missing_ok=True)
    proc2 = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc2.returncode == 0, proc2.stdout + proc2.stderr

    done_file = requests_dir / "done" / "20261012T100000Z-88888888.json"
    assert done_file.exists()
    assert json.loads(done_file.read_text())["status"] == "done"
