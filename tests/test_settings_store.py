"""[S-2] The settings store: files, modes, atomic writes, backups, audit line, and a store that cannot be read."""

import json
import os
import stat

import pytest

import settings_store as store

SECRET = "tok-9f8e7d6c5b4a-do-not-log"


@pytest.fixture
def env(tmp_path):
    return {"CONFIG_DIR": str(tmp_path)}


def test_nothing_stored_loads_empty_without_error(env):
    state = store.load(env)
    assert (state.values, state.connections, state.stages, state.error, state.rev) == ({}, [], {}, "", 0)


def test_a_save_writes_both_files_with_secrets_private(env, tmp_path):
    state = store.load(env)
    state.values["WHISPER_BEAM_SIZE"] = 5
    state.secret_values["PLEX_TOKEN"] = SECRET
    store.save(state, env)
    assert json.loads((tmp_path / "settings.json").read_text())["values"] == {"WHISPER_BEAM_SIZE": 5}
    assert stat.S_IMODE(os.stat(tmp_path / "secrets.json").st_mode) == 0o600
    assert SECRET not in (tmp_path / "settings.json").read_text()
    again = store.load(env)
    assert again.values == {"WHISPER_BEAM_SIZE": 5} and again.secret_values == {"PLEX_TOKEN": SECRET} and again.rev == 1


def test_the_second_save_keeps_the_previous_contents_as_prev(env, tmp_path):
    state = store.load(env)
    state.values["WHISPER_BEAM_SIZE"] = 5
    store.save(state, env)
    first = (tmp_path / "settings.json").read_text()
    state.values["WHISPER_BEAM_SIZE"] = 9
    state.secret_values["PLEX_TOKEN"] = SECRET
    store.save(state, env)
    assert (tmp_path / "settings.json.prev").read_text() == first
    state.secret_values["PLEX_TOKEN"] = SECRET + "2"
    store.save(state, env)
    assert stat.S_IMODE(os.stat(tmp_path / "secrets.json.prev").st_mode) == 0o600


def test_a_failed_write_leaves_the_old_file_and_no_temp_files(env, tmp_path, monkeypatch):
    state = store.load(env)
    state.values["WHISPER_BEAM_SIZE"] = 5
    store.save(state, env)
    before = (tmp_path / "settings.json").read_bytes()
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError(28, "No space left on device")))
    state.values["WHISPER_BEAM_SIZE"] = 9
    with pytest.raises(OSError):
        store.save(state, env)
    monkeypatch.undo()
    assert (tmp_path / "settings.json").read_bytes() == before
    assert not [n for n in os.listdir(tmp_path) if n.endswith(".tmp")]


@pytest.mark.parametrize(
    "text, why",
    [("{not json", "not valid JSON"), ('["a"]', "unexpected shape"), ('{"version": 2, "values": {}}', "another version")],
)
def test_an_unusable_settings_file_loads_empty_with_the_reason(env, tmp_path, text, why):
    (tmp_path / "settings.json").write_text(text)
    state = store.load(env)
    assert why in state.error and state.values == {}


def test_a_key_the_registry_lost_is_ignored_but_kept_in_the_file(env, tmp_path):
    (tmp_path / "settings.json").write_text(
        json.dumps({"version": 1, "rev": 3, "values": {"OLD_KEY": 1, "WHISPER_BEAM_SIZE": 4}})
    )
    state = store.load(env)
    assert state.values == {"WHISPER_BEAM_SIZE": 4} and state.unknown == {"OLD_KEY": 1}
    store.save(state, env)
    assert json.loads((tmp_path / "settings.json").read_text())["values"] == {"OLD_KEY": 1, "WHISPER_BEAM_SIZE": 4}


def test_hand_edited_garbage_never_reaches_a_consumer(env, tmp_path):
    (tmp_path / "settings.json").write_text(
        json.dumps({"version": 1, "values": {"WHISPER_BEAM_SIZE": 999, "RESCAN_INTERVAL": 60, "REQUIRE_ENG": False}})
    )
    state = store.load(env)
    assert state.values == {"REQUIRE_ENG": False}
    assert len(state.notes) == 2


def test_loose_secret_permissions_are_fixed_and_reported_once(env, tmp_path, capsys):
    path = tmp_path / "secrets.json"
    path.write_text(json.dumps({"version": 1, "values": {"PLEX_TOKEN": SECRET}, "connections": {}}))
    os.chmod(path, 0o644)
    state = store.load(env)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600 and state.secret_values == {"PLEX_TOKEN": SECRET}
    out = capsys.readouterr().out
    assert "set to 600" in out and SECRET not in out


def test_permissions_that_cannot_be_fixed_hide_the_secrets(env, tmp_path, monkeypatch):
    path = tmp_path / "secrets.json"
    path.write_text(json.dumps({"version": 1, "values": {"PLEX_TOKEN": SECRET}, "connections": {}}))
    os.chmod(path, 0o644)
    monkeypatch.setattr(os, "chmod", lambda *a: (_ for _ in ()).throw(PermissionError()))
    state = store.load(env)
    assert "cannot be made private" in state.secrets_error and state.secret_values == {}


def test_the_audit_line_names_keys_and_secret_names_never_values(capsys):
    store.audit(
        "admin", ["PLEX_URL", "WHISPER_BEAM_SIZE"], ["PLEX_TOKEN"], {"PLEX_URL": "http://plex.lan:32400/web?X-Plex-Token=abc"}
    )
    out = capsys.readouterr().out
    assert "settings saved by admin" in out and "keys=PLEX_URL,WHISPER_BEAM_SIZE" in out and "secrets=PLEX_TOKEN" in out
    assert "http://plex.lan:32400/web" in out and "X-Plex-Token" not in out


def test_the_lock_is_busy_for_a_second_holder(env, monkeypatch):
    monkeypatch.setenv("GLOSSARY_LOCK_WAIT", "0.1")
    with store.locked(env) as first:
        assert first is True
        with store.locked(env) as second:
            assert second is False


def test_bootstrap_secrets_in_secrets_json_are_ignored(env, tmp_path):
    path = tmp_path / "secrets.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "values": {
                    "PLEX_TOKEN": SECRET,
                    "REVIEW_TOKEN": "should-be-ignored",
                    "OPENROUTER_JEV_API_KEY": "also-ignored",
                },
                "connections": {},
            }
        )
    )
    state = store.load(env)
    assert state.secret_values == {"PLEX_TOKEN": SECRET}
    assert any("REVIEW_TOKEN is not editable" in note for note in state.notes)


def test_locked_raises_if_lock_cannot_be_opened(tmp_path):
    unwritable = tmp_path / "unwritable"
    unwritable.mkdir()
    os.chmod(unwritable, 0o555)
    env = {"CONFIG_DIR": str(unwritable / "sub")}
    try:
        with pytest.raises(OSError):
            with store.locked(env):
                pass
    finally:
        os.chmod(unwritable, 0o755)


@pytest.mark.parametrize(
    "text, why",
    [("{not json", "not valid JSON"), ('["a"]', "unexpected shape"), ('{"version": 2, "values": {}}', "another version")],
)
def test_an_unusable_secrets_file_loads_empty_with_the_reason(env, tmp_path, text, why):
    path = tmp_path / "secrets.json"
    path.write_text(text)
    os.chmod(path, 0o600)
    state = store.load(env)
    assert why in state.secrets_error and state.secret_values == {} and state.conn_keys == {}


def test_connections_and_stages_round_trip_through_save_and_load(env):
    state = store.load(env)
    conn = {
        "name": "fast",
        "kind": "llamacpp",
        "url": "http://127.0.0.1:8090/v1",
        "model": "qwen",
        "extra_body": "{}",
        "timeout_connect": 10.0,
        "timeout_read": 120.0,
    }
    state.connections = [conn]
    state.stages = {"repair": "fast", "verify": "fast"}
    state.conn_keys = {"fast": "secret-key-123"}
    store.save(state, env)

    loaded = store.load(env)
    assert loaded.connections == [conn]
    assert loaded.stages == {"repair": "fast", "verify": "fast"}
    assert loaded.conn_keys == {"fast": "secret-key-123"}


def test_state_copy_is_independent():
    state = store.State()
    state.values["WHISPER_BEAM_SIZE"] = 5
    state.connections.append({"name": "test"})
    state.stages["repair"] = "test"
    state.secret_values["PLEX_TOKEN"] = "abc"
    state.conn_keys["test"] = "key"
    state.notes.append("note1")

    clone = state.copy()
    clone.values["WHISPER_BEAM_SIZE"] = 7
    clone.connections[0]["name"] = "changed"
    clone.stages["repair"] = "other"
    clone.secret_values["PLEX_TOKEN"] = "xyz"
    clone.conn_keys["test"] = "key2"
    clone.notes.append("note2")

    assert state.values["WHISPER_BEAM_SIZE"] == 5
    assert state.connections[0]["name"] == "test"
    assert state.stages["repair"] == "test"
    assert state.secret_values["PLEX_TOKEN"] == "abc"
    assert state.conn_keys["test"] == "key"
    assert state.notes == ["note1"]


def test_audit_url_with_raw_at_in_password_leaks_nothing(capsys):
    store.audit(
        "admin",
        [],
        [],
        {"PLEX_URL": "http://user:p@ssword@plex.lan:32400/web?query=1#frag"},
    )
    out = capsys.readouterr().out
    assert "url PLEX_URL=http://plex.lan:32400/web" in out
    assert "user" not in out and "p@ssword" not in out and "query" not in out and "frag" not in out
