"""Admin-token plumbing in review_server (specs/webui-admin-token): the route() argument, the header-only read in
the HTTP layer, the 401-then-403 order, and admin_enabled on /api/auth-mode.

The real guarded routes (settings, run requests, schedule) do not exist yet, so a tiny probe route is registered
in ADMIN_ROUTES for the length of each test."""

import http.client
import json
import threading

import pytest

import review_server as rs

TOKEN = "review-fixture-token"
ADMIN = "admin-fixture-token"
PROBE = ("POST", "/api/_admin_probe")


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("REVIEW_TOKEN", TOKEN)
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    monkeypatch.delenv("REVIEW_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("REVIEW_ADMIN_TOKEN_FILE", raising=False)
    monkeypatch.setitem(rs.ADMIN_ROUTES, PROBE, lambda body: (200, {"ok": True, "echo": body.get("x")}))
    monkeypatch.setitem(rs.ADMIN_ROUTES, ("GET", "/api/_admin_probe_get"), lambda body: (200, {"ok": True}))
    return monkeypatch


def call(token=TOKEN, admin=None, body=None):
    kwargs = {} if admin is None else {"admin_token": admin}
    return rs.route("POST", "/api/_admin_probe", body or {}, token, headers={"X-DubTitlerr-Request": "1"}, **kwargs)


def test_unset_admin_token_disables_the_guarded_route_with_403(env):
    assert call(admin=ADMIN) == (403, {"error": "admin writes are disabled"})
    assert call() == (403, {"error": "admin writes are disabled"}), "omitting the argument must not open it"


def test_disabled_means_disabled_even_with_review_auth_off(env):
    env.setenv("REVIEW_AUTH", "off")
    assert call(token=None, admin="anything") == (403, {"error": "admin writes are disabled"})


def test_a_wrong_or_missing_admin_token_is_403(env):
    env.setenv("REVIEW_ADMIN_TOKEN", ADMIN)
    assert call(admin="nope") == (403, {"error": "admin token required"})
    assert call() == (403, {"error": "admin token required"})
    assert call(admin="") == (403, {"error": "admin token required"})


def test_the_review_token_is_checked_first_so_a_missing_one_is_401(env):
    assert call(token=None, admin=ADMIN) == (401, {"error": "login required"}), "admin unset"
    env.setenv("REVIEW_ADMIN_TOKEN", ADMIN)
    assert call(token=None, admin=ADMIN) == (401, {"error": "login required"}), "admin right"
    assert call(token="wrong", admin=ADMIN)[0] == 401


def test_both_tokens_reach_the_handler(env):
    env.setenv("REVIEW_ADMIN_TOKEN", ADMIN)
    assert call(admin=ADMIN, body={"x": 7}) == (200, {"ok": True, "echo": 7})


def test_the_admin_check_still_runs_when_review_auth_is_off(env):
    env.setenv("REVIEW_AUTH", "off")
    env.setenv("REVIEW_ADMIN_TOKEN", ADMIN)
    assert call(token=None, admin="bad")[0] == 403
    assert call(token=None, admin=ADMIN)[0] == 200


def test_admin_authorised_helper_wraps_check_admin(env):
    assert rs.admin_authorised(ADMIN) is False
    env.setenv("REVIEW_ADMIN_TOKEN", ADMIN)
    assert rs.admin_authorised(ADMIN) is True
    assert rs.admin_authorised("x") is False and rs.admin_authorised(None) is False


def test_existing_callers_that_omit_admin_token_still_work(env):
    assert rs.route("GET", "/api/episodes", {}, None)[0] == 401
    assert rs.route("GET", "/api/nothing-here", {}, TOKEN)[0] == 404


def test_auth_mode_reports_admin_enabled(env):
    assert rs.route("GET", "/api/auth-mode", {}, None)[1]["admin_enabled"] is False
    env.setenv("REVIEW_ADMIN_TOKEN", ADMIN)
    assert rs.route("GET", "/api/auth-mode", {}, None)[1]["admin_enabled"] is True


def test_auth_mode_never_reveals_the_token(env):
    env.setenv("REVIEW_ADMIN_TOKEN", ADMIN)
    assert ADMIN not in json.dumps(rs.route("GET", "/api/auth-mode", {}, None)[1])


def test_open_routes_are_unchanged():
    assert set(rs.OPEN_ROUTES) == {("GET", "/healthz"), ("GET", "/api/auth-mode"), ("POST", "/api/login"), ("POST", "/api/setup")}


# --- the HTTP layer: header only -------------------------------------------------------------------------------------


@pytest.fixture
def server(env):
    env.setenv("REVIEW_ADMIN_TOKEN", ADMIN)
    srv = rs.BoundedHTTPServer(("127.0.0.1", 0), rs.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def post(srv, path="/api/_admin_probe", headers=None, body=None):
    conn = http.client.HTTPConnection(*srv.server_address, timeout=5)
    h = {"Content-Type": "application/json", **(headers or {})}
    conn.request("POST", path, body=json.dumps(body or {}), headers=h)
    r = conn.getresponse()
    out = (r.status, json.loads(r.read() or b"{}"))
    conn.close()
    return out


def test_the_header_is_read_by_the_http_layer(server):
    ok = {rs.TOKEN_HEADER: TOKEN, "X-Review-Admin-Token": ADMIN}
    assert post(server, headers=ok)[0] == 200
    assert post(server, headers={rs.TOKEN_HEADER: TOKEN, "X-Review-Admin-Token": "bad"}) == (
        403,
        {"error": "admin token required"},
    )
    assert post(server, headers={rs.TOKEN_HEADER: TOKEN})[0] == 403
    assert post(server, headers={"X-Review-Admin-Token": ADMIN})[0] == 401


def test_a_cookie_or_query_admin_token_is_ignored(server):
    base = {rs.TOKEN_HEADER: TOKEN}
    cookie = {**base, "Cookie": f"X-Review-Admin-Token={ADMIN}; admin_token={ADMIN}; review_admin={ADMIN}"}
    assert post(server, headers=cookie)[0] == 403
    conn = http.client.HTTPConnection(*server.server_address, timeout=5)
    conn.request("GET", f"/api/_admin_probe_get?admin_token={ADMIN}&X-Review-Admin-Token={ADMIN}", headers=base)
    assert conn.getresponse().status == 403
    conn.close()
    assert post(server, headers=base, body={"admin_token": ADMIN, "X-Review-Admin-Token": ADMIN})[0] == 403
