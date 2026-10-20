import json

import pytest

import glossary_lock
import review_auth
import review_server as rs

pytestmark = pytest.mark.real_accounts
OLD = "token-from-0-2-x"
CSRF = {"X-DubTitlerr-Request": "1"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("REVIEW_TOKEN", OLD)
    for name in ("REVIEW_AUTH", "REVIEW_USERNAME", "REVIEW_PASSWORD", "REVIEW_PASSWORD_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(review_auth, "SCRYPT_N", 2**4)
    monkeypatch.setattr(rs, "ROOTS", [str(tmp_path / "media")])
    monkeypatch.setattr(rs, "_STEMS_CACHE", None)
    monkeypatch.setattr(rs, "_QUEUE_CACHE", {})
    return tmp_path


def session(name):
    return {"Cookie": f"dubtitlerr_session={review_auth.sessions().create(name, False)}", **CSRF}


def test_after_an_upgrade_the_old_token_is_the_api_key_and_browsers_go_to_setup(env):
    rs.startup_auth()
    assert (env / "config" / "apikey").read_text() == OLD + "\n"
    assert rs.route("GET", "/api/episodes", {}, None, headers={"X-Api-Key": OLD})[0] == 200
    assert rs.route("GET", "/api/episodes", {}, None) == (409, {"error": "setup required"})


def test_reset_gives_a_new_key_and_the_old_one_gets_401(env):
    rs.startup_auth()
    review_auth.create_user("root", "admin", "admin password")
    admin = session("root")
    status, payload = rs.route("GET", "/api/apikey", {}, None, headers=admin)
    assert (status, payload) == (200, {"key": OLD})
    status, payload = rs.route("POST", "/api/apikey/reset", {}, None, headers=admin)
    new = payload["key"]
    assert status == 200 and new != OLD and len(new) >= 43
    assert rs.route("GET", "/api/episodes", {}, None, headers={"X-Api-Key": OLD})[0] == 401
    assert rs.route("GET", "/api/episodes", {}, OLD)[0] == 401, "the old token as the legacy alias stops too"
    assert rs.route("GET", "/api/episodes", {}, None, headers={"X-Api-Key": new})[0] == 200


def test_a_user_cannot_read_or_reset_the_key(env):
    rs.startup_auth()
    review_auth.create_user("alice", "user", "user password!")
    alice = session("alice")
    assert rs.route("GET", "/api/apikey", {}, None, headers=alice)[:2] == (403, {"error": "admin only"})
    assert rs.route("POST", "/api/apikey/reset", {}, None, headers=alice)[0] == 403
    assert review_auth.api_key() == OLD


def test_the_key_appears_nowhere_but_the_admin_key_route(env, capsys):
    rs.startup_auth()
    review_auth.create_user("root", "admin", "admin password")
    admin = session("root")
    _, settings = rs.route("GET", "/api/settings", {}, None, headers=admin)
    _, me = rs.route("GET", "/api/me", {}, None, headers=admin)
    _, mode = rs.route("GET", "/api/auth-mode", {}, None)
    assert OLD not in json.dumps([settings, me, mode], default=str)
    assert OLD not in capsys.readouterr().out
    assert OLD not in json.dumps(review_auth.read_users())


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/apikey"),
        ("PUT", "/api/apikey"),
        ("DELETE", "/api/apikey"),
        ("GET", "/api/apikey/reset"),
        ("PUT", "/api/apikey/reset"),
    ],
)
def test_the_key_routes_answer_405_to_the_wrong_method(env, method, path):
    rs.startup_auth()
    review_auth.create_user("root", "admin", "admin password")
    assert rs.route(method, path, {}, None, headers=session("root"))[0] == 405
    assert review_auth.api_key() == OLD, "a wrong-method request neither shows nor resets the key"


def test_a_busy_key_lock_makes_reset_a_503_and_keeps_the_key(env, monkeypatch):
    rs.startup_auth()
    review_auth.create_user("root", "admin", "admin password")
    monkeypatch.setattr(review_auth, "LOCK_WAIT", 0.05)
    with glossary_lock.locked(review_auth.apikey_path(), "holder", wait=0):
        status, payload = rs.route("POST", "/api/apikey/reset", {}, None, headers=session("root"))
    assert (status, payload) == (503, {"error": "busy, try again"})
    assert review_auth.api_key() == OLD
