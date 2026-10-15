import importlib.util
import pathlib

import pytest

import review_server as rs

TOKEN = "retired-token"
PROBE = ("POST", "/api/_admin_probe")


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("REVIEW_TOKEN", TOKEN)
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    monkeypatch.setitem(rs.ADMIN_ROUTES, PROBE, lambda body: (200, {"ok": True}))
    return monkeypatch


def test_the_admin_token_module_and_its_helpers_are_gone():
    assert importlib.util.find_spec("review_admin") is None
    assert not any(hasattr(rs, name) for name in ("admin_guard", "admin_authorised", "ADMIN_HEADER", "review_admin"))
    assert "X-Review-Admin-Token" not in pathlib.Path(rs.__file__).read_text()


def test_the_alias_and_the_key_reach_an_admin_route_with_no_second_secret(env):
    assert rs.route("POST", "/api/_admin_probe", {}, TOKEN) == (200, {"ok": True})
    assert rs.route("POST", "/api/_admin_probe", {}, None, headers={"X-Api-Key": TOKEN}) == (200, {"ok": True})
    assert rs.route("POST", "/api/_admin_probe", {}, None)[0] == 401
    assert rs.route("POST", "/api/_admin_probe", {}, "wrong")[0] == 401


def test_a_configured_admin_token_changes_nothing(env):
    env.setenv("REVIEW_ADMIN_TOKEN", "old-admin")
    assert rs.route("POST", "/api/_admin_probe", {}, TOKEN, admin_token="wrong") == (200, {"ok": True})
    assert rs.route("POST", "/api/_admin_probe", {}, TOKEN, admin_token="old-admin") == (200, {"ok": True})


def test_auth_off_opens_admin_routes_as_before(env):
    env.setenv("REVIEW_AUTH", "off")
    assert rs.route("POST", "/api/_admin_probe", {}, None, headers={"X-DubTitlerr-Request": "1"}) == (200, {"ok": True})


def test_auth_mode_reports_only_setup_and_account_health(env):
    assert rs.route("GET", "/api/auth-mode", {}, None) == (200, {"setup_required": False, "accounts_ok": True})


def test_startup_says_once_that_the_admin_token_is_retired(env, tmp_path, capsys):
    env.setenv("CONFIG_DIR", str(tmp_path))
    env.setenv("REVIEW_ADMIN_TOKEN", "old-admin-secret")
    rs.startup_auth()
    out = capsys.readouterr().out
    assert out.count("REVIEW_ADMIN_TOKEN is retired") == 1 and "old-admin-secret" not in out
