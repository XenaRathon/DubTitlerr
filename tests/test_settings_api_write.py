"""[S-2] [S-3] [S-6] [S-7] PUT /api/settings and POST /api/settings/reset: validation, all-or-nothing, secrets gate, conflicts."""

import contextlib
import json
import os
import stat

import pytest

import review_auth
import settings_api as api
import settings_store as store

SECRET = "plex-secret-7c1e9a52b8d4"


@pytest.fixture
def env(tmp_path):
    return {"CONFIG_DIR": str(tmp_path), "EFFECTIVE_ENV_FILE": str(tmp_path / "effective.env")}


@pytest.fixture(autouse=True)
def login_on(monkeypatch):
    monkeypatch.setattr(review_auth, "auth_on", lambda: True)
    monkeypatch.setattr(review_auth, "setup_required", lambda: False)


def secrets_off(monkeypatch):
    monkeypatch.setattr(review_auth, "auth_on", lambda: False)


def put(env, values, **extra):
    """PUT with the current revision unless the test names one (revision is required)."""
    if "revision" not in extra:
        extra["revision"] = store.load(env).rev
    return api.handle("PUT", "/api/settings", {"values": values, **extra}, environ=env)


def entry(env, key):
    return api.handle("GET", "/api/settings", environ=env)[1]["values"][key]


def snapshot(tmp_path):
    return {n: (tmp_path / n).read_bytes() for n in ("settings.json", "secrets.json") if (tmp_path / n).exists()}


def test_a_valid_save_writes_both_files_keeps_prev_and_logs_keys_not_secrets(env, tmp_path, capsys):
    status, payload = put(env, {"WHISPER_BEAM_SIZE": 5, "PLEX_TOKEN": SECRET})
    assert status == 200 and payload["changed"] == ["PLEX_TOKEN", "WHISPER_BEAM_SIZE"] and payload["revision"] == 1
    assert stat.S_IMODE(os.stat(tmp_path / "secrets.json").st_mode) == 0o600
    first = (tmp_path / "settings.json").read_text()
    put(env, {"WHISPER_BEAM_SIZE": 6})
    assert (tmp_path / "settings.json.prev").read_text() == first
    out = capsys.readouterr().out
    assert "settings saved by admin" in out and "keys=PLEX_TOKEN,WHISPER_BEAM_SIZE" in out and SECRET not in out


def test_env_then_ui_then_reset_walks_through_the_three_sources(env):
    env["REQUIRE_ENG"] = "0"
    assert entry(env, "REQUIRE_ENG")["source"] == "env" and entry(env, "REQUIRE_ENG")["value"] == 0
    assert put(env, {"REQUIRE_ENG": True})[0] == 200
    after = entry(env, "REQUIRE_ENG")
    assert after["value"] is True and after["source"] == "ui" and after["overridden_env"] is True
    assert api.handle("POST", "/api/settings/reset", {"keys": ["REQUIRE_ENG"]}, environ=env)[0] == 200
    back = entry(env, "REQUIRE_ENG")
    assert back["value"] == 0 and back["source"] == "env" and back["overridden_env"] is False


def test_null_resets_one_key_and_an_unchanged_save_writes_nothing(env, tmp_path):
    put(env, {"WHISPER_BEAM_SIZE": 5, "MINE_MIN_COUNT": 4})
    before = snapshot(tmp_path)
    status, payload = put(env, {"WHISPER_BEAM_SIZE": 5})
    assert status == 200 and payload["changed"] == [] and snapshot(tmp_path) == before
    put(env, {"WHISPER_BEAM_SIZE": None})
    assert json.loads((tmp_path / "settings.json").read_text())["values"] == {"MINE_MIN_COUNT": 4}


def test_one_bad_key_refuses_the_whole_save_and_leaves_both_files_byte_identical(env, tmp_path):
    put(env, {"WHISPER_BEAM_SIZE": 5, "PLEX_TOKEN": SECRET})
    before = snapshot(tmp_path)
    status, payload = put(env, {"MINE_MIN_COUNT": 4, "WHISPER_BEAM_SIZE": 99})
    assert status == 400 and list(payload["errors"]) == ["WHISPER_BEAM_SIZE"]
    assert "between 1 and 20" in payload["errors"]["WHISPER_BEAM_SIZE"]
    assert snapshot(tmp_path) == before


def test_unknown_and_not_yet_editable_keys_are_refused_by_name(env):
    status, payload = put(env, {"NOPE": 1, "REPAIR_MODEL": "x", "RESCAN_INTERVAL": 60})
    assert status == 400
    assert payload["errors"] == {
        "NOPE": "unknown setting",
        "REPAIR_MODEL": "set through a Connection",
        "RESCAN_INTERVAL": "edit in a later release",
    }


def test_a_malformed_body_is_a_400_not_a_crash(env):
    for body in (None, [], {"values": [], "revision": 0}, {"values": {}, "revision": 0, "colour": "red"}):
        assert api.handle("PUT", "/api/settings", body, environ=env)[0] == 400


@pytest.mark.parametrize("revision", [None, True, "0", 0.0, [0]])
def test_the_revision_is_required_and_must_be_an_int(env, tmp_path, revision):
    body = {"values": {"WHISPER_BEAM_SIZE": 5}}
    if revision is not None:
        body["revision"] = revision
    status, payload = api.handle("PUT", "/api/settings", body, environ=env)
    assert status == 400 and "revision" in json.dumps(payload["errors"]) and not (tmp_path / "settings.json").exists()


def test_restart_required_lists_only_the_keys_that_need_a_restart(env):
    status, payload = put(env, {"REVIEW_PORT": 9000, "WHISPER_MODEL": "large-v3"})
    assert status == 200 and payload["restart_required"] == ["REVIEW_PORT"]


def test_a_secret_put_is_403_until_login_is_enabled_and_writes_nothing(env, tmp_path, monkeypatch):
    secrets_off(monkeypatch)
    status, payload = put(env, {"WHISPER_BEAM_SIZE": 5, "PLEX_TOKEN": SECRET})
    assert status == 403 and "login" in payload["error"] and not (tmp_path / "settings.json").exists()
    assert SECRET not in json.dumps(payload)
    assert put(env, {"WHISPER_BEAM_SIZE": 5})[0] == 200
    assert api.handle("GET", "/api/settings", environ=env)[1]["secrets_writable"] is False


def test_a_secret_takes_a_string_or_a_clear_and_empty_means_no_change(env, tmp_path):
    put(env, {"PLEX_TOKEN": SECRET})
    assert entry(env, "PLEX_TOKEN")["set"] is True and entry(env, "PLEX_TOKEN")["source"] == "ui"
    before = snapshot(tmp_path)
    assert put(env, {"PLEX_TOKEN": ""})[1]["changed"] == [] and snapshot(tmp_path) == before
    assert put(env, {"PLEX_TOKEN": {"clear": True}})[1]["changed"] == ["PLEX_TOKEN"]
    assert entry(env, "PLEX_TOKEN")["set"] is False
    assert put(env, {"PLEX_TOKEN": "two\nlines"})[0] == 400


def test_a_stale_form_gets_409_with_the_current_values(env):
    revision = api.handle("GET", "/api/settings", environ=env)[1]["revision"]
    assert put(env, {"WHISPER_BEAM_SIZE": 5}, revision=revision)[0] == 200
    status, payload = put(env, {"WHISPER_BEAM_SIZE": 6}, revision=revision)
    assert status == 409 and payload["current"]["values"]["WHISPER_BEAM_SIZE"]["value"] == 5


def test_a_busy_lock_is_a_503_with_a_retry_message(env, monkeypatch):
    monkeypatch.setenv("GLOSSARY_LOCK_WAIT", "0.1")
    with store.locked(env):
        status, payload = put(env, {"WHISPER_BEAM_SIZE": 5})
    assert status == 503 and "busy" in payload["error"]


def test_a_full_or_read_only_volume_is_507_or_503_and_names_only_the_error_class(env, monkeypatch):
    def full(*a, **k):
        raise OSError(28, "No space left on device: /config/secret-path")

    monkeypatch.setattr(store, "save", full)
    status, payload = put(env, {"WHISPER_BEAM_SIZE": 5})
    assert status == 507 and "OSError" in payload["error"] and "secret-path" not in payload["error"]
    monkeypatch.setattr(store, "save", lambda *a, **k: (_ for _ in ()).throw(OSError(30, "read-only")))
    assert put(env, {"WHISPER_BEAM_SIZE": 5})[0] == 503


def test_a_corrupt_store_refuses_saves_until_reset_all(env, tmp_path):
    (tmp_path / "settings.json").write_text("{nope")
    status, payload = put(env, {"WHISPER_BEAM_SIZE": 5})
    assert status == 409 and payload["reset_required"] is True
    assert api.handle("POST", "/api/settings/reset", {"all": True}, environ=env)[0] == 200
    assert (tmp_path / "settings.json.corrupt").read_text() == "{nope"
    assert put(env, {"WHISPER_BEAM_SIZE": 5})[0] == 200


def test_reset_by_category_clears_only_that_category(env):
    put(env, {"WHISPER_BEAM_SIZE": 5, "MINE_MIN_COUNT": 4, "PLEX_TOKEN": SECRET})
    status, payload = api.handle("POST", "/api/settings/reset", {"category": "transcription"}, environ=env)
    assert status == 200 and payload["reset"] == ["WHISPER_BEAM_SIZE"]
    assert entry(env, "MINE_MIN_COUNT")["source"] == "ui" and entry(env, "PLEX_TOKEN")["set"] is True
    assert api.handle("POST", "/api/settings/reset", {"category": "nope"}, environ=env)[0] == 400
    assert api.handle("POST", "/api/settings/reset", {}, environ=env)[0] == 400


def test_resetting_a_secret_needs_login_but_a_category_reset_skips_secrets_without_it(env, monkeypatch):
    put(env, {"PLEX_TOKEN": SECRET, "PLEX_SECTION": "9"})
    secrets_off(monkeypatch)
    assert api.handle("POST", "/api/settings/reset", {"keys": ["PLEX_TOKEN"]}, environ=env)[0] == 403
    status, payload = api.handle("POST", "/api/settings/reset", {"category": "connect"}, environ=env)
    assert status == 200 and payload["reset"] == ["PLEX_SECTION"]
    assert entry(env, "PLEX_TOKEN")["set"] is True


def test_a_corrupt_secrets_file_refuses_only_plans_that_touch_secrets_and_is_not_overwritten(env, tmp_path):
    (tmp_path / "secrets.json").write_text("{nope")
    assert put(env, {"WHISPER_BEAM_SIZE": 5})[0] == 200
    assert (tmp_path / "secrets.json").read_text() == "{nope"
    status, payload = put(env, {"PLEX_TOKEN": SECRET})
    assert status == 409 and payload["reset_required"] is True and SECRET not in json.dumps(payload)
    assert api.handle("POST", "/api/settings/reset", {"keys": ["PLEX_TOKEN"]}, environ=env)[0] == 409
    assert api.handle("POST", "/api/settings/reset", {"keys": ["WHISPER_BEAM_SIZE"]}, environ=env)[0] == 200


def test_reset_all_moves_both_unparseable_files_aside_inside_the_lock(env, tmp_path, monkeypatch):
    (tmp_path / "settings.json").write_text("{nope")
    (tmp_path / "secrets.json").write_text("{nada")
    held, seen, real_locked, real_replace = [False], [], store.locked, os.replace

    @contextlib.contextmanager
    def tracking(environ=None):
        with real_locked(environ) as got:
            held[0] = True
            try:
                yield got
            finally:
                held[0] = False

    def spy(src, dst, *a, **k):
        if str(dst).endswith(".corrupt"):
            seen.append(held[0])
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(store, "locked", tracking)
    monkeypatch.setattr(os, "replace", spy)
    assert api.handle("POST", "/api/settings/reset", {"all": True}, environ=env)[0] == 200
    assert seen == [True, True]
    assert (tmp_path / "settings.json.corrupt").read_text() == "{nope"
    assert (tmp_path / "secrets.json.corrupt").read_text() == "{nada"
    assert put(env, {"PLEX_TOKEN": SECRET})[0] == 200


def seed_connections(tmp_path):
    state = store.load({"CONFIG_DIR": str(tmp_path)})
    state.connections = [{"name": "local", "kind": "llamacpp", "url": "http://127.0.0.1:8090/v1"}]
    state.stages = {"repair": "local"}
    state.conn_keys = {"local": "conn-secret"}
    store.save(state, {"CONFIG_DIR": str(tmp_path)})


@pytest.mark.parametrize("body", [{"all": True}, {"category": "connections"}])
def test_reset_all_and_the_connections_category_clear_connections_stages_and_keys(env, tmp_path, body):
    seed_connections(tmp_path)
    status, payload = api.handle("POST", "/api/settings/reset", body, environ=env)
    assert status == 200 and {"connections", "stages"} <= set(payload["reset"])
    state = store.load(env)
    assert state.connections == [] and state.stages == {} and state.conn_keys == {}


def test_reset_without_secret_rights_keeps_connection_keys(env, tmp_path, monkeypatch):
    seed_connections(tmp_path)
    secrets_off(monkeypatch)
    assert api.handle("POST", "/api/settings/reset", {"all": True}, environ=env)[0] == 200
    state = store.load(env)
    assert state.connections == [] and state.conn_keys == {"local": "conn-secret"}


def test_the_server_routes_put_and_reset_through_the_settings_api(env, monkeypatch, tmp_path, capsys):
    import review_server as rs

    secrets_off(monkeypatch)
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    csrf = {review_auth.CSRF_HEADER: "1"}
    assert ("PUT", "/api/settings") not in rs.ADMIN_ROUTES and ("POST", "/api/settings/reset") not in rs.ADMIN_ROUTES
    assert rs.route("PUT", "/api/settings", {"values": {"WHISPER_BEAM_SIZE": 5}}, None, headers=csrf)[0] == 400  # no revision
    body = {"values": {"WHISPER_BEAM_SIZE": 5}, "revision": 0}
    status, payload = rs.route("PUT", "/api/settings", body, None, headers=csrf)
    assert status == 200 and payload["changed"] == ["WHISPER_BEAM_SIZE"]
    assert "settings saved by admin" in capsys.readouterr().out  # the open principal has no name
    reset = rs.route("POST", "/api/settings/reset", {"keys": ["WHISPER_BEAM_SIZE"]}, None, headers=csrf)
    assert reset[1]["reset"] == ["WHISPER_BEAM_SIZE"]
    assert ("POST", "/api/settings/reset") in rs._JSON_REQUIRED


def test_the_audit_line_names_the_calling_principal(env, monkeypatch, tmp_path, capsys):
    import review_server as rs

    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    principal = review_auth.Principal("session", "alice", "admin")
    decision = review_auth.Decision("admin", None, "", "admin", True, principal)
    monkeypatch.setattr(review_auth, "decide", lambda *a, **k: decision)
    status, _ = rs.route("PUT", "/api/settings", {"values": {"WHISPER_BEAM_SIZE": 5}, "revision": 0}, None)
    assert status == 200 and "settings saved by session:alice" in capsys.readouterr().out
