"""/api/requests and /api/schedule through route(): review token for reads, review token plus admin token for writes."""

import json

import pytest

import review_requests
import review_server as rs

TOKEN = "review-token"
ADMIN = "admin-token"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEW_TOKEN", TOKEN)
    monkeypatch.setenv("REVIEW_ADMIN_TOKEN", ADMIN)
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    monkeypatch.setattr(rs, "_LOGIN", None)
    root = tmp_path / "Anime"
    (root / "One Pace").mkdir(parents=True)
    monkeypatch.setenv("ANIME_ROOT", str(root))
    monkeypatch.setenv("REQUESTS_DIR", str(tmp_path / "requests"))
    monkeypatch.setattr(review_requests, "REQUESTS_DIR", str(tmp_path / "requests"))
    return tmp_path


BODY = {"show": "One Pace", "season": 31}


def test_get_requests_needs_the_review_token_only(env):
    assert rs.route("GET", "/api/requests", {}, None)[0] == 401
    assert rs.route("GET", "/api/requests", {}, "wrong")[0] == 401
    assert rs.route("GET", "/api/requests", {}, TOKEN) == (200, [])
    assert rs.route("GET", "/api/requests", {}, TOKEN, admin_token="nope")[0] == 200, "reads ignore the admin token"


def test_post_requests_auth_matrix(env):
    assert rs.route("POST", "/api/requests", BODY, None)[0] == 401
    assert rs.route("POST", "/api/requests", BODY, "wrong", admin_token=ADMIN)[0] == 401
    assert rs.route("POST", "/api/requests", BODY, TOKEN) == (403, {"error": "admin token required"})
    assert rs.route("POST", "/api/requests", BODY, TOKEN, admin_token="wrong") == (
        403,
        {"error": "admin token required"},
    )
    status, payload = rs.route("POST", "/api/requests", BODY, TOKEN, admin_token=ADMIN)
    assert status == 201 or status == 200, payload
    assert payload.get("id")


def test_post_requests_is_disabled_without_an_admin_token(env, monkeypatch):
    monkeypatch.delenv("REVIEW_ADMIN_TOKEN")
    assert rs.route("POST", "/api/requests", BODY, TOKEN, admin_token=ADMIN) == (
        403,
        {"error": "admin writes are disabled"},
    )
    assert not (env / "requests").exists() or not list((env / "requests").iterdir())


def test_a_created_request_is_listed_and_uses_anime_root_from_the_environment(env):
    _, made = rs.route("POST", "/api/requests", BODY, TOKEN, admin_token=ADMIN)
    _, listed = rs.route("GET", "/api/requests", {}, TOKEN)
    assert [r["id"] for r in listed] == [made["id"]]
    assert listed[0]["show"] == "One Pace"
    # a show that is not under ANIME_ROOT is refused by the module, and the route passes its answer through
    status, payload = rs.route("POST", "/api/requests", {"show": "Nope"}, TOKEN, admin_token=ADMIN)
    assert status == 400 and "show directory not found" in payload["error"]


def test_the_request_routes_are_not_open(env):
    assert not any("requests" in p or "schedule" in p for _m, p in rs.OPEN_ROUTES)
    assert set(rs.OPEN_ROUTES) == {("GET", "/healthz"), ("GET", "/api/auth-mode"), ("POST", "/api/login")}


# --- schedule: written against review_requests.handle('/api/schedule'); skipped until it supports it ------------------

needs_schedule = pytest.mark.skipif(
    not hasattr(review_requests, "get_schedule"),
    reason="review_requests.handle does not serve /api/schedule yet (get_schedule/put_schedule are being added)",
)


@needs_schedule
def test_get_schedule_needs_the_review_token_only(env):
    assert rs.route("GET", "/api/schedule", {}, None)[0] == 401
    assert rs.route("GET", "/api/schedule", {}, "wrong")[0] == 401
    assert rs.route("GET", "/api/schedule", {}, TOKEN)[0] == 200


@needs_schedule
def test_put_schedule_auth_matrix(env):
    body = {"start": "02:00", "end": "09:00"}
    assert rs.route("PUT", "/api/schedule", body, None)[0] == 401
    assert rs.route("PUT", "/api/schedule", body, TOKEN) == (403, {"error": "admin token required"})
    assert rs.route("PUT", "/api/schedule", body, TOKEN, admin_token="wrong")[0] == 403
    status, payload = rs.route("PUT", "/api/schedule", body, TOKEN, admin_token=ADMIN)
    assert status in (200, 400), payload  # the module decides what a valid schedule is; the route must reach it
    assert status != 404


def test_put_schedule_is_guarded_even_before_the_module_supports_it(env):
    """The admin check must run first, so an unauthorised caller never reaches the (possibly missing) handler."""
    assert rs.route("PUT", "/api/schedule", {}, TOKEN) == (403, {"error": "admin token required"})


def test_the_http_layer_serves_put_with_the_admin_header(env):
    import http.client
    import threading

    srv = rs.BoundedHTTPServer(("127.0.0.1", 0), rs.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:

        def put(headers):
            conn = http.client.HTTPConnection(*srv.server_address, timeout=5)
            conn.request("PUT", "/api/schedule", body=json.dumps({}), headers={"Content-Type": "application/json", **headers})
            r = conn.getresponse()
            out = (r.status, json.loads(r.read() or b"{}"))
            conn.close()
            return out

        assert put({})[0] == 401
        assert put({rs.TOKEN_HEADER: TOKEN}) == (403, {"error": "admin token required"})
        assert put({rs.TOKEN_HEADER: TOKEN, "X-Review-Admin-Token": ADMIN})[0] != 403
    finally:
        srv.shutdown()
        srv.server_close()
