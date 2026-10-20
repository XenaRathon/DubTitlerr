import json
import types

import pytest

import review_auth

pytestmark = pytest.mark.real_accounts
KEY = "the-api-key"


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    monkeypatch.setattr(review_auth, "SCRYPT_N", 2**4)
    monkeypatch.setattr(review_auth, "_TOKEN_FALLBACK", lambda: KEY)
    clock = Clock()
    monkeypatch.setattr(review_auth, "CLOCK", clock)
    return types.SimpleNamespace(dir=tmp_path, clock=clock)


@pytest.fixture
def people(env):
    review_auth.create_user("root", "admin", "admin password")
    review_auth.create_user("alice", "user", "user password!")
    return {
        n: {"Cookie": f"dubtitlerr_session={review_auth.sessions().create(n, False)}", "X-DubTitlerr-Request": "1"}
        for n in ("root", "alice")
    }


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/healthz"),
        ("GET", "/api/auth-mode"),
        ("POST", "/api/login"),
        ("POST", "/api/setup"),
        ("GET", "/review"),
        ("GET", "/review/assets/app.js"),
        ("GET", "/review/login"),
        ("POST", "/api/webhook/sonarr"),
        ("POST", "/api/webhook/radarr"),
    ],
)
def test_public_routes_need_nothing(people, method, path):
    assert review_auth.role_for(method, path, {}) == ("public", None)


def test_no_credentials_is_401_once_accounts_exist(people):
    assert review_auth.role_for("GET", "/api/episodes", {}) == (None, 401)
    assert review_auth.role_for("PUT", "/api/settings", {}) == (None, 401)


def test_before_setup_everything_but_public_routes_and_the_key_answers_409(env):
    assert review_auth.role_for("GET", "/api/episodes", {}) == (None, 409)
    assert review_auth.role_for("GET", "/api/episodes", {"Cookie": "dubtitlerr_session=stale"}) == (None, 409)
    assert review_auth.role_for("GET", "/api/episodes", {"X-Api-Key": KEY}) == ("admin", None)
    assert review_auth.role_for("GET", "/api/episodes", {"X-Api-Key": "wrong"}) == (None, 401)
    assert review_auth.role_for("GET", "/healthz", {}) == ("public", None)


def test_a_user_reaches_user_routes_and_is_refused_admin_routes(people):
    user = people["alice"]
    assert review_auth.role_for("GET", "/api/episodes", user) == ("user", None)
    assert review_auth.role_for("POST", "/api/decide", user) == ("user", None)
    assert review_auth.role_for("POST", "/api/glossary", user) == ("user", None)
    for method, path in [
        ("PUT", "/api/settings"),
        ("POST", "/api/settings/reset"),
        ("POST", "/api/settings/test"),
        ("POST", "/api/system/restart"),
        ("POST", "/api/requests"),
        ("PUT", "/api/schedule"),
        ("GET", "/api/users"),
        ("GET", "/api/apikey"),
        ("POST", "/api/apikey/reset"),
    ]:
        assert review_auth.role_for(method, path, user) == (None, 403), (method, path)
    assert review_auth.role_for("GET", "/api/settings", user) == ("user", None)
    assert review_auth.role_for("GET", "/api/settings/schema", user) == ("user", None)


def test_an_admin_reaches_everything(people):
    admin = people["root"]
    for method, path in [
        ("PUT", "/api/settings"),
        ("POST", "/api/system/restart"),
        ("GET", "/api/users"),
        ("DELETE", "/api/users/alice"),
        ("PUT", "/api/users/alice"),
        ("GET", "/api/episodes"),
    ]:
        assert review_auth.role_for(method, path, admin) == ("admin", None), (method, path)


def test_an_unlisted_route_fails_closed(people):
    assert review_auth.role_for("GET", "/api/nope", people["alice"]) == (None, 403)
    assert review_auth.role_for("GET", "/api/nope", {}) == (None, 401)
    assert review_auth.role_for("GET", "/api/users/alice", people["alice"]) == (None, 403), "GET on the wildcard is unlisted"
    assert review_auth.role_for("GET", "/api/nope", people["root"]) == ("admin", None), "the 404 comes from the router"


def test_the_api_key_decides_when_a_cookie_is_also_present(people):
    assert review_auth.role_for("GET", "/api/episodes", {**people["root"], "X-Api-Key": "wrong"}) == (None, 401)
    assert review_auth.role_for("PUT", "/api/settings", {**people["alice"], "X-Api-Key": KEY}) == ("admin", None)


def test_header_names_are_case_insensitive(people):
    assert review_auth.role_for("GET", "/api/episodes", {"x-api-key": KEY}) == ("admin", None)
    cookie = people["alice"]["Cookie"]
    assert review_auth.role_for("GET", "/api/episodes", {"cookie": cookie}) == ("user", None)


def test_the_legacy_token_cookie_opens_the_classic_pages_only(people):
    legacy = {"Cookie": f"dubtitlerr_token={KEY}"}
    assert review_auth.role_for("GET", "/", legacy) == ("admin", None)
    assert review_auth.role_for("GET", "/shared", legacy) == ("admin", None)
    assert review_auth.role_for("GET", "/api/episodes", legacy) == (None, 401)
    assert review_auth.role_for("POST", "/api/decide", legacy) == (None, 401)


def test_a_valid_session_beats_a_legacy_cookie_and_a_stale_token(people):
    alice = people["alice"]
    with_cookie = {"Cookie": alice["Cookie"] + f"; dubtitlerr_token={KEY}"}
    assert review_auth.role_for("GET", "/api/apikey", alice) == (None, 403)
    assert review_auth.role_for("GET", "/api/apikey", with_cookie) == (None, 403), (
        "the legacy cookie does not raise a user to admin"
    )
    assert review_auth.role_for("GET", "/api/me", with_cookie) == ("user", None)
    stale = {**alice, "X-Review-Token": "token-from-before-a-reset"}
    assert review_auth.role_for("GET", "/api/episodes", stale) == ("user", None), (
        "a stale token does not lock a signed-in browser out"
    )


def test_review_auth_off_opens_every_route(env, monkeypatch):
    monkeypatch.setenv("REVIEW_AUTH", "off")
    assert review_auth.role_for("PUT", "/api/settings", {"X-DubTitlerr-Request": "1"}) == ("admin", None)
    assert review_auth.role_for("GET", "/api/nope", {}) == ("admin", None)


def test_a_deleted_account_or_a_bumped_session_epoch_ends_its_sessions(env, people):
    review_auth.create_user("bob", "user", "bobs password")
    bob = {"Cookie": f"dubtitlerr_session={review_auth.sessions().create('bob', False)}"}
    assert review_auth.role_for("GET", "/api/episodes", bob) == ("user", None)
    path = env.dir / "users.json"
    doc = json.loads(path.read_text())
    doc["users"][-1]["session_epoch"] = 1  # a password or role changed by another process (the recovery CLI), after the login
    path.write_text(json.dumps(doc))
    assert review_auth.role_for("GET", "/api/episodes", bob) == (None, 401)
    doc["users"] = [u for u in doc["users"] if u["name"] != "bob"]
    path.write_text(json.dumps(doc))
    assert review_auth.role_for("GET", "/api/episodes", bob) == (None, 401)


def test_an_unreadable_accounts_file_refuses_cookies_but_keeps_the_key(env, people):
    (env.dir / "users.json").write_text("{not json")
    assert review_auth.role_for("GET", "/api/episodes", people["root"]) == (None, 401)
    assert review_auth.role_for("GET", "/api/episodes", {"X-Api-Key": KEY}) == ("admin", None)


def test_register_routes_adds_and_is_idempotent_and_all_or_nothing(env):
    review_auth.register_routes({("GET", "/api/_t5_probe"): "user", ("POST", "/api/_t5_probe/*"): "admin"})
    review_auth.register_routes({("GET", "/api/_t5_probe"): "user"})
    assert review_auth.ROUTE_ROLES[("GET", "/api/_t5_probe")] == "user"
    with pytest.raises(ValueError):
        review_auth.register_routes({("GET", "/api/_t5_new"): "user", ("GET", "/api/_t5_probe"): "admin"})
    assert ("GET", "/api/_t5_new") not in review_auth.ROUTE_ROLES
    with pytest.raises(ValueError):
        review_auth.register_routes({("GET", "/api/_t5_bad"): "superuser"})
    for key in [("GET", "/api/_t5_probe"), ("POST", "/api/_t5_probe/*")]:
        review_auth.ROUTE_ROLES.pop(key, None)


def test_the_settings_routes_of_webui_full_settings_have_their_roles():
    expect = {
        ("PUT", "/api/settings"): "admin",
        ("POST", "/api/settings/reset"): "admin",
        ("POST", "/api/settings/test"): "admin",
        ("POST", "/api/system/restart"): "admin",
        ("GET", "/api/settings"): "user",
        ("GET", "/api/settings/schema"): "user",
    }
    assert {k: review_auth.ROUTE_ROLES[k] for k in expect} == expect
    assert set(review_auth.ROUTE_ROLES.values()) <= {"public", "user", "admin"}


@pytest.mark.parametrize(
    "prefix",
    ['theme={"a":1}; ', "x=a b; ", 'other="a\\"b; ', "junk; ", "=; ", "a=b;c=d; "],
)
def test_a_foreign_cookie_before_ours_does_not_drop_the_session(people, prefix):
    cookie = people["alice"]["Cookie"]
    assert review_auth.role_for("GET", "/api/episodes", {"Cookie": prefix + cookie}) == ("user", None)
    assert review_auth.role_for("GET", "/api/episodes", {"Cookie": cookie + "; " + prefix}) == ("user", None)


def test_the_first_cookie_of_a_name_wins_and_names_match_exactly(people):
    cookie = people["alice"]["Cookie"]
    sid = cookie.split("=", 1)[1]
    assert review_auth.role_for("GET", "/api/episodes", {"Cookie": f"x_dubtitlerr_session=nope; {cookie}"}) == ("user", None)
    assert review_auth.role_for("GET", "/api/episodes", {"Cookie": f"dubtitlerr_session=forged; dubtitlerr_session={sid}"}) == (
        None,
        401,
    )
    assert review_auth.role_for("GET", "/api/episodes", {"Cookie": f'dubtitlerr_session="{sid}"'}) == ("user", None)


def test_a_query_string_or_fragment_does_not_change_the_route(people):
    user = people["alice"]
    assert review_auth.role_for("GET", "/api/episode?stem=x", user) == ("user", None)
    assert review_auth.role_for("GET", "/api/episodes?show=a&x=/api/users", user) == ("user", None)
    assert review_auth.role_for("GET", "/api/users?x=1", user) == (None, 403)
    assert review_auth.role_for("GET", "/api/users#frag", user) == (None, 403)
    assert review_auth.role_for("GET", "/healthz?probe=1", {}) == ("public", None)


def test_a_hand_edited_non_integer_session_epoch_is_a_401_not_a_crash(env, people):
    path = env.dir / "users.json"
    doc = json.loads(path.read_text())
    doc["users"][1]["session_epoch"] = "zero"
    path.write_text(json.dumps(doc))
    assert review_auth.role_for("GET", "/api/episodes", people["alice"]) == (None, 401)


@pytest.mark.parametrize(
    "method,path",
    [("GET", "/healthz"), ("GET", "/review"), ("GET", "/review/assets/app.js"), ("POST", "/api/webhook/sonarr")],
)
def test_public_routes_that_ignore_the_principal_do_no_lookup(people, monkeypatch, method, path):
    def no_lookup(*a, **k):
        raise AssertionError("authenticate ran on a public route")

    monkeypatch.setattr(review_auth, "authenticate", no_lookup)
    assert review_auth.role_for(method, path, people["alice"]) == ("public", None)


@pytest.mark.parametrize("path", ["/healthz", "/api/auth-mode", "/review/assets/app.js", "/api/login"])
def test_a_wrong_api_key_on_a_public_route_does_not_block_it(people, path):
    method = "POST" if path == "/api/login" else "GET"
    assert review_auth.role_for(method, path, {"X-Api-Key": "wrong"}) == ("public", None)
