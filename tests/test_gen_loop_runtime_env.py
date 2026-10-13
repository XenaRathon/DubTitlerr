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
        if (REPO / "review_settings.py").exists():
            shutil.copy(REPO / "review_settings.py", app / "review_settings.py")
    (app / "mine_glossary.py").write_text("")
    return app


def test_runtime_env_model_change_applies_to_next_show(tmp_path):
    # 1. runtime.env model change applies to the next show
    app = _setup_app(tmp_path)
    runs_file = tmp_path / "runs.jsonl"
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    runtime_env = config_dir / "runtime.env"
    runtime_env.write_text("REPAIR_MODEL=model-one\n")

    stub_generate = f"""\
import os, json, pathlib
show = os.environ.get("SHOW_NAME", "")
model = os.environ.get("REPAIR_MODEL", "")
with open(r"{runs_file}", "a") as f:
    f.write(json.dumps({{"show": show, "model": model}}) + "\\n")

# If Show1 just ran, update runtime.env for Show2
if show == "Show1":
    pathlib.Path(r"{runtime_env}").write_text("REPAIR_MODEL=model-two\\n")
elif show == "Show2":
    pathlib.Path(os.environ["STOP_FLAG"]).touch()
"""
    (app / "generate.py").write_text(stub_generate)

    anime = tmp_path / "anime"
    (anime / "Show1").mkdir(parents=True)
    (anime / "Show2").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Show1\nShow2\n")

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(config_dir),
        REQUESTS_DIR=str(config_dir / "requests"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
        REPAIR_MODEL="container-model",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    lines = [json.loads(line) for line in runs_file.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0] == {"show": "Show1", "model": "model-one"}
    assert lines[1] == {"show": "Show2", "model": "model-two"}

    effective_env = (config_dir / "effective.env").read_text()
    assert "REPAIR_MODEL=model-two" in effective_env


def test_request_require_eng_beats_runtime_env(tmp_path):
    # 2. a request require_eng beats runtime.env
    app = _setup_app(tmp_path)
    runs_file = tmp_path / "runs.jsonl"
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    runtime_env = config_dir / "runtime.env"
    runtime_env.write_text("REQUIRE_ENG=1\n")

    stub_generate = f"""\
import os, json, pathlib
gen_re = os.environ.get("GENERATE_ONLY_RE", "")
req_eng = os.environ.get("REQUIRE_ENG", "")
with open(r"{runs_file}", "a") as f:
    f.write(json.dumps({{"gen_re": gen_re, "require_eng": req_eng}}) + "\\n")
pathlib.Path(os.environ["STOP_FLAG"]).touch()
"""
    (app / "generate.py").write_text(stub_generate)

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    requests_dir = config_dir / "requests"
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
        CONFIG_DIR=str(config_dir),
        REQUESTS_DIR=str(requests_dir),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
        REQUIRE_ENG="1",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    lines = [json.loads(line) for line in runs_file.read_text().splitlines()]
    assert len(lines) >= 1
    # Request had require_eng: 0, beating runtime.env (REQUIRE_ENG=1)
    assert lines[0]["require_eng"] == "0"


def test_hostile_hand_edited_runtime_env_cannot_inject(tmp_path):
    # 3. a hostile hand-edited runtime.env cannot inject
    app = _setup_app(tmp_path)
    runs_file = tmp_path / "runs.jsonl"
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    pwn_file = tmp_path / "pwned.txt"

    # Hostile runtime.env with shell injection, disallowed keys, command execution
    (config_dir / "runtime.env").write_text(
        f"""REPAIR_MODEL=model; touch {pwn_file}
EVIL_INJECT=true
PATH=/evil/bin
`touch {pwn_file}`
$(touch {pwn_file})
REPAIR_URL=http://evil.com
REPAIR_MODEL=safe-model
"""
    )

    stub_generate = f"""\
import os, json, pathlib
with open(r"{runs_file}", "a") as f:
    f.write(json.dumps({{
        "model": os.environ.get("REPAIR_MODEL", ""),
        "evil": os.environ.get("EVIL_INJECT"),
        "repair_url": os.environ.get("REPAIR_URL"),
    }}) + "\\n")
pathlib.Path(os.environ["STOP_FLAG"]).touch()
"""
    (app / "generate.py").write_text(stub_generate)

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(config_dir),
        REQUESTS_DIR=str(config_dir / "requests"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
        REPAIR_MODEL="container-model",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # Command injection did not execute
    assert not pwn_file.exists()

    rec = json.loads(runs_file.read_text().splitlines()[0])
    assert rec["evil"] is None
    assert rec["repair_url"] is None
    # Only the valid safe-model value was accepted, or container-model if invalid
    assert rec["model"] == "safe-model"


def test_deleting_runtime_env_restores_container_value_for_next_show(tmp_path):
    # 4. deleting runtime.env restores the container value for the next show
    app = _setup_app(tmp_path)
    runs_file = tmp_path / "runs.jsonl"
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    runtime_env = config_dir / "runtime.env"
    runtime_env.write_text("REPAIR_MODEL=runtime-model\n")

    stub_generate = f"""\
import os, json, pathlib
show = os.environ.get("SHOW_NAME", "")
model = os.environ.get("REPAIR_MODEL", "")
with open(r"{runs_file}", "a") as f:
    f.write(json.dumps({{"show": show, "model": model}}) + "\\n")

# When Show1 finishes, delete runtime.env
if show == "Show1":
    pathlib.Path(r"{runtime_env}").unlink()
elif show == "Show2":
    pathlib.Path(os.environ["STOP_FLAG"]).touch()
"""
    (app / "generate.py").write_text(stub_generate)

    anime = tmp_path / "anime"
    (anime / "Show1").mkdir(parents=True)
    (anime / "Show2").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Show1\nShow2\n")

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(config_dir),
        REQUESTS_DIR=str(config_dir / "requests"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
        REPAIR_MODEL="container-model",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    lines = [json.loads(line) for line in runs_file.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0] == {"show": "Show1", "model": "runtime-model"}
    # Show2 must have reverted to container-model!
    assert lines[1] == {"show": "Show2", "model": "container-model"}

    effective_env = (config_dir / "effective.env").read_text()
    assert "REPAIR_MODEL=container-model" in effective_env


def test_missing_exporter_degrades_to_container_env(tmp_path):
    # 5. a missing exporter degrades to container env
    app = _setup_app(tmp_path, include_exporter=False)
    runs_file = tmp_path / "runs.jsonl"
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    runtime_env = config_dir / "runtime.env"
    runtime_env.write_text("REPAIR_MODEL=runtime-model\n")

    stub_generate = f"""\
import os, json, pathlib
with open(r"{runs_file}", "a") as f:
    f.write(json.dumps({{"model": os.environ.get("REPAIR_MODEL", "")}}) + "\\n")
pathlib.Path(os.environ["STOP_FLAG"]).touch()
"""
    (app / "generate.py").write_text(stub_generate)

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(config_dir),
        REQUESTS_DIR=str(config_dir / "requests"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
        REPAIR_MODEL="container-model",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    rec = json.loads(runs_file.read_text().splitlines()[0])
    # Degraded cleanly to container-model without crashing
    assert rec["model"] == "container-model"


def test_m4_gen_loop_does_not_apply_profile_to_generate(tmp_path):
    # Decision M4: gen_loop must call 'export --scope gen' so an openai repair
    # profile does not overwrite REPAIR_BACKEND / RESTORE_BACKEND in generate stages.
    app = _setup_app(tmp_path)
    runs_file = tmp_path / "runs.jsonl"
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    runtime_env = config_dir / "runtime.env"
    runtime_env.write_text("REPAIR_PROFILE=cloud_openai\n")

    stub_generate = f"""\
import os, json, pathlib
rec = {{
    "REPAIR_BACKEND": os.environ.get("REPAIR_BACKEND"),
    "REPAIR_LLAMACPP_URL": os.environ.get("REPAIR_LLAMACPP_URL"),
    "VERIFY_BACKEND": os.environ.get("VERIFY_BACKEND"),
}}
with open(r"{runs_file}", "a") as f:
    f.write(json.dumps(rec) + "\\n")
pathlib.Path(os.environ["STOP_FLAG"]).touch()
"""
    (app / "generate.py").write_text(stub_generate)

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    profiles_json = json.dumps({
        "cloud_openai": {
            "backend": "openai",
            "url": "https://api.openai.com/v1",
        }
    })

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(config_dir),
        REQUESTS_DIR=str(config_dir / "requests"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
        REPAIR_BACKEND="llamacpp",
        REPAIR_LLAMACPP_URL="http://192.0.2.10:8090/v1",
        VERIFY_BACKEND="llamacpp",
        REPAIR_PROFILES=profiles_json,
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    rec = json.loads(runs_file.read_text().splitlines()[0])
    # Generate stage must preserve container's backends, NOT the repair profile's openai backend!
    assert rec["REPAIR_BACKEND"] == "llamacpp"


def test_restore_runtime_env_restores_all_keys_after_reset(tmp_path):
    # L3: restore_runtime_env restores REPAIR_OPENAI_KEY_ENV, REPAIR_LLAMACPP_URL, and REQUIRE_ENG
    app = _setup_app(tmp_path)
    runs_file = tmp_path / "runs.jsonl"
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    runtime_env = config_dir / "runtime.env"
    runtime_env.write_text("REQUIRE_ENG=0\n")

    stub_generate = f"""\
import os, json, pathlib
show = os.environ.get("SHOW_NAME", "")
rec = {{
    "show": show,
    "REQUIRE_ENG": os.environ.get("REQUIRE_ENG"),
    "REPAIR_LLAMACPP_URL": os.environ.get("REPAIR_LLAMACPP_URL"),
    "REPAIR_OPENAI_KEY_ENV": os.environ.get("REPAIR_OPENAI_KEY_ENV"),
}}
with open(r"{runs_file}", "a") as f:
    f.write(json.dumps(rec) + "\\n")
if show == "Show1":
    pathlib.Path(r"{runtime_env}").unlink()
elif show == "Show2":
    pathlib.Path(os.environ["STOP_FLAG"]).touch()
"""
    (app / "generate.py").write_text(stub_generate)

    anime = tmp_path / "anime"
    (anime / "Show1").mkdir(parents=True)
    (anime / "Show2").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Show1\nShow2\n")

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(config_dir),
        REQUESTS_DIR=str(config_dir / "requests"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
        REQUIRE_ENG="1",
        REPAIR_LLAMACPP_URL="http://192.0.2.10:8090/v1",
        REPAIR_OPENAI_KEY_ENV="CONTAINER_KEY_VAR",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    lines = [json.loads(line) for line in runs_file.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["REQUIRE_ENG"] == "0"
    # Show2 must have restored initial container environment for all three keys!
    assert lines[1]["REQUIRE_ENG"] == "1"
    assert lines[1]["REPAIR_LLAMACPP_URL"] == "http://192.0.2.10:8090/v1"
    assert lines[1]["REPAIR_OPENAI_KEY_ENV"] == "CONTAINER_KEY_VAR"


def test_per_request_apply_runtime_env(tmp_path):
    # L3: apply_runtime_env is called per request
    app = _setup_app(tmp_path)
    runs_file = tmp_path / "runs.jsonl"
    config_dir = tmp_path / "config"
    requests_dir = config_dir / "requests"
    requests_dir.mkdir(parents=True, exist_ok=True)
    runtime_env = config_dir / "runtime.env"
    runtime_env.write_text("REQUIRE_ENG=1\n")

    stub_generate = f"""\
import os, json, pathlib
gen_re = os.environ.get("GENERATE_ONLY_RE", "")
req_eng = os.environ.get("REQUIRE_ENG", "")
with open(r"{runs_file}", "a") as f:
    f.write(json.dumps({{"gen_re": gen_re, "require_eng": req_eng}}) + "\\n")
if "E01" in gen_re:
    pathlib.Path(r"{runtime_env}").write_text("REQUIRE_ENG=0\\n")
elif "E02" in gen_re:
    pathlib.Path(os.environ["STOP_FLAG"]).touch()
"""
    (app / "generate.py").write_text(stub_generate)

    anime = tmp_path / "anime"
    (anime / "Frieren").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Frieren\n")

    req1 = requests_dir / "20261012T100000Z-11111111.json"
    req1.write_text(
        json.dumps({
            "id": "20261012T100000Z-11111111",
            "show": "Frieren",
            "generate_only_re": "E01",
            "status": "pending",
        })
    )
    req2 = requests_dir / "20261012T100001Z-22222222.json"
    req2.write_text(
        json.dumps({
            "id": "20261012T100001Z-22222222",
            "show": "Frieren",
            "generate_only_re": "E02",
            "status": "pending",
        })
    )

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(config_dir),
        REQUESTS_DIR=str(requests_dir),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
        REQUIRE_ENG="1",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    lines = [json.loads(line) for line in runs_file.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0] == {"gen_re": "E01", "require_eng": "1"}
    # Request 2 picked up the new runtime.env value because apply_runtime_env ran before it!
    assert lines[1] == {"gen_re": "E02", "require_eng": "0"}


def test_exporter_stderr_logged_once_per_sweep(tmp_path):
    # L5: Exporter stderr is logged once per sweep, not sent to /dev/null
    app = _setup_app(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    runtime_env = config_dir / "runtime.env"
    runtime_env.write_text("REQUIRE_ENG=1\n")

    # Wrap review_settings_write.py to emit a warning to stderr
    real_exporter = REPO / "review_settings_write.py"
    (app / "review_settings_write.py").write_text(f"""\
import sys, subprocess
sys.stderr.write("review_settings_write: ignoring runtime settings\\n")
res = subprocess.run([sys.executable, "{real_exporter}"] + sys.argv[1:], capture_output=True, text=True)
sys.stdout.write(res.stdout)
sys.exit(res.returncode)
""")

    stub_generate = """\
import os, pathlib
show = os.environ.get("SHOW_NAME", "")
if show == "Show2":
    pathlib.Path(os.environ["STOP_FLAG"]).touch()
"""
    (app / "generate.py").write_text(stub_generate)

    anime = tmp_path / "anime"
    (anime / "Show1").mkdir(parents=True)
    (anime / "Show2").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Show1\nShow2\n")

    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        CONFIG_DIR=str(config_dir),
        REQUESTS_DIR=str(config_dir / "requests"),
        STOP_FLAG=str(tmp_path / "stop"),
        RESCAN_INTERVAL="0",
    )

    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # Exporter stderr warning was printed to stderr, not silenced to /dev/null
    assert "review_settings_write: ignoring runtime settings" in proc.stderr
    # Logged exactly once per sweep despite multiple calls (sweep start, Show1, Show2)
    assert proc.stderr.count("review_settings_write: ignoring runtime settings") == 1



