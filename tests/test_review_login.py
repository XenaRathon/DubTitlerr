"""Account login: POST /api/login, /api/logout, GET /api/me and the cookie they hand out (specs/webui-login-roles S-3, S-4)."""

import hashlib
import http.client
import json
import threading
import types

import pytest

import glossary_lock
import review_auth
import review_server as rs

pytestmark = pytest.mark.real_accounts
KEY = "login-key"
PASSWORD = "correct horse"
CSRF = {"X-DubTitlerr-Request": "1"}


class Clock:
    def __init__(self, now=2_000_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def env(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("REVIEW_TOKEN", KEY)
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    monkeypatch.setattr(review_auth, "CLOCK", clock)
    monkeypatch.setattr(review_auth, "SCRYPT_N", 2**4)
    monkeypatch.setattr(rs, "_THROTTLE", rs.LoginThrottle(clock=clock))
    monkeypatch.setattr(rs, "ROOTS", [str(tmp_path / "media")])
    monkeypatch.setattr(rs, "_STEMS_CACHE", None)
    monkeypatch.setattr(rs, "_QUEUE_CACHE", {})
    review_auth.create_user("Reviewer", "admin", PASSWORD)
    return types.SimpleNamespace(clock=clock, tmp=tmp_path)


def login(user="reviewer", password=PASSWORD, remember=False, client="10.0.0.5", headers=None):
    body = {"username": user, "password": password, "remember": remember}
    return rs.route_full("POST", "/api/login", body, None, client=client, headers=headers or {})


def set_cookie(extra):
    """The session cookie line; a login also sends a second Set-Cookie that clears the legacy token cookie."""
    value = extra["Set-Cookie"]
    return value[0] if isinstance(value, list) else value


def cookie_of(extra):
    return set_cookie(extra).split(";", 1)[0]


def me(cookie):
    return rs.route("GET", "/api/me", {}, None, headers={"Cookie": cookie})


def test_a_correct_login_sets_an_httponly_samesite_strict_cookie_and_me_returns_the_user(env):
    status, payload, extra = login()
    assert (status, payload) == (200, {"username": "Reviewer", "role": "admin", "token": KEY})  # "token": transitional, Task 15
    flags = set_cookie(extra).split("; ")
    assert flags[0].startswith("dubtitlerr_session=") and {"Path=/", "HttpOnly", "SameSite=Strict"} <= set(flags)
    assert "Secure" not in flags and not any(f.startswith("Max-Age") for f in flags), "a browser-session cookie over plain http"
    assert me(cookie_of(extra)) == (200, {"username": "Reviewer", "role": "admin"})


def test_remember_me_adds_a_30_day_max_age_and_https_adds_secure(env):
    flags = set_cookie(login(remember=True, headers={"X-Forwarded-Proto": "https"})[2]).split("; ")
    assert "Max-Age=2592000" in flags and "Secure" in flags


@pytest.mark.parametrize(
    "user,password", [("reviewer", "wrong password"), ("nobody", PASSWORD), ("", ""), (5, ["x"]), (None, None)]
)
def test_a_wrong_username_and_a_wrong_password_give_the_same_401(env, user, password):
    assert login(user, password)[:2] == (401, {"error": "wrong username or password"})


@pytest.mark.parametrize(
    "user,password", [("Reviewer", PASSWORD), ("nobody", PASSWORD), ("Reviewer", "wrong password"), ("", ""), (5, ["x"])]
)
def test_every_attempt_costs_exactly_one_scrypt(env, monkeypatch, user, password):
    review_auth.dummy_hash()
    calls, real = [], hashlib.scrypt
    monkeypatch.setattr(review_auth.hashlib, "scrypt", lambda *a, **k: calls.append(1) or real(*a, **k))
    login(user, password)
    assert len(calls) == 1


def test_neither_the_password_nor_a_session_id_reaches_the_log_and_failures_read_alike(env, capsys):
    ok = login(password=PASSWORD)
    login(password="guess-one-pass")
    login(user="intruder", password=PASSWORD)
    out = capsys.readouterr().out
    assert PASSWORD not in out and "guess-one" not in out and "intruder" not in out
    assert cookie_of(ok[2]).split("=", 1)[1] not in out
    refusals = [ln for ln in out.splitlines() if "login refused" in ln]
    assert len(refusals) == 2 and len(set(refusals)) == 1


def test_five_failures_then_429_with_retry_after_then_recovery(env):
    for _ in range(5):
        assert login(password="wrong password")[0] == 401
    status, payload, _ = login(password="wrong password")
    assert status == 429 and payload["retry_after"] == 60
    assert login()[0] == 429, "even the right password waits out the lockout"
    env.clock.now += 61
    assert login()[0] == 200


def test_a_success_resets_the_count_and_clients_are_throttled_separately(env):
    for _ in range(4):
        login(password="wrong password")
    assert login()[0] == 200
    for i in range(5):  # other names, so only the address is counted
        login(user=f"ghost{i}", password="wrong password", client="10.0.0.6")
    assert login(client="10.0.0.6")[0] == 429 and login(client="10.0.0.5")[0] == 200


def test_failures_against_one_username_from_many_addresses_lock_that_username(env):
    for i in range(5):
        assert login(password="wrong password", client=f"10.0.1.{i}")[0] == 401
    assert login(client="10.0.1.99")[0] == 429, "behind a proxy the address is shared; the name is counted too"


def test_a_login_clears_the_legacy_token_cookie_and_the_old_token_only_comes_back_for_an_admin(env):
    extra = login()[2]
    assert set_cookie(extra).startswith("dubtitlerr_session=")
    assert any(c.startswith("dubtitlerr_token=;") and "Max-Age=0" in c for c in extra["Set-Cookie"])
    review_auth.create_user("viewer", "user", "viewer password")
    status, payload, _ = login(user="viewer", password="viewer password")
    assert status == 200 and "token" not in payload, "the transitional token field is for admins only"


def test_is_https_documents_that_native_tls_is_not_served():
    assert "native TLS is not served" in review_auth.is_https.__doc__
    assert review_auth.is_https({"X-Forwarded-Proto": "https"}) and not review_auth.is_https({})


def test_every_login_gets_a_new_session_id_even_when_the_browser_presents_an_old_one(env):
    first = cookie_of(login()[2])
    second = cookie_of(login(headers={"Cookie": first})[2])
    third = cookie_of(login()[2])
    assert len({first, second, third}) == 3 and me(first)[0] == me(second)[0] == me(third)[0] == 200


def test_logout_ends_the_session_and_clears_the_cookie(env):
    cookie = cookie_of(login()[2])
    status, payload, extra = rs.route_full("POST", "/api/logout", {}, None, headers={"Cookie": cookie, **CSRF})
    assert (status, payload) == (200, {"ok": True}) and "Max-Age=0" in extra["Set-Cookie"]
    assert me(cookie)[0] == 401


def test_me_for_the_api_key_and_for_nobody(env):
    assert rs.route("GET", "/api/me", {}, None, headers={"X-Api-Key": KEY}) == (200, {"username": "api key", "role": "admin"})
    assert rs.route("GET", "/api/me", {}, None) == (401, {"error": "login required"})


def test_a_remember_me_cookie_is_reissued_after_a_day_of_use(env):
    cookie = cookie_of(login(remember=True)[2])
    assert "Set-Cookie" not in rs.route_full("GET", "/api/me", {}, None, headers={"Cookie": cookie})[2]
    env.clock.now += 2 * 86400
    refreshed = rs.route_full("GET", "/api/me", {}, None, headers={"Cookie": cookie})[2]
    assert refreshed["Set-Cookie"].startswith(cookie) and "Max-Age=2592000" in refreshed["Set-Cookie"]


def test_before_setup_login_is_409_and_with_an_unreadable_file_it_is_503(env):
    (env.tmp / "config" / "users.json").write_text("{not json")
    status, payload, _ = login()
    assert status == 503 and "unreadable" in payload["error"]
    (env.tmp / "config" / "users.json").unlink()
    assert login()[:2] == (409, {"error": "setup required"})


def test_logged_in_requests_keep_answering_while_a_glossary_lock_is_held(env):
    cookie = cookie_of(login()[2])
    with glossary_lock.locked(str(env.tmp / "g.json"), "acquire", wait=0):
        assert [me(cookie)[0] for _ in range(3)] == [200, 200, 200]


def test_auth_mode_reports_setup_and_account_health_and_nothing_secret(env):
    status, payload = rs.route("GET", "/api/auth-mode", {}, None)
    assert status == 200 and payload["setup_required"] is False and payload["accounts_ok"] is True
    assert payload["password_login"] is True and payload["admin_enabled"] is False
    assert KEY not in json.dumps(payload) and PASSWORD not in json.dumps(payload)
    (env.tmp / "config" / "users.json").write_text("{not json")
    assert rs.route("GET", "/api/auth-mode", {}, None)[1]["accounts_ok"] is False


def test_tracked_addresses_are_capped_and_the_oldest_is_evicted():
    clock = Clock()
    t = rs.LoginThrottle(clock=clock, cap=3)
    for addr in ("a", "b", "c", "d"):
        t.failure(addr)
    assert len(t) == 3 and not t.tracked("a") and t.tracked("d")
    for i in range(10_000):
        t.failure(f"flood-{i}")
    assert len(t) == 3


@pytest.fixture
def server(env):
    srv = rs.BoundedHTTPServer(("127.0.0.1", 0), rs.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def request(srv, method, path, body=None, headers=None, raw=None):
    conn = http.client.HTTPConnection(*srv.server_address, timeout=5)
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    conn.request(method, path, body=data, headers=headers or {})
    r = conn.getresponse()
    out = (r.status, r.read(), r)
    conn.close()
    return out


JSON = {"Content-Type": "application/json"}


def test_loopback_login_hands_out_a_cookie_that_unlocks_reads(server):
    status, raw, resp = request(server, "POST", "/api/login", {"username": "reviewer", "password": PASSWORD}, JSON)
    assert status == 200 and json.loads(raw)["role"] == "admin"
    cookie = resp.getheader("Set-Cookie").split(";", 1)[0]
    assert request(server, "GET", "/api/episodes", headers={"Cookie": cookie})[0] == 200
    assert request(server, "GET", "/api/episodes")[0] == 401
    assert request(server, "GET", "/api/episodes", headers={"Cookie": f"dubtitlerr_token={KEY}"})[0] == 401, (
        "the legacy cookie is for the classic pages only"
    )


def test_loopback_throttle_answers_429_with_a_retry_after_header(server):
    for _ in range(5):
        assert request(server, "POST", "/api/login", {"username": "reviewer", "password": "no"}, JSON)[0] == 401
    status, _, resp = request(server, "POST", "/api/login", {"username": "reviewer", "password": "no"}, JSON)
    assert status == 429 and resp.getheader("Retry-After") == "60"


def test_login_accepts_only_json_and_a_small_body(server):
    ok = {"username": "reviewer", "password": PASSWORD}
    assert request(server, "POST", "/api/login", ok, {"Content-Type": "text/plain"})[0] == 415
    assert request(server, "POST", "/api/login", ok)[0] == 415
    assert request(server, "POST", "/api/login", ok, {"Content-Type": "application/json; charset=utf-8"})[0] == 200
    assert request(server, "POST", "/api/login", {"username": "reviewer", "password": "x" * 6000}, JSON)[0] == 413
    assert request(server, "POST", "/api/login", raw=b"not json", headers=JSON)[0] == 401, "an unreadable body is a failed login"


def test_the_classic_pages_accept_a_session_and_otherwise_point_at_setup_or_login(server, env):
    cookie = cookie_of(login()[2])
    page = request(server, "GET", "/", headers={"Cookie": cookie})
    assert page[0] == 200 and b"needs-token" not in page[1]
    locked = request(server, "GET", "/")
    assert b"needs-token" in locked[1] and b"/review/login" in locked[1]
    (env.tmp / "config" / "users.json").unlink()
    assert b"/review/setup" in request(server, "GET", "/shared")[1]
