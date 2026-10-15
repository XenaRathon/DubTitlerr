"""[S-5] The exporter: stored settings per scope, shell-safe output, reset-to-init lines, boot snapshot, bad files."""

import json
import os
import subprocess
import sys

import pytest

import settings_store as store

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTER = os.path.join(REPO, "review_settings_write.py")


@pytest.fixture
def cfg(tmp_path):
    return tmp_path


def save(cfg, values=None, secrets=None):
    env = {"CONFIG_DIR": str(cfg)}
    state = store.load(env)
    state.values.update(values or {})
    state.secret_values.update(secrets or {})
    store.save(state, env)


def run(cfg, *args, env=None):
    full = {k: v for k, v in os.environ.items() if k not in ("WHISPER_BEAM_SIZE", "REQUIRE_ENG")}
    full.update({"CONFIG_DIR": str(cfg), **(env or {})})
    return subprocess.run([sys.executable, EXPORTER, *args], env=full, capture_output=True, text=True, timeout=30)


def test_gen_scope_exports_the_stored_gen_keys_and_nothing_else(cfg):
    save(cfg, {"WHISPER_BEAM_SIZE": 5, "REQUIRE_ENG": False, "REPAIR_UNANCHORED": True, "REVIEW_PORT": 9000})
    res = run(cfg, "export", "--scope", "gen", "--plain")
    assert res.returncode == 0 and res.stderr == ""
    assert sorted(res.stdout.splitlines()) == ["REQUIRE_ENG=0", "WHISPER_BEAM_SIZE=5"]


def test_merge_scope_adds_the_merge_keys_and_secrets_for_its_scope(cfg):
    save(cfg, {"WHISPER_BEAM_SIZE": 5, "REPAIR_UNANCHORED": True, "REVIEW_PORT": 9000}, {"PLEX_TOKEN": "tok en'$(x)"})
    lines = run(cfg, "export", "--scope", "merge").stdout.splitlines()
    assert "export REPAIR_UNANCHORED=1" in lines and "export WHISPER_BEAM_SIZE=5" in lines
    assert "export PLEX_TOKEN='tok en'\"'\"'$(x)'" in lines
    assert not any("REVIEW_PORT" in line for line in lines)


def test_server_and_container_scopes_export_only_their_own_keys(cfg):
    save(cfg, {"REVIEW_PORT": 9000, "MERGE_INTERVAL": 120, "WHISPER_BEAM_SIZE": 5}, {"WEBHOOK_TOKEN": "hook"})
    assert run(cfg, "export", "--scope", "server", "--plain").stdout == "REVIEW_PORT=9000\n"
    assert "export WEBHOOK_TOKEN=hook\n" in run(cfg, "export", "--scope", "server").stdout
    assert run(cfg, "export", "--scope", "container", "--plain").stdout == "MERGE_INTERVAL=120\n"


def test_boot_flag_records_the_container_value_of_each_stored_key(cfg):
    save(cfg, {"REVIEW_PORT": 9000, "REVIEW_BIND": "127.0.0.1"})
    out = run(cfg, "export", "--scope", "server", "--boot", env={"REVIEW_PORT": "8000"}).stdout.splitlines()
    assert "export DT_BOOT_REVIEW_PORT=8000" in out and not any("DT_BOOT_REVIEW_BIND" in line for line in out)


def test_reset_to_init_restores_or_unsets_every_unstored_key_of_the_scope(cfg):
    save(cfg, {"WHISPER_BEAM_SIZE": 5})
    out = run(cfg, "export", "--scope", "gen", "--reset-to-init").stdout
    assert "export WHISPER_BEAM_SIZE=5\n" in out
    restore = 'if [ -n "${_HAS_INIT_REQUIRE_ENG:-}" ]; then export REQUIRE_ENG="$_INIT_REQUIRE_ENG"; else unset REQUIRE_ENG; fi\n'
    assert restore in out and "_HAS_INIT_WHISPER_BEAM_SIZE" not in out


def test_the_snapshot_covers_every_gen_registry_key(cfg):
    out = run(cfg, "snapshot", "--scope", "gen").stdout
    assert '_INIT_ACQUIRE_APPLY="${ACQUIRE_APPLY:-}"\n_HAS_INIT_ACQUIRE_APPLY="${ACQUIRE_APPLY+1}"\n' in out
    assert "REPAIR_UNANCHORED" not in out and "PLEX_TOKEN" in out


def test_reset_to_init_round_trips_through_a_real_shell(cfg):
    """Snapshot, apply a stored value, drop it, apply again: the loop is back on the container value, or on nothing."""
    save(cfg, {"WHISPER_BEAM_SIZE": 5})
    script = f"""
set -u
cd {REPO}
eval "$({sys.executable} {EXPORTER} snapshot --scope gen)"
eval "$({sys.executable} {EXPORTER} export --scope gen --reset-to-init)"
echo "stored:$WHISPER_BEAM_SIZE:${{REQUIRE_ENG-unset}}"
rm "$CONFIG_DIR/settings.json"
eval "$({sys.executable} {EXPORTER} export --scope gen --reset-to-init)"
echo "reset:${{WHISPER_BEAM_SIZE-unset}}:${{REQUIRE_ENG-unset}}"
"""
    env = {k: v for k, v in os.environ.items() if k not in ("WHISPER_BEAM_SIZE", "REQUIRE_ENG")}
    env.update(CONFIG_DIR=str(cfg), WHISPER_BEAM_SIZE="7")
    # the container value of WHISPER_BEAM_SIZE is 7, REQUIRE_ENG is unset
    out = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, timeout=30)
    assert out.stdout.splitlines() == ["stored:5:unset", "reset:7:unset"], out.stderr


def test_a_corrupt_file_exports_nothing_and_prints_one_stderr_line(cfg):
    (cfg / "settings.json").write_text("{nope")
    res = run(cfg, "export", "--scope", "gen", "--plain")
    assert res.returncode == 0 and res.stdout == "" and res.stderr.count("\n") == 1 and "not valid JSON" in res.stderr


def test_a_hand_edited_value_that_fails_validation_is_never_exported(cfg):
    (cfg / "settings.json").write_text(
        json.dumps({"version": 1, "values": {"WHISPER_BEAM_SIZE": "7; rm -rf /", "REQUIRE_ENG": True}})
    )
    res = run(cfg, "export", "--scope", "gen", "--plain")
    assert res.stdout == "REQUIRE_ENG=1\n" and "WHISPER_BEAM_SIZE" in res.stderr


def test_secrets_are_withheld_when_secrets_json_cannot_be_trusted(cfg):
    save(cfg, {}, {"PLEX_TOKEN": "tok"})
    (cfg / "secrets.json").write_text("{nope")
    res = run(cfg, "export", "--scope", "merge", "--plain")
    assert "PLEX_TOKEN" not in res.stdout and "secrets.json" in res.stderr


def test_usage_errors_exit_2():
    assert subprocess.run([sys.executable, EXPORTER], capture_output=True).returncode == 2
    assert subprocess.run([sys.executable, EXPORTER, "export", "--scope", "nope"], capture_output=True).returncode == 2
    assert subprocess.run([sys.executable, EXPORTER, "snapshot", "--scope", "server"], capture_output=True).returncode == 2


@pytest.mark.parametrize("flag", ["--plain", "--boot"])
def test_plain_and_boot_never_print_a_secret(cfg, flag):
    save(cfg, {"REVIEW_PORT": 9000}, {"WEBHOOK_TOKEN": "hook-secret-1", "PLEX_TOKEN": "tok-secret-2"})
    for scope in ("server", "merge"):
        res = run(cfg, "export", "--scope", scope, flag, env={"WEBHOOK_TOKEN": "hook-container"})
        assert "secret" not in res.stdout and "TOKEN" not in res.stdout and "hook-container" not in res.stdout


def test_stdout_carries_only_export_and_unset_lines_even_when_the_store_logs(cfg):
    """store.load logs through common.log, which prints to stdout; eval would run that line, so it must go to stderr."""
    (cfg / "settings.json").write_text(json.dumps({"version": 1, "values": {"x; touch PWNED; #": 1, "REQUIRE_ENG": False}}))
    res = run(cfg, "export", "--scope", "gen", "--reset-to-init")
    assert res.returncode == 0 and "touch PWNED" in res.stderr
    for line in res.stdout.splitlines():
        assert line.startswith(("export ", "if [ -n ")), line
    assert "PWNED" not in res.stdout


@pytest.mark.parametrize("scope", ["gen", "merge"])
def test_a_hostile_key_in_settings_json_creates_no_file_when_the_output_is_evaluated(cfg, scope):
    hostile = "x; touch PWNED; #"
    (cfg / "settings.json").write_text(json.dumps({"version": 1, "values": {hostile: "v", "REQUIRE_ENG": False}}))
    (cfg / "secrets.json").write_text(json.dumps({"version": 1, "values": {hostile: "v"}}))
    export = f"{sys.executable} {EXPORTER} export --scope {scope} --reset-to-init 2>/dev/null"
    script = f'cd "$WORK" && eval "$({export})"; echo "$REQUIRE_ENG"'
    work = cfg / "work"
    work.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "REQUIRE_ENG"}
    env.update(CONFIG_DIR=str(cfg), WORK=str(work))
    out = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == "0", out.stderr
    assert not (work / "PWNED").exists() and not (cfg / "PWNED").exists() and list(work.iterdir()) == []


def test_the_snapshot_defines_a_restore_function_for_every_gen_key(cfg):
    out = run(cfg, "snapshot", "--scope", "gen").stdout
    assert "restore_runtime_env() {\n" in out
    body = out.split("restore_runtime_env() {\n", 1)[1].split("\n}\n", 1)[0]
    one = 'if [ -n "${_HAS_INIT_WHISPER_BEAM_SIZE:-}" ]; then export WHISPER_BEAM_SIZE="$_INIT_WHISPER_BEAM_SIZE"; else unset'
    assert one in body
    shell = f'set -u\nWHISPER_BEAM_SIZE=7\neval "$({sys.executable} {EXPORTER} snapshot --scope gen)"\n'
    shell += "WHISPER_BEAM_SIZE=5; REQUIRE_ENG=0; export WHISPER_BEAM_SIZE REQUIRE_ENG\nrestore_runtime_env\n"
    shell += 'echo "${WHISPER_BEAM_SIZE-unset}:${REQUIRE_ENG-unset}"\n'
    env = {k: v for k, v in os.environ.items() if k not in ("WHISPER_BEAM_SIZE", "REQUIRE_ENG")}
    env["CONFIG_DIR"] = str(cfg)
    got = subprocess.run(["sh", "-c", shell], env=env, capture_output=True, text=True, timeout=30)
    assert got.stdout.strip() == "7:unset", got.stderr


def test_secrets_only_prints_the_stored_secrets_of_the_scope_and_a_presence_flag_never_a_container_copy(cfg):
    save(cfg, {"REVIEW_PORT": 9000}, {"WEBHOOK_TOKEN": "hook-stored", "PLEX_TOKEN": "plex-stored"})
    res = run(cfg, "export", "--scope", "server", "--secrets-only", env={"WEBHOOK_TOKEN": "container-hook"})
    assert res.returncode == 0 and res.stderr == ""
    assert res.stdout.splitlines() == ["export WEBHOOK_TOKEN=hook-stored", "export DT_BOOT_WEBHOOK_TOKEN=1"]
    assert "container-hook" not in res.stdout and "REVIEW_PORT" not in res.stdout and "PLEX_TOKEN" not in res.stdout
    none = run(cfg, "export", "--scope", "server", "--secrets-only")
    assert none.stdout.splitlines() == ["export WEBHOOK_TOKEN=hook-stored", "export DT_BOOT_WEBHOOK_TOKEN=''"]


def test_secrets_only_withholds_secrets_when_secrets_json_cannot_be_trusted(cfg):
    save(cfg, {}, {"WEBHOOK_TOKEN": "hook-stored"})
    (cfg / "secrets.json").write_text("{nope")
    res = run(cfg, "export", "--scope", "server", "--secrets-only")
    assert res.stdout == "" and "secrets.json" in res.stderr


def test_secrets_only_cannot_be_combined_with_plain(cfg):
    save(cfg, {}, {"WEBHOOK_TOKEN": "hook-stored"})
    res = run(cfg, "export", "--scope", "server", "--secrets-only", "--plain")
    assert res.returncode == 2 and res.stdout == ""
