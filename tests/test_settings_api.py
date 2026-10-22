"""[S-3] [S-6] GET /api/settings/schema and GET /api/settings: values, their source, pending state, and no secret values."""

import json

import pytest

import review_auth
import settings_api as api
import settings_registry as reg
import settings_store as store

SECRET = "plex-secret-7c1e9a52b8d4"  # gitleaks:allow -- test fixture, not a real credential


@pytest.fixture
def env(tmp_path):
    return {"CONFIG_DIR": str(tmp_path), "EFFECTIVE_ENV_FILE": str(tmp_path / "effective.env")}


def values(env):
    status, payload = api.handle("GET", "/api/settings", environ=env)
    assert status == 200
    return payload


def stored(env, **kv):
    state = store.load(env)
    state.values.update(kv)
    store.save(state, env)


def test_the_schema_route_returns_the_registry(env):
    status, payload = api.handle("GET", "/api/settings/schema", environ=env)
    assert status == 200 and len(payload["categories"]) == 9
    assert {s["key"] for s in payload["settings"]} == set(reg.REGISTRY)


def test_a_container_value_is_reported_as_env_and_a_missing_one_as_default(env):
    env["REQUIRE_ENG"] = "0"
    v = values(env)["values"]
    assert v["REQUIRE_ENG"] == {"value": False, "source": "env", "overridden_env": False, "pending": False}
    assert v["REQUIRE_ENG"]["value"] == 0
    assert v["WHISPER_BEAM_SIZE"]["value"] == 7 and v["WHISPER_BEAM_SIZE"]["source"] == "default"


def test_a_stored_value_wins_and_flags_the_env_it_overrides(env):
    env["REQUIRE_ENG"] = "0"
    stored(env, REQUIRE_ENG=True)
    entry = values(env)["values"]["REQUIRE_ENG"]
    assert entry["value"] is True and entry["source"] == "ui" and entry["overridden_env"] is True


def test_an_env_value_the_registry_cannot_parse_is_shown_raw_and_marked(env):
    env["WHISPER_BEAM_SIZE"] = "lots"
    entry = values(env)["values"]["WHISPER_BEAM_SIZE"]
    assert entry["value"] == "lots" and entry["env_invalid"] is True


def test_secrets_are_a_set_flag_and_never_a_value(env):
    env["PLEX_TOKEN"] = SECRET
    env["REVIEW_TOKEN"] = SECRET + "-review"
    payload = values(env)
    assert payload["values"]["PLEX_TOKEN"] == {"set": True, "source": "env", "overridden_env": False, "pending": False}
    assert payload["values"]["WATCHSTATE_API_KEY"]["set"] is False
    assert SECRET not in json.dumps(payload)


def test_pending_compares_the_stored_value_with_what_the_builder_reports(env, tmp_path):
    stored(env, WHISPER_BEAM_SIZE=5)
    assert values(env)["values"]["WHISPER_BEAM_SIZE"]["pending"] is True
    (tmp_path / "effective.env").write_text("WHISPER_BEAM_SIZE=5\n")
    assert values(env)["values"]["WHISPER_BEAM_SIZE"]["pending"] is False


def test_a_reset_that_the_builder_has_not_seen_yet_is_pending(env, tmp_path):
    (tmp_path / "effective.env").write_text("WHISPER_BEAM_SIZE=5\n")
    assert values(env)["values"]["WHISPER_BEAM_SIZE"]["pending"] is True


def test_merge_scope_keys_are_compared_with_the_merge_report(env, tmp_path):
    stored(env, REPAIR_UNANCHORED=True)
    (tmp_path / "effective.env").write_text("REPAIR_UNANCHORED=1\n")
    assert values(env)["values"]["REPAIR_UNANCHORED"]["pending"] is True
    (tmp_path / "merge-effective.env").write_text("REPAIR_UNANCHORED=1\n")
    assert values(env)["values"]["REPAIR_UNANCHORED"]["pending"] is False


def test_a_restart_key_is_pending_until_the_process_runs_with_it(env):
    stored(env, REVIEW_PORT=9000)
    payload = values(env)
    assert payload["values"]["REVIEW_PORT"]["pending"] is True and payload["restart_pending"] is True
    env["REVIEW_PORT"] = "9000"
    env["DT_BOOT_REVIEW_PORT"] = "8842"
    payload = values(env)
    assert payload["values"]["REVIEW_PORT"]["pending"] is False and payload["restart_pending"] is False
    assert payload["values"]["REVIEW_PORT"]["overridden_env"] is True


def test_a_corrupt_store_falls_back_to_the_environment_and_says_why(env, tmp_path):
    (tmp_path / "settings.json").write_text("{nope")
    env["WHISPER_BEAM_SIZE"] = "3"
    payload = values(env)
    assert "not valid JSON" in payload["store_error"]
    assert payload["values"]["WHISPER_BEAM_SIZE"]["value"] == 3 and payload["values"]["WHISPER_BEAM_SIZE"]["source"] == "env"


def test_retired_env_vars_that_are_still_set_are_listed(env):
    env["REPAIR_PROFILES"] = "{}"
    env["RUNTIME_DECISION_MODELS"] = "m"
    assert values(env)["retired_env"] == ["REPAIR_PROFILES", "RUNTIME_DECISION_MODELS"]


def test_every_settings_route_is_in_the_role_table_entries():
    assert api.ROLE_ENTRIES[("GET", "/api/settings")] == "user"
    assert api.ROLE_ENTRIES[("GET", "/api/settings/schema")] == "user"
    for route in [
        ("PUT", "/api/settings"),
        ("POST", "/api/settings/reset"),
        ("POST", "/api/settings/test"),
        ("POST", "/api/system/restart"),
    ]:
        assert api.ROLE_ENTRIES[route] == "admin"


def test_review_server_registers_the_entries_and_serves_the_routes(monkeypatch, tmp_path):
    import review_server as rs

    monkeypatch.setenv("REVIEW_AUTH", "off")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    assert api.ROLE_ENTRIES.items() <= review_auth.ROUTE_ROLES.items()
    status, payload = rs.route("GET", "/api/settings/schema", {}, None)
    assert status == 200 and "categories" in payload
    status, payload = rs.route("GET", "/api/settings", {}, None)
    assert status == 200 and "values" in payload and "restart_pending" in payload


def test_get_redacts_credentials_in_urls_and_hides_extra_bodies(env):
    env["PLEX_URL"] = "https://u:pw@plex.lan:32400/x?X-Plex-Token=t"
    env["VERIFY_OPENAI_URL"] = "http://h/v1?key=k"
    env["VERIFY_OPENAI_EXTRA_BODY"] = '{"api_key":"sk-x"}'
    env["REPAIR_EXTRA_BODY"] = ""
    env["SUBS_REPO"] = "HTTPS://u:secret_tok@github.com/x"
    env["SHOWS"] = "Show1,https://u:secret_mid@h"
    env["WATCH_QUEUE_PIN"] = "ssh://u:secret_ssh@h"
    payload = values(env)
    text = json.dumps(payload)
    for leaked in ("u:pw", "X-Plex-Token", "key=k", "sk-x", "api_key", "secret_tok", "secret_mid", "secret_ssh"):
        assert leaked not in text
    assert payload["values"]["PLEX_URL"]["value"] == "https://plex.lan:32400/x"
    assert payload["values"]["SUBS_REPO"]["value"] == "HTTPS://github.com/x"
    assert payload["values"]["SHOWS"]["value"] == "Show1,https://h"
    assert payload["values"]["WATCH_QUEUE_PIN"]["value"] == "ssh://h"
    assert payload["values"]["VERIFY_OPENAI_EXTRA_BODY"]["set"] is True
    assert "value" not in payload["values"]["VERIFY_OPENAI_EXTRA_BODY"]
    assert payload["values"]["REPAIR_EXTRA_BODY"]["set"] is False


def test_a_stored_extra_body_is_not_echoed_either(env):
    stored(env, VERIFY_OPENAI_EXTRA_BODY='{"api_key":"sk-y"}')
    assert "sk-y" not in json.dumps(values(env))


@pytest.mark.parametrize(
    ("auth_on", "setup", "expected"), [(True, False, True), (True, True, False), (False, False, False), (False, True, False)]
)
def test_secrets_writable_needs_auth_on_and_no_pending_setup(env, monkeypatch, auth_on, setup, expected):
    monkeypatch.setattr(api.review_auth, "auth_on", lambda: auth_on)
    monkeypatch.setattr(api.review_auth, "setup_required", lambda: setup)
    assert api._secrets_writable() is expected
    assert values(env)["secrets_writable"] is expected


def test_a_secrets_error_makes_secrets_read_only(env, tmp_path, monkeypatch):
    monkeypatch.setattr(api.review_auth, "auth_on", lambda: True)
    monkeypatch.setattr(api.review_auth, "setup_required", lambda: False)
    (tmp_path / "secrets.json").write_text("{nope")
    assert values(env)["secrets_writable"] is False
