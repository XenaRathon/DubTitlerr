import importlib.util
import pathlib
import re

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
    assert rs.route("POST", "/api/_admin_probe", {}, TOKEN) == (200, {"ok": True})


def test_admin_routes_are_open_with_auth_off(env):
    """With REVIEW_AUTH=off an admin route needs no credential at all (only the CSRF header). In 0.2.x the admin token kept
    these routes closed even with auth off; since it was retired, startup logs a loud warning instead."""
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


def test_the_registry_marks_the_admin_token_keys_retired_with_a_pointer_to_the_api_key():
    import settings_registry as reg

    by_key = {s["key"]: s for s in reg.schema()["settings"]}
    for key in ("REVIEW_ADMIN_TOKEN", "REVIEW_ADMIN_TOKEN_FILE"):
        entry = by_key[key]
        assert entry["managed_by"] == "retired" and entry["editable"] is False, key
        assert "retired" in entry["label"].lower() and "0.3.0" in entry["help"] and "API key" in entry["help"], key


def test_compose_no_longer_offers_the_admin_token_and_says_it_is_retired():
    text = (pathlib.Path(__file__).resolve().parent.parent / "compose.yaml").read_text()
    assert not [ln for ln in text.splitlines() if re.match(r"\s*#?\s*REVIEW_ADMIN_TOKEN(_FILE)?:", ln)], "no option line"
    assert "X-Review-Admin-Token" not in text
    assert "REVIEW_ADMIN_TOKEN is retired" in text and "Settings -> General -> Security" in text
