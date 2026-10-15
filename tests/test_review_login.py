"""Optional username/password login in front of the review token (REVIEW_USERNAME + REVIEW_PASSWORD[_FILE]).

The token stays the only credential the server checks (authorised() is unchanged). /api/login merely hands that token to a human
who knows the password; unconfigured, the route does not exist."""

import http.client
import json
import secrets
import threading

import pytest

import review_server as rs

TOKEN = "fixture-token"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def login(monkeypatch, tmp_path):
    clock = Clock()
    for name in ("REVIEW_USERNAME", "REVIEW_PASSWORD", "REVIEW_PASSWORD_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REVIEW_TOKEN", TOKEN)
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    monkeypatch.setattr(rs, "_LOGIN", None)
    monkeypatch.setattr(rs, "_THROTTLE", rs.LoginThrottle(clock=clock))
    # Authenticated /api/episodes calls walk the library: keep that off the real roots and out of the shared caches.
    monkeypatch.setattr(rs, "ROOTS", [str(tmp_path / "media")])
    monkeypatch.setattr(rs, "_STEMS_CACHE", None)
    monkeypatch.setattr(rs, "_QUEUE_CACHE", {})

    def configure(user="reviewer", password="correct horse", **env):
        if user is not None:
            monkeypatch.setenv("REVIEW_USERNAME", user)
        if password is not None:
            monkeypatch.setenv("REVIEW_PASSWORD", password)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        rs.configure_login()

    configure.clock = clock
    configure.tmp = tmp_path
    return configure


def post(user, password, client="10.0.0.5"):
    return rs.route("POST", "/api/login", {"username": user, "password": password}, None, client=client)


# ---- the happy path and the refusals ----------------------------------------------------------------------------------------


def test_a_match_returns_the_server_token_and_nothing_else(login):
    login()
    assert post("reviewer", "correct horse") == (200, {"token": TOKEN})


@pytest.mark.parametrize(
    "user,password",
    [
        ("reviewer", "wrong"),
        ("someone", "correct horse"),
        ("", ""),
        ("reviewer", ""),
        ("", "correct horse"),
        (None, None),
        (5, ["x"]),
    ],
)
def test_anything_else_is_a_401_with_one_message(login, user, password):
    login()
    status, payload = post(user, password)
    assert (status, payload) == (401, {"error": "wrong username or password"})


def test_unicode_passwords_match_on_their_utf8_bytes(login):
    login(password="pässwörd-日本語-🔑")
    assert post("reviewer", "pässwörd-日本語-🔑")[0] == 200
    assert post("reviewer", "passwort-日本語-🔑")[0] == 401
    assert post("reviewer", "pässwörd-日本語-🔑")[0] == 401  # a different normalisation is a different password


def test_the_issued_token_works_against_the_unchanged_authorised(login):
    login()
    token = post("reviewer", "correct horse")[1]["token"]
    assert rs.authorised("GET", token) and not rs.authorised("GET", "nope")
    assert rs.route("GET", "/api/episodes", {}, token)[0] == 200
    assert rs.route("GET", "/api/episodes", {}, None)[0] == 401, "login does not open any other route"


# ---- configuration ------------------------------------------------------------------------------------------------------------


def test_unconfigured_the_route_is_a_404_and_auth_mode_says_so(login):
    assert rs.route("POST", "/api/login", {"username": "a", "password": "b"}, None) == (404, {"error": "no such route"})
    assert rs.route("GET", "/api/auth-mode", {}, None) == (200, {"password_login": False, "admin_enabled": False})


def test_configured_auth_mode_is_true_and_reveals_nothing_else(login):
    login()
    assert rs.route("GET", "/api/auth-mode", {}, None) == (200, {"password_login": True, "admin_enabled": False})


@pytest.mark.parametrize("user,password", [("", "secret"), ("reviewer", ""), ("", ""), ("reviewer", None), (None, "secret")])
def test_an_empty_or_half_configured_login_is_not_configured_never_open(login, capsys, user, password):
    login(user=user, password=password)
    assert rs.route("GET", "/api/auth-mode", {}, None) == (200, {"password_login": False, "admin_enabled": False})
    assert rs.route("POST", "/api/login", {"username": user or "", "password": password or ""}, None)[0] == 404
    if user is not None or password is not None:
        assert "login" in capsys.readouterr().out.lower(), "a half-set login is logged once at start"


def test_a_password_file_is_read_once_and_its_trailing_newline_stripped(login):
    f = login.tmp / "pw"
    f.write_text("from a file\n")
    login(password=None, REVIEW_PASSWORD_FILE=str(f))
    f.write_text("changed afterwards\n")
    assert post("reviewer", "from a file")[0] == 200
    assert post("reviewer", "changed afterwards")[0] == 401


def test_only_the_final_newline_is_stripped_from_a_password_file(login):
    f = login.tmp / "pw"
    f.write_bytes(b" spaced \r\n")
    login(password=None, REVIEW_PASSWORD_FILE=str(f))
    assert post("reviewer", " spaced ")[0] == 200


def test_an_empty_or_missing_password_file_is_not_configured(login):
    f = login.tmp / "pw"
    f.write_text("\n")
    login(password=None, REVIEW_PASSWORD_FILE=str(f))
    assert rs.route("GET", "/api/auth-mode", {}, None)[1] == {"password_login": False, "admin_enabled": False}
    login(password=None, REVIEW_PASSWORD_FILE=str(login.tmp / "nope"))
    assert rs.route("GET", "/api/auth-mode", {}, None)[1] == {"password_login": False, "admin_enabled": False}


# ---- constant time, logging, throttling -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user,password", [("reviewer", "correct horse"), ("wrong", "correct horse"), ("reviewer", "wrong"), ("", "")]
)
def test_both_fields_are_always_compared_in_constant_time(login, monkeypatch, user, password):
    login()
    calls = []
    real = secrets.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(rs.secrets, "compare_digest", spy)
    rs.route("POST", "/api/login", {"username": user, "password": password}, None)
    assert [type(a) for a, _ in calls[:2]] == [bytes, bytes], "utf-8 bytes, not str"
    assert len(calls) == 2, "no short circuit on the username"


def test_the_password_never_reaches_the_log_and_failures_read_alike(login, capsys):
    login(password="s3cr3t-pass-phrase")
    post("reviewer", "s3cr3t-pass-phrase")
    post("reviewer", "guess-one-s3cr3t")
    post("intruder", "s3cr3t-pass-phrase")
    out = capsys.readouterr().out
    assert "s3cr3t" not in out and "pass-phrase" not in out
    failures = [ln for ln in out.splitlines() if "login" in ln.lower() and "refused" in ln.lower()]
    assert len(failures) == 2 and len({ln for ln in failures}) == 1, "wrong password and wrong username are logged identically"
    assert "intruder" not in out


def test_five_failures_then_429_with_retry_after_then_recovery(login):
    login()
    for _ in range(5):
        assert post("reviewer", "wrong")[0] == 401
    status, payload = post("reviewer", "wrong")
    assert status == 429 and payload["retry_after"] == 60
    assert post("reviewer", "correct horse")[0] == 429, "even the right password waits out the lockout"
    login.clock.now += 30
    assert post("reviewer", "correct horse")[1]["retry_after"] == 30
    login.clock.now += 31
    assert post("reviewer", "correct horse")[0] == 200


def test_failures_outside_the_five_minute_window_do_not_add_up(login):
    login()
    for _ in range(4):
        post("reviewer", "wrong")
    login.clock.now += 301
    for _ in range(4):
        assert post("reviewer", "wrong")[0] == 401
    assert post("reviewer", "wrong")[0] == 401  # the fifth of the NEW window
    assert post("reviewer", "wrong")[0] == 429


def test_a_success_resets_the_count(login):
    login()
    for _ in range(4):
        post("reviewer", "wrong")
    assert post("reviewer", "correct horse")[0] == 200
    for _ in range(4):
        assert post("reviewer", "wrong")[0] == 401


def test_clients_are_throttled_separately(login):
    login()
    for _ in range(6):
        post("reviewer", "wrong", client="10.0.0.5")
    assert post("reviewer", "wrong", client="10.0.0.5")[0] == 429
    assert post("reviewer", "correct horse", client="10.0.0.9")[0] == 200


def test_tracked_addresses_are_capped_and_the_oldest_is_evicted():
    clock = Clock()
    t = rs.LoginThrottle(clock=clock, cap=3)
    for addr in ("a", "b", "c", "d"):
        t.failure(addr)
    assert len(t) == 3 and not t.tracked("a") and t.tracked("d")
    for _ in range(10_000):
        t.failure(f"flood-{_}")
    assert len(t) == 3


# ---- the open-route list, the Handler checks and the loopback end to end ----------------------------------------------------


def test_the_open_routes_are_exactly_these():
    assert set(rs.OPEN_ROUTES) == {("GET", "/healthz"), ("GET", "/api/auth-mode"), ("POST", "/api/login"), ("POST", "/api/setup")}


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/episodes"),
        ("GET", "/api/episode"),
        ("GET", "/api/audio"),
        ("GET", "/api/shared"),
        ("POST", "/api/decide"),
        ("POST", "/api/shared"),
        ("POST", "/api/apply"),
        ("GET", "/api/nope"),
    ],
)
def test_every_other_api_route_still_needs_the_token(login, method, path):
    login()
    assert rs.route(method, path, {}, None)[0] == 401


@pytest.fixture
def server(login):
    login()
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


def test_loopback_login_then_the_token_unlocks_the_api(server):
    status, raw, _ = request(server, "GET", "/api/auth-mode")
    assert (status, json.loads(raw)) == (200, {"password_login": True, "admin_enabled": False})
    status, raw, _ = request(server, "POST", "/api/login", {"username": "reviewer", "password": "correct horse"}, JSON)
    assert status == 200
    token = json.loads(raw)["token"]
    assert request(server, "GET", "/api/episodes", headers={rs.TOKEN_HEADER: token})[0] == 200
    assert request(server, "GET", "/api/episodes")[0] == 401


def test_loopback_failures_throttle_with_a_retry_after_header(server):
    for _ in range(5):
        assert request(server, "POST", "/api/login", {"username": "reviewer", "password": "no"}, JSON)[0] == 401
    status, raw, resp = request(server, "POST", "/api/login", {"username": "reviewer", "password": "no"}, JSON)
    assert status == 429 and resp.getheader("Retry-After") == "60"


def test_login_accepts_only_json_and_a_small_body(server):
    ok = {"username": "reviewer", "password": "correct horse"}
    assert request(server, "POST", "/api/login", ok, {"Content-Type": "text/plain"})[0] == 415
    assert request(server, "POST", "/api/login", ok, {"Content-Type": "application/x-www-form-urlencoded"})[0] == 415
    assert request(server, "POST", "/api/login", ok)[0] == 415, "no content type at all"
    assert request(server, "POST", "/api/login", ok, {"Content-Type": "application/json; charset=utf-8"})[0] == 200
    big = {"username": "reviewer", "password": "x" * 6000}
    assert request(server, "POST", "/api/login", big, JSON)[0] == 413
    unreadable = request(server, "POST", "/api/login", raw=b"not json", headers=JSON)
    assert unreadable[0] == 401, "an unreadable body is just a failed login"


def test_unconfigured_loopback_login_is_404(login):
    srv = rs.BoundedHTTPServer(("127.0.0.1", 0), rs.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        assert request(srv, "POST", "/api/login", {"username": "a", "password": "b"}, JSON)[0] == 404
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
