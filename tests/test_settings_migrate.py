"""[S-4] The one-time migration from runtime.env and REPAIR_PROFILES."""

import json
import os
import subprocess
import sys

import pytest

import settings_api as api
import settings_migrate as mig
import settings_store as store

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES = {
    "local": {"backend": "llamacpp", "url": "http://192.168.1.20:8090/v1/chat/completions"},
    "cloud": {
        "backend": "openai",
        "url": "https://api.example.test/v1/chat/completions",
        "key_env": "CLOUD_API_KEY",
        "extra_body": {"reasoning": {"effort": "low"}},
        "model_secondary": "gpt-y",
    },
}


@pytest.fixture
def env(tmp_path):
    return {"CONFIG_DIR": str(tmp_path), "EFFECTIVE_ENV_FILE": str(tmp_path / "effective.env")}


def test_runtime_env_keys_become_stored_values_and_the_file_is_renamed(env, tmp_path):
    env.update(RUNTIME_VERIFY_BACKENDS="llamacpp,ollama,openai,decision", RUNTIME_DECISION_MODELS="typesafe/jev")
    (tmp_path / "runtime.env").write_text(
        "REPAIR_MODEL=x\nREQUIRE_ENG=0\nACQUIRE_APPLY=1\nVERIFY_BACKEND=openai\nVERIFY_DECISION_MODEL=typesafe/jev\n"
    )
    assert mig.migrate(env) == []
    assert not (tmp_path / "runtime.env").exists() and (tmp_path / "runtime.env.migrated").exists()
    state = store.load(env)
    assert state.values == {
        "REPAIR_MODEL": "x",
        "REQUIRE_ENG": False,
        "ACQUIRE_APPLY": True,
        "VERIFY_BACKEND": "openai",
        "VERIFY_DECISION_MODEL": "typesafe/jev",
    }
    entry = api.get_settings(env)[1]["values"]["REPAIR_MODEL"]
    assert entry["value"] == "x" and entry["source"] == "ui"


def test_a_second_start_changes_nothing(env, tmp_path):
    (tmp_path / "runtime.env").write_text("REPAIR_MODEL=x\n")
    mig.migrate(env)
    before = (tmp_path / "settings.json").read_bytes()
    (tmp_path / "runtime.env").write_text("REPAIR_MODEL=somebody-recreated-it\n")
    assert mig.migrate(env) == []
    assert (tmp_path / "settings.json").read_bytes() == before and (tmp_path / "runtime.env").exists()


def test_a_rerun_after_a_crash_never_overwrites_a_value_saved_since(env, tmp_path):
    state = store.load(env)
    state.values["REQUIRE_ENG"] = False
    store.save(state, env)
    (tmp_path / "runtime.env").write_text("REQUIRE_ENG=1\nACQUIRE_APPLY=0\n")
    mig.migrate(env)
    assert store.load(env).values == {"REQUIRE_ENG": False, "ACQUIRE_APPLY": False}


def test_an_unreadable_runtime_file_or_a_corrupt_store_is_retried_not_marked_done(env, tmp_path):
    (tmp_path / "runtime.env").mkdir()
    assert "unreadable" in mig.migrate(env)[0] and not (tmp_path / "runtime.env.migrated").exists()
    (tmp_path / "runtime.env").rmdir()
    (tmp_path / "runtime.env").write_text("REQUIRE_ENG=0\n")
    (tmp_path / "settings.json").write_text("{nope")
    assert "not valid JSON" in mig.migrate(env)[0]
    assert (tmp_path / "runtime.env").exists() and not (tmp_path / "runtime.env.migrated").exists()


def test_bad_runtime_values_are_skipped_with_a_note(env, tmp_path):
    (tmp_path / "runtime.env").write_text("REQUIRE_ENG=maybe\nREPAIR_MODEL=bad model!\n")
    notes = mig.migrate(env)
    assert any("REPAIR_MODEL" in n for n in notes)
    assert store.load(env).values == {}


def test_the_cli_runs_the_migration_and_exits_zero(tmp_path):
    (tmp_path / "runtime.env").write_text("REQUIRE_ENG=0\n")
    full = {**os.environ, "CONFIG_DIR": str(tmp_path)}
    res = subprocess.run(
        [sys.executable, os.path.join(REPO, "review_settings_write.py"), "migrate"],
        env=full,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0 and (tmp_path / "runtime.env.migrated").exists()
    assert json.loads((tmp_path / "settings.json").read_text())["values"] == {"REQUIRE_ENG": False}


def test_verify_values_the_old_exporter_refused_are_skipped_with_a_log_note_never_imported(env, tmp_path, capsys):
    """0.2.x exported VERIFY_BACKEND / VERIFY_DECISION_MODEL only when the operator had opted in through
    RUNTIME_VERIFY_BACKENDS / RUNTIME_DECISION_MODELS. A value it never applied must not start applying now."""
    (tmp_path / "runtime.env").write_text(
        "VERIFY_BACKEND=openai\nVERIFY_DECISION_MODEL=typesafe/jev\nREPAIR_MODEL=x\nREQUIRE_ENG=0\n"
    )
    notes = mig.migrate(env)
    assert store.load(env).values == {"REPAIR_MODEL": "x", "REQUIRE_ENG": False}
    assert any("VERIFY_BACKEND" in n and "RUNTIME_VERIFY_BACKENDS" in n for n in notes)
    assert any("VERIFY_DECISION_MODEL" in n and "RUNTIME_DECISION_MODELS" in n for n in notes)
    assert "RUNTIME_VERIFY_BACKENDS" not in capsys.readouterr().out, "migrate() returns its notes; the caller logs them, once"
    assert (tmp_path / "runtime.env.migrated").exists()


def test_the_default_opt_in_lists_allow_the_local_backends_and_no_decision_model(env, tmp_path):
    (tmp_path / "runtime.env").write_text("VERIFY_BACKEND=ollama\nVERIFY_DECISION_MODEL=typesafe/jev\n")
    mig.migrate(env)
    assert store.load(env).values == {"VERIFY_BACKEND": "ollama"}


def test_only_the_listed_decision_models_and_backends_are_imported(env, tmp_path):
    env.update(RUNTIME_VERIFY_BACKENDS="openai,bogus", RUNTIME_DECISION_MODELS="m-one, m-two")
    (tmp_path / "runtime.env").write_text("VERIFY_BACKEND=llamacpp\nVERIFY_DECISION_MODEL=m-two\n")
    notes = mig.migrate(env)
    assert store.load(env).values == {"VERIFY_DECISION_MODEL": "m-two"}
    assert len(notes) == 1 and "VERIFY_BACKEND" in notes[0]


def test_each_note_reaches_the_log_exactly_once_through_the_command_line(tmp_path):
    (tmp_path / "runtime.env").write_text("VERIFY_BACKEND=openai\nREPAIR_MODEL=bad model!\n")
    full = {k: v for k, v in os.environ.items() if not k.startswith("RUNTIME_")}
    full["CONFIG_DIR"] = str(tmp_path)
    res = subprocess.run(
        [sys.executable, os.path.join(REPO, "review_settings_write.py"), "migrate"],
        env=full,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0
    both = res.stdout + res.stderr
    assert both.count("RUNTIME_VERIFY_BACKENDS") == 1 and both.count("REPAIR_MODEL") == 1


def test_a_corrupt_secrets_file_does_not_hold_runtime_env_back(env, tmp_path):
    """The migration never writes secrets, so only an unusable settings.json blocks it."""
    (tmp_path / "runtime.env").write_text("REQUIRE_ENG=0\n")
    (tmp_path / "secrets.json").write_text("{nope")
    assert mig.migrate(env) == []
    assert store.load(env).values == {"REQUIRE_ENG": False}
    assert (tmp_path / "runtime.env.migrated").exists() and not (tmp_path / "runtime.env").exists()
    assert (tmp_path / "secrets.json").read_text() == "{nope", "the unusable secrets file is left alone"


def test_bad_values_and_bad_profiles_are_skipped_with_a_note(env, tmp_path):
    env["REPAIR_PROFILES"] = json.dumps(
        {"meta": {"backend": "llamacpp", "url": "http://169.254.169.254/v1"}, "ok": PROFILES["local"], "odd": 3}
    )
    (tmp_path / "runtime.env").write_text("REQUIRE_ENG=maybe\nREPAIR_MODEL=bad model!\n")
    notes = mig.migrate(env)
    assert any("meta" in n for n in notes) and any("odd" in n for n in notes) and any("REPAIR_MODEL" in n for n in notes)
    assert [c["name"] for c in store.load(env).connections] == ["ok"] and store.load(env).values == {}


def test_each_profile_becomes_one_connection_and_the_env_list_is_never_read_again(env, tmp_path):
    env.update(REPAIR_PROFILES=json.dumps(PROFILES), CLOUD_API_KEY="sk-cloud-abcdefgh12345678")
    (tmp_path / "runtime.env").write_text("REPAIR_PROFILE=cloud\n")
    assert mig.migrate(env) == []
    state = store.load(env)
    assert [c["name"] for c in state.connections] == ["local", "cloud"]
    assert state.stages == {"repair": "cloud"} and state.conn_keys == {"cloud": "sk-cloud-abcdefgh12345678"}
    assert state.connections[1]["extra_body"] == {"reasoning": {"effort": "low"}} and state.connections[1]["kind"] == "openai"
    assert state.connections[1]["model_secondary"] == "gpt-y", "REPAIR_MODEL_SECONDARY comes from the profile's model_secondary"
    env["REPAIR_PROFILES"] = json.dumps({"other": PROFILES["local"]})
    mig.migrate(env)
    assert [c["name"] for c in store.load(env).connections] == ["local", "cloud"]
    assert api.get_settings(env)[1]["retired_env"] == ["REPAIR_PROFILES"]


def test_without_a_runtime_file_the_profiles_are_still_imported_once(env, tmp_path):
    env["REPAIR_PROFILES"] = json.dumps(PROFILES)
    mig.migrate(env)
    assert len(store.load(env).connections) == 2 and (tmp_path / "runtime.env.migrated").read_bytes() == b""
    assert store.load(env).stages == {}


def test_the_profile_import_has_its_own_marker_and_does_not_depend_on_the_runtime_marker(env, tmp_path):
    (tmp_path / "runtime.env.migrated").write_text("")  # the runtime.env migration ran long ago, with no profiles set
    env["REPAIR_PROFILES"] = json.dumps({"local": PROFILES["local"]})
    mig.migrate(env)
    assert [c["name"] for c in store.load(env).connections] == ["local"]
    assert (tmp_path / "profiles.migrated").exists()
    env["REPAIR_PROFILES"] = json.dumps({"again": PROFILES["local"]})
    mig.migrate(env)
    assert [c["name"] for c in store.load(env).connections] == ["local"], "imported once"


def test_repair_profile_is_read_from_the_migrated_file_when_runtime_env_is_gone(env, tmp_path):
    """Task 8 renames runtime.env to runtime.env.migrated before the profiles are imported on a later start."""
    (tmp_path / "runtime.env").write_text("REPAIR_PROFILE=cloud\nREQUIRE_ENG=0\n")
    mig.migrate(env)  # no profiles yet: runtime.env moves to .migrated, profiles marker written... but REPAIR_PROFILES was unset
    (tmp_path / "profiles.migrated").unlink()
    env.update(REPAIR_PROFILES=json.dumps(PROFILES), CLOUD_API_KEY="sk-cloud-abcdefgh12345678")
    assert not (tmp_path / "runtime.env").exists()
    mig.migrate(env)
    assert store.load(env).stages == {"repair": "cloud"}
    assert store.load(env).values == {"REQUIRE_ENG": False}, "the runtime values are not imported a second time"


def test_every_skipped_profile_and_key_leaves_a_note(env):
    env["REPAIR_PROFILES"] = json.dumps(
        {
            "no-key": {"backend": "openai", "url": "https://api.example.test/v1/chat/completions", "key_env": "MISSING_KEY"},
            "short-key": {"backend": "openai", "url": "https://api.example.test/v1/chat/completions", "key_env": "SHORT"},
            "bad name!": PROFILES["local"],
            "not-json-object": "x",
        }
    )
    env["SHORT"] = "abc"
    notes = mig.migrate(env)
    assert any("no-key" in n and "MISSING_KEY" in n for n in notes), notes
    assert any("short-key" in n and "key" in n for n in notes), notes
    assert any("bad name!" in n for n in notes) and any("not-json-object" in n for n in notes)
    state = store.load(env)
    assert [c["name"] for c in state.connections] == ["no-key", "short-key"] and state.conn_keys == {}


def test_a_chosen_profile_that_was_not_imported_leaves_a_note(env, tmp_path):
    env["REPAIR_PROFILES"] = json.dumps({"local": PROFILES["local"]})
    (tmp_path / "runtime.env").write_text("REPAIR_PROFILE=gone\n")
    notes = mig.migrate(env)
    assert any("gone" in n for n in notes) and store.load(env).stages == {}


def test_a_profile_list_that_is_not_json_is_one_note(env):
    env["REPAIR_PROFILES"] = "{nope"
    assert any("REPAIR_PROFILES" in n and "JSON" in n for n in mig.migrate(env))


def test_migrated_connections_keep_the_containers_repair_timeouts(env):
    """A raised REPAIR_TIMEOUT_READ (a slow hosted model) must survive the upgrade, not drop back to the default."""
    env.update(REPAIR_PROFILES=json.dumps(PROFILES), REPAIR_TIMEOUT_CONNECT="20", REPAIR_TIMEOUT_READ="300")
    mig.migrate(env)
    for conn in store.load(env).connections:
        assert (conn["timeout_connect"], conn["timeout_read"]) == (20.0, 300.0)


@pytest.mark.parametrize("bad", ["", "abc", "0", "601", "-5", "nan", "inf", "1e9"])
def test_an_unusable_container_timeout_falls_back_to_the_default(env, bad):
    env.update(REPAIR_PROFILES=json.dumps({"local": PROFILES["local"]}), REPAIR_TIMEOUT_CONNECT=bad, REPAIR_TIMEOUT_READ=bad)
    mig.migrate(env)
    conn = store.load(env).connections[0]
    assert (conn["timeout_connect"], conn["timeout_read"]) == (10.0, 120.0)


def test_one_good_and_one_bad_timeout_are_judged_separately(env):
    env.update(REPAIR_PROFILES=json.dumps({"local": PROFILES["local"]}), REPAIR_TIMEOUT_CONNECT="15", REPAIR_TIMEOUT_READ="9999")
    mig.migrate(env)
    conn = store.load(env).connections[0]
    assert (conn["timeout_connect"], conn["timeout_read"]) == (15.0, 120.0)


def test_a_corrupt_secrets_file_defers_the_whole_profile_import_when_a_profile_carries_a_key(env, tmp_path):
    (tmp_path / "secrets.json").write_text("{nope")
    env.update(REPAIR_PROFILES=json.dumps(PROFILES), CLOUD_API_KEY="sk-cloud-abcdefgh12345678")
    (tmp_path / "runtime.env").write_text("REQUIRE_ENG=0\nREPAIR_PROFILE=cloud\n")
    notes = mig.migrate(env)
    assert any("deferred" in n and "secrets.json" in n for n in notes), notes
    state = store.load(env)
    assert state.connections == [] and state.stages == {}, "no connection without its key: a rerun would skip it, key included"
    assert not (tmp_path / "profiles.migrated").exists()
    assert state.values == {"REQUIRE_ENG": False} and (tmp_path / "runtime.env.migrated").exists(), "runtime values still import"
    # after the operator repairs secrets.json, the next start imports everything, key included
    (tmp_path / "secrets.json").unlink()
    assert mig.migrate(env) == []
    state = store.load(env)
    assert [c["name"] for c in state.connections] == ["local", "cloud"] and state.conn_keys == {
        "cloud": "sk-cloud-abcdefgh12345678"
    }
    assert state.stages == {"repair": "cloud"} and (tmp_path / "profiles.migrated").exists()


def test_a_corrupt_secrets_file_does_not_defer_profiles_that_carry_no_key(env, tmp_path):
    (tmp_path / "secrets.json").write_text("{nope")
    env["REPAIR_PROFILES"] = json.dumps({"local": PROFILES["local"]})
    assert mig.migrate(env) == []
    assert [c["name"] for c in store.load(env).connections] == ["local"] and (tmp_path / "profiles.migrated").exists()
    assert (tmp_path / "secrets.json").read_text() == "{nope"


def test_the_audit_line_names_only_the_keys_this_run_imported(env, tmp_path, capsys):
    state = store.load(env)
    state.connections = [
        dict(PROFILES["local"], name="old", kind="llamacpp", model="", extra_body={}, timeout_connect=10.0, timeout_read=120.0)
    ]
    state.conn_keys = {"old": "sk-already-there-0123456789"}
    store.save(state, env)
    capsys.readouterr()
    env.update(REPAIR_PROFILES=json.dumps({"local": PROFILES["local"]}))
    mig.migrate(env)
    audit = [ln for ln in capsys.readouterr().out.splitlines() if "migration from runtime.env" in ln]
    assert audit and "connection:old.api_key" not in audit[0] and "secrets=" not in audit[0]
