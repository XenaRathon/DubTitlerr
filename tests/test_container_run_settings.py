"""[S-5] container_run.sh exports the stored container- and server-scope settings at container start, before its own defaults."""

import json
import os
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = open(os.path.join(REPO, "container_run.sh")).read()


def block():
    start = SCRIPT.index("# >>> stored settings")
    end = SCRIPT.index("# <<< stored settings")
    return SCRIPT[start:end]


def run_block(tmp_path, values, env=None, tail=""):
    (tmp_path / "settings.json").write_text(json.dumps({"version": 1, "values": values}))
    script = (
        "set -u\n"
        f"{block()}\n"
        ': "${MERGE_INTERVAL:=600}"\n'
        'echo "interval=$MERGE_INTERVAL port=${REVIEW_PORT-unset}"'
        ' "boot_port=${DT_BOOT_REVIEW_PORT-unset} window=${MERGE_WINDOW-unset}"\n'
        f"{tail}\n"
    )
    full = {
        k: v for k, v in os.environ.items() if k not in ("MERGE_INTERVAL", "REVIEW_PORT", "MERGE_WINDOW", "DT_BOOT_REVIEW_PORT")
    }
    full.update({"APP_DIR": REPO, "CONFIG_DIR": str(tmp_path), **(env or {})})
    return subprocess.run(["sh", "-c", script], env=full, capture_output=True, text=True, timeout=30)


def test_stored_container_and_server_values_are_exported_before_the_defaults(tmp_path):
    res = run_block(
        tmp_path, {"MERGE_INTERVAL": 120, "REVIEW_PORT": 9000, "MERGE_WINDOW": "22:00-06:00"}, {"REVIEW_PORT": "8000"}
    )
    assert res.stdout.strip() == "interval=120 port=9000 boot_port=8000 window=22:00-06:00", res.stderr


def test_without_stored_values_the_defaults_and_the_container_env_stand(tmp_path):
    res = run_block(tmp_path, {}, {"REVIEW_PORT": "8000"})
    assert res.stdout.strip() == "interval=600 port=8000 boot_port=unset window=unset"


def test_gen_scope_values_are_not_exported_at_container_start(tmp_path):
    res = run_block(tmp_path, {"WHISPER_BEAM_SIZE": 5}, tail='echo "beam=${WHISPER_BEAM_SIZE-unset}"')
    assert res.stdout.splitlines()[-1] == "beam=unset"


def test_a_missing_exporter_changes_nothing(tmp_path):
    res = run_block(tmp_path, {"MERGE_INTERVAL": 120}, {"APP_DIR": str(tmp_path / "no-app")})
    assert res.stdout.startswith("interval=600") and res.returncode == 0


def test_the_block_sits_before_the_defaults_it_must_override():
    assert SCRIPT.index("# <<< stored settings") < SCRIPT.index(': "${MERGE_INTERVAL:=600}"')


# --- the review server's own secrets: exported inside its subshell only ------------------------------------------------------


def server_block():
    start = SCRIPT.index("# >>> stored server secrets")
    end = SCRIPT.index("# <<< stored server secrets")
    return SCRIPT[start:end]


def run_server_function(tmp_path, secrets, env=None):
    """Run the real run_review_server against a stub review_server.py that records its environment, then report what the parent
    shell and a sibling child (standing in for the merge and generate loops) can see."""
    import shutil

    app = tmp_path / "app"
    app.mkdir()
    for name in (
        "review_settings_write.py",
        "settings_registry.py",
        "settings_store.py",
        "settings_connections.py",
        "glossary_lock.py",
        "common.py",
    ):
        shutil.copy(os.path.join(REPO, name), app / name)
    dump = tmp_path / "server-env.json"
    stub = "import json, os\nenv = {k: v for k, v in os.environ.items() if 'WEBHOOK_TOKEN' in k}\n"
    (app / "review_server.py").write_text(stub + f"open({str(dump)!r}, 'w').write(json.dumps(env))\n")
    (tmp_path / "settings.json").write_text(json.dumps({"version": 1, "values": {"REVIEW_PORT": 9000}}))
    (tmp_path / "secrets.json").write_text(json.dumps({"version": 1, "values": secrets, "connections": {}}))
    os.chmod(tmp_path / "secrets.json", 0o600)
    script = (
        "set -u\n"
        f"{server_block()}\n"
        "run_review_server &\nwait $!\n"
        'echo "parent=${WEBHOOK_TOKEN-unset}:${DT_BOOT_WEBHOOK_TOKEN-unset}"\n'
        "sh -c 'echo \"child=${WEBHOOK_TOKEN-unset}\"'\n"
    )
    full = {k: v for k, v in os.environ.items() if "WEBHOOK_TOKEN" not in k}
    full.update({"APP_DIR": str(app), "CONFIG_DIR": str(tmp_path), **(env or {})})
    res = subprocess.run(["sh", "-c", script], env=full, capture_output=True, text=True, timeout=30)
    return res, json.loads(dump.read_text()) if dump.exists() else None


def test_a_stored_server_secret_reaches_the_review_server_process_only(tmp_path):
    res, seen = run_server_function(tmp_path, {"WEBHOOK_TOKEN": "hook-stored-1"})
    assert res.returncode == 0, res.stderr
    assert seen == {"WEBHOOK_TOKEN": "hook-stored-1", "DT_BOOT_WEBHOOK_TOKEN": ""}
    assert res.stdout.splitlines() == ["parent=unset:unset", "child=unset"]


def test_the_container_secret_is_never_copied_into_a_boot_variable(tmp_path):
    res, seen = run_server_function(tmp_path, {"WEBHOOK_TOKEN": "hook-stored-1"}, {"WEBHOOK_TOKEN": "container-hook-9"})
    assert seen["WEBHOOK_TOKEN"] == "hook-stored-1" and seen["DT_BOOT_WEBHOOK_TOKEN"] == "1"
    assert "container-hook-9" not in json.dumps(seen)
    assert "child=container-hook-9" in res.stdout, "the container's own value is untouched outside the server"


def test_without_a_stored_secret_the_server_keeps_the_container_value(tmp_path):
    res, seen = run_server_function(tmp_path, {}, {"WEBHOOK_TOKEN": "container-hook-9"})
    assert seen == {"WEBHOOK_TOKEN": "container-hook-9"}


def test_a_missing_exporter_still_starts_the_server(tmp_path):
    res, seen = run_server_function(tmp_path, {"WEBHOOK_TOKEN": "hook-stored-1"}, {"WEBHOOK_TOKEN": "container-hook-9"})
    assert seen["WEBHOOK_TOKEN"] == "hook-stored-1"  # sanity: the stub app has the exporter
    app = tmp_path / "app"
    (app / "review_settings_write.py").unlink()
    (tmp_path / "server-env.json").unlink()
    script = f"set -u\n{server_block()}\nrun_review_server &\nwait $!\n"
    full = {**os.environ, "APP_DIR": str(app), "CONFIG_DIR": str(tmp_path), "WEBHOOK_TOKEN": "container-hook-9"}
    subprocess.run(["sh", "-c", script], env=full, capture_output=True, text=True, timeout=30)
    assert json.loads((tmp_path / "server-env.json").read_text()) == {"WEBHOOK_TOKEN": "container-hook-9"}


def test_the_review_server_is_started_through_that_function_and_the_boot_block_never_names_a_secret_flag():
    assert "run_review_server &" in SCRIPT and 'python3 "$APP_DIR/review_server.py" &' not in SCRIPT
    assert "--secrets-only" not in block() or "--boot" not in block().split("--secrets-only")[0].splitlines()[-1]


def test_the_one_time_migration_runs_before_the_exports_and_its_values_are_exported(tmp_path):
    (tmp_path / "runtime.env").write_text("REQUIRE_ENG=0\n")
    (tmp_path / "settings.json").write_text(json.dumps({"version": 1, "values": {"MERGE_INTERVAL": 120}}))
    res = run_block(tmp_path, {"MERGE_INTERVAL": 120}, tail='echo "migrated=$(ls "$CONFIG_DIR" | grep -c runtime.env.migrated)"')
    assert res.stdout.splitlines()[-1] == "migrated=1" and "interval=120 port=unset" in res.stdout, res.stderr
    assert SCRIPT.index('review_settings_write.py" migrate') < SCRIPT.index('review_settings_write.py" export')
