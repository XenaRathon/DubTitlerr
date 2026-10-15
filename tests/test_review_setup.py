import http.client
import json
import stat
import threading

import pytest

import review_auth
import review_server as rs

pytestmark = pytest.mark.real_accounts
KEY = "setup-key"
FIRST = {"username": "Admin", "password": "first-admin-pass"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("REVIEW_USERNAME", "REVIEW_PASSWORD", "REVIEW_PASSWORD_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("REVIEW_TOKEN", KEY)
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    monkeypatch.setattr(review_auth, "SCRYPT_N", 2**4)
    monkeypatch.setattr(rs, "ROOTS", [str(tmp_path / "media")])
    monkeypatch.setattr(rs, "_STEMS_CACHE", None)
    monkeypatch.setattr(rs, "_QUEUE_CACHE", {})
    return tmp_path


def test_before_setup_a_cookie_less_api_call_is_409(env):
    assert rs.route("GET", "/api/episodes", {}, None) == (409, {"error": "setup required"})


def test_before_setup_the_api_key_still_reads_and_so_does_the_old_token(env):
    assert rs.route("GET", "/api/episodes", {}, None, headers={"X-Api-Key": KEY})[0] == 200
    assert rs.route("GET", "/api/episodes", {}, KEY)[0] == 200


def test_before_setup_a_webhook_with_its_url_secret_is_accepted(env, monkeypatch):
    monkeypatch.setattr(rs.review_webhooks, "handle", lambda *a, **k: (202, {"ok": True}))
    assert rs.route("POST", "/api/webhook/sonarr", b"{}", None) == (202, {"ok": True})


def test_the_spa_document_is_served_for_the_setup_and_login_urls(env, monkeypatch):
    (env / "dist").mkdir()
    (env / "dist" / "index.html").write_text("<!doctype html>spa")
    monkeypatch.setattr(rs, "UI_DIST", env / "dist")
    for path in ("/review", "/review/", "/review/setup", "/review/login"):
        assert rs.route("GET", path, {}, None) == (200, b"<!doctype html>spa"), path


def test_setup_creates_the_first_admin_with_a_0600_scrypt_file_and_no_password(env):
    assert rs.route("POST", "/api/setup", FIRST, None) == (200, {"username": "Admin", "role": "admin"})
    path = env / "config" / "users.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    raw = path.read_text()
    assert "scrypt$" in raw and "first-admin-pass" not in raw
    assert rs.route("GET", "/api/episodes", {}, None) == (401, {"error": "login required"}), "setup is over"


def test_a_second_setup_is_409_already_set_up(env):
    rs.route("POST", "/api/setup", FIRST, None)
    assert rs.route("POST", "/api/setup", {"username": "other", "password": "another-long-pass"}, None) == (
        409,
        {"error": "already set up"},
    )


def test_two_browsers_racing_setup_one_wins_and_the_other_gets_409(env):
    results = []
    barrier = threading.Barrier(2)

    def go(name):
        barrier.wait()
        results.append(rs.route("POST", "/api/setup", {"username": name, "password": "racing-password"}, None)[0])

    threads = [threading.Thread(target=go, args=(n,)) for n in ("one", "two")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [200, 409]
    assert len(review_auth.read_users()) == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"username": "bad name", "password": "long enough pw"},
        {"username": "ok", "password": "short"},
        {"username": 5, "password": None},
    ],
)
def test_setup_validates_its_input(env, body):
    status, payload = rs.route("POST", "/api/setup", body, None)
    assert status == 400 and payload["error"]
    assert not (env / "config" / "users.json").exists()


def test_env_credentials_are_imported_once_as_the_first_admin(env, capsys):
    pair = {"REVIEW_USERNAME": "reviewer", "REVIEW_PASSWORD": "correct horse"}
    assert review_auth.import_env_admin(pair) is True
    (row,) = review_auth.read_users()
    assert (row["name"], row["role"]) == ("reviewer", "admin") and review_auth.verify_password("correct horse", row["hash"])
    assert review_auth.import_env_admin(pair) is False and len(review_auth.read_users()) == 1
    assert "correct horse" not in capsys.readouterr().out


def test_a_password_file_wins_and_loses_one_trailing_newline(env):
    f = env / "pw"
    f.write_bytes(b"from a file\r\n")
    assert review_auth.import_env_admin(
        {"REVIEW_USERNAME": "reviewer", "REVIEW_PASSWORD_FILE": str(f), "REVIEW_PASSWORD": "ignored pw!"}
    )
    assert review_auth.verify_password("from a file", review_auth.read_users()[0]["hash"])


def test_an_unreadable_password_file_imports_nothing_and_leaves_setup_open(env, capsys):
    assert review_auth.import_env_admin({"REVIEW_USERNAME": "reviewer", "REVIEW_PASSWORD_FILE": str(env / "nope")}) is False
    assert review_auth.setup_required() is True
    assert "REVIEW_PASSWORD_FILE unreadable" in capsys.readouterr().out


@pytest.mark.parametrize(
    "pair",
    [
        {"REVIEW_USERNAME": "reviewer"},
        {"REVIEW_PASSWORD": "correct horse"},
        {"REVIEW_USERNAME": "bad name", "REVIEW_PASSWORD": "correct horse"},
        {"REVIEW_USERNAME": "reviewer", "REVIEW_PASSWORD": "short"},
        {"REVIEW_USERNAME": "", "REVIEW_PASSWORD": ""},
    ],
)
def test_half_set_invalid_or_short_credentials_are_not_imported(env, pair):
    assert review_auth.import_env_admin(pair) is False and review_auth.setup_required() is True


def test_nothing_set_imports_nothing_and_logs_nothing(env, capsys):
    assert review_auth.import_env_admin({}) is False and capsys.readouterr().out == ""


def test_startup_imports_the_env_admin_and_seeds_the_key_from_the_review_token(env, monkeypatch):
    monkeypatch.setenv("REVIEW_USERNAME", "reviewer")
    monkeypatch.setenv("REVIEW_PASSWORD", "correct horse")
    monkeypatch.setattr(review_auth, "_DUMMY", None)
    rs.startup_auth()
    assert review_auth._DUMMY is not None, "the dummy hash is built at start, not by the first unknown-user login"
    assert review_auth.setup_required() is False
    assert (env / "config" / "apikey").read_text() == KEY + "\n"


def test_startup_refuses_to_run_with_auth_on_and_no_scrypt(env, monkeypatch, capsys):
    monkeypatch.delattr(review_auth.hashlib, "scrypt")
    with pytest.raises(SystemExit) as e:
        rs.startup_auth()
    assert e.value.code == 2 and "scrypt" in capsys.readouterr().out


def test_startup_does_nothing_when_auth_is_off(env, monkeypatch):
    monkeypatch.setenv("REVIEW_AUTH", "off")
    monkeypatch.setenv("REVIEW_USERNAME", "reviewer")
    monkeypatch.setenv("REVIEW_PASSWORD", "correct horse")
    rs.startup_auth()
    assert review_auth.setup_required() is True and not (env / "config" / "apikey").exists()


def test_open_routes_are_the_four_pinned_entries():
    assert set(rs.OPEN_ROUTES) == {("GET", "/healthz"), ("GET", "/api/auth-mode"), ("POST", "/api/login"), ("POST", "/api/setup")}


def test_setup_accepts_only_small_json_over_http(env):
    srv = rs.BoundedHTTPServer(("127.0.0.1", 0), rs.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:

        def post(body, ctype):
            conn = http.client.HTTPConnection(*srv.server_address, timeout=5)
            conn.request("POST", "/api/setup", body=body, headers={"Content-Type": ctype})
            r = conn.getresponse()
            r.read()
            conn.close()
            return r.status

        assert post(json.dumps(FIRST), "text/plain") == 415
        assert post(json.dumps({"username": "a", "password": "x" * 6000}), "application/json") == 413
        assert post(json.dumps(FIRST), "application/json") == 200
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
