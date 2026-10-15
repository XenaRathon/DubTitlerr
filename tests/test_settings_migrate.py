"""[S-4] The one-time migration from runtime.env."""

import json
import os
import subprocess
import sys

import pytest

import settings_api as api
import settings_migrate as mig
import settings_store as store

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
    out = capsys.readouterr().out
    assert "VERIFY_BACKEND" in out and "RUNTIME_VERIFY_BACKENDS" in out, "the skip is logged, not only returned"
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
