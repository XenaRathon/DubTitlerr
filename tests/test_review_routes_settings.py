"""/api/settings and /api/settings/test routes: role enforcement (admin for test, user for settings)."""

import pytest

import review_server as rs
import review_settings

TOKEN = "review-token"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEW_TOKEN", TOKEN)
    monkeypatch.delenv("REVIEW_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    monkeypatch.setattr(review_settings, "EFFECTIVE_ENV_PATH", str(tmp_path / "effective.env"))
    return tmp_path


def test_get_settings_auth_matrix(env):
    assert rs.route("GET", "/api/settings", {}, None)[0] == 401
    assert rs.route("GET", "/api/settings", {}, "wrong")[0] == 401
    status, payload = rs.route("GET", "/api/settings", {}, TOKEN)
    assert status == 200 and isinstance(payload, dict)


def test_settings_reports_secrets_as_presence_only(env, monkeypatch):
    monkeypatch.setenv("LONGCATAI_API_KEY", "sk-super-secret-value")
    _, payload = rs.route("GET", "/api/settings", {}, TOKEN)
    assert "sk-super-secret-value" not in str(payload)
    assert TOKEN not in str(payload)


def test_test_connection_needs_the_review_token_but_no_admin_token(env):
    body = {"backend": "repair"}
    assert rs.route("POST", "/api/settings/test", body, None)[0] == 401
    assert rs.route("POST", "/api/settings/test", body, "wrong")[0] == 401
    status, payload = rs.route("POST", "/api/settings/test", body, TOKEN)  # no admin token anywhere
    assert status == 200 and payload["ok"] in (True, False), payload
    assert status != 403


def test_test_connection_validates_its_body(env):
    assert rs.route("POST", "/api/settings/test", {}, TOKEN) == (400, {"error": "backend is required"})
    assert rs.route("POST", "/api/settings/test", {"backend": "x"}, TOKEN) == (400, {"error": "unsupported backend"})


def test_wrong_methods_on_the_settings_routes_do_not_exist(env):
    assert rs.route("POST", "/api/settings", {}, TOKEN)[0] == 404
    assert rs.route("GET", "/api/settings/test", {}, TOKEN)[0] == 404


def test_the_settings_routes_are_not_open(env):
    assert not any("settings" in p for _m, p in rs.OPEN_ROUTES)


def test_user_principal_gets_403_on_test_connection(env, tmp_path, monkeypatch):
    import review_auth

    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(review_auth, "SCRYPT_N", 2**4)
    review_auth.create_user("alice", "user", "user-password-10ch")
    sid = review_auth.sessions().create("alice", False)
    headers = {"Cookie": f"dubtitlerr_session={sid}", "X-DubTitlerr-Request": "1"}
    status, payload, _ = rs.route_full("POST", "/api/settings/test", {"backend": "repair"}, None, headers=headers)
    assert status == 403
    assert payload == {"error": "admin only"}
