import http.client
import json
import threading
import types

import pytest

import review_auth
import review_server as rs

pytestmark = pytest.mark.real_accounts
KEY = "accounts-key"
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
    review_auth.create_user("root", "admin", "admin password")
    review_auth.create_user("alice", "user", "alice password")
    return types.SimpleNamespace(clock=clock, tmp=tmp_path)


def sess(name):
    return {"Cookie": f"dubtitlerr_session={review_auth.sessions().create(name, False)}", **CSRF}


def call(method, path, body=None, headers=None, client="10.0.0.5"):
    return rs.route(method, path, {} if body is None else body, None, client=client, headers=headers)


def alive(headers):
    return call("GET", "/api/me", headers={"Cookie": headers["Cookie"]})[0] == 200


def test_the_account_list_shows_names_and_roles_and_never_a_hash(env):
    status, payload = call("GET", "/api/users", headers=sess("root"))
    assert status == 200 and payload == {"users": [{"name": "root", "role": "admin"}, {"name": "alice", "role": "user"}]}
    assert "scrypt" not in json.dumps(payload)


def test_an_admin_adds_a_user_and_a_duplicate_in_any_case_is_409(env):
    admin = sess("root")
    body = {"username": "Carol", "password": "carols password", "role": "user"}
    assert call("POST", "/api/users", body, admin) == (201, {"name": "Carol", "role": "user"})
    assert call("POST", "/api/users", {**body, "username": "CAROL"}, admin) == (409, {"error": "username taken"})
    assert call("POST", "/api/users", {**body, "username": "dave", "role": "root"}, admin)[0] == 400
    assert call("POST", "/api/users", {**body, "username": "dave", "password": "short"}, admin)[0] == 400


def test_a_user_gets_403_on_every_account_route(env):
    alice = sess("alice")
    for method, path in [
        ("GET", "/api/users"),
        ("POST", "/api/users"),
        ("PUT", "/api/users/root"),
        ("DELETE", "/api/users/root"),
    ]:
        assert call(method, path, {}, alice)[0] == 403, (method, path)


def test_changing_a_role_ends_that_accounts_sessions(env):
    alice = sess("alice")
    assert call("PUT", "/api/users/alice", {"role": "admin"}, sess("root")) == (200, {"name": "alice", "role": "admin"})
    assert not alive(alice)


def test_an_admin_resets_a_password_the_old_one_stops_and_the_sessions_end(env):
    alice = sess("alice")
    env.clock.now += 10
    assert call("PUT", "/api/users/alice", {"password": "brand new pass"}, sess("root"))[0] == 200
    assert not alive(alice)
    assert rs.route("POST", "/api/login", {"username": "alice", "password": "brand new pass"}, None)[0] == 200
    assert rs.route("POST", "/api/login", {"username": "alice", "password": "alice password"}, None)[0] == 401


def test_the_last_admin_cannot_be_deleted_or_demoted(env):
    admin = sess("root")
    before = (env.tmp / "config" / "users.json").read_bytes()
    refusal = (409, {"error": "cannot remove or demote the last admin"})
    assert call("PUT", "/api/users/root", {"role": "user"}, admin) == refusal
    assert call("DELETE", "/api/users/root", headers=admin) == refusal
    assert (env.tmp / "config" / "users.json").read_bytes() == before


def test_an_admin_may_demote_or_delete_themself_while_another_admin_exists(env):
    call("PUT", "/api/users/alice", {"role": "admin"}, sess("root"))
    root = sess("root")
    assert call("PUT", "/api/users/root", {"role": "user"}, root)[0] == 200
    assert not alive(root)


def test_deleting_an_account_ends_its_sessions_at_once(env):
    alice = sess("alice")
    assert call("DELETE", "/api/users/alice", headers=sess("root")) == (200, {"ok": True})
    assert not alive(alice)
    assert call("PUT", "/api/users/alice", {"role": "user"}, sess("root")) == (404, {"error": "no such user"})


def test_a_bad_name_in_the_path_is_400_and_a_wrong_method_is_404(env):
    admin = sess("root")
    assert call("PUT", "/api/users/bad%20name", {"role": "user"}, admin)[0] == 400
    assert call("PUT", "/api/users/alice", {}, admin) == (400, {"error": "nothing to change"})
    assert call("GET", "/api/users/alice", headers=admin)[0] == 404


def test_changing_your_own_password_needs_the_current_one(env):
    alice = sess("alice")
    assert call("PUT", "/api/me/password", {"current": "wrong wrong", "new": "a fresh password"}, alice) == (
        403,
        {"error": "current password is wrong"},
    )
    assert call("PUT", "/api/me/password", {"current": "alice password", "new": "short"}, alice)[0] == 400


def test_a_password_change_rotates_this_session_and_ends_every_other(env):
    here, elsewhere = sess("alice"), sess("alice")
    env.clock.now += 10
    body = {"current": "alice password", "new": "a fresh password"}
    status, payload, extra = rs.route_full("PUT", "/api/me/password", body, None, headers=here)
    assert (status, payload) == (200, {"ok": True})
    fresh = {"Cookie": extra["Set-Cookie"].split(";", 1)[0]}
    assert fresh["Cookie"] != here["Cookie"], "a new session id, so a stolen copy of the old one is worthless"
    assert alive(fresh) and not alive(here) and not alive(elsewhere)
    restarted = review_auth.SessionStore(review_auth.sessions().path)
    assert restarted.lookup(fresh["Cookie"].split("=", 1)[1]) is not None
    assert restarted.lookup(here["Cookie"].split("=", 1)[1]) is None, "the rotation is on disk, not only in memory"
    row = review_auth.find_user(review_auth.read_users(), "alice")
    assert row["session_epoch"] == 1 and float(row["pw_changed_at"]) == env.clock.now
    assert rs.route("POST", "/api/login", {"username": "alice", "password": "a fresh password"}, None)[0] == 200


def test_an_invalid_role_is_refused_and_leaves_the_file_readable(env):
    before = (env.tmp / "config" / "users.json").read_bytes()
    assert call("PUT", "/api/users/alice", {"role": "editor"}, sess("root")) == (400, {"error": "role must be admin or user"})
    assert (env.tmp / "config" / "users.json").read_bytes() == before
    assert [u["name"] for u in review_auth.read_users()] == ["root", "alice"]


def test_other_methods_on_the_collection_are_405(env):
    admin = sess("root")
    for method in ("PUT", "DELETE", "PATCH"):
        assert call(method, "/api/users", {}, admin) == (405, {"error": "method not allowed"}), method


def test_ten_wrong_current_passwords_end_in_429(env):
    alice = sess("alice")
    statuses = [
        call("PUT", "/api/me/password", {"current": "nope nope nope", "new": "a fresh password"}, alice)[0] for _ in range(10)
    ]
    assert statuses[:5] == [403] * 5 and statuses[-1] == 429
    assert call("PUT", "/api/me/password", {"current": "alice password", "new": "a fresh password"}, alice)[0] == 429


def test_the_api_key_has_no_password_to_change(env):
    assert call("PUT", "/api/me/password", {"current": "x", "new": "a fresh password"}, {"X-Api-Key": KEY})[0] == 403


def test_the_http_layer_serves_delete_without_a_body_and_rejects_garbage_json(env):
    srv = rs.BoundedHTTPServer(("127.0.0.1", 0), rs.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:

        def send(method, path, raw=None):
            conn = http.client.HTTPConnection(*srv.server_address, timeout=5)
            conn.request(method, path, body=raw, headers={"X-Api-Key": KEY, "Content-Type": "application/json"})
            r = conn.getresponse()
            out = (r.status, json.loads(r.read() or b"{}"))
            conn.close()
            return out

        assert send("POST", "/api/users", b"{not json") == (400, {"error": "invalid JSON"})
        assert send("DELETE", "/api/users/alice") == (200, {"ok": True})
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_a_path_name_in_another_case_edits_the_stored_account(env):
    review_auth.create_user("ann", "user", "anns password")
    assert call("PUT", "/api/users/ANN", {"role": "admin"}, sess("root")) == (200, {"name": "ann", "role": "admin"})
    assert [u["name"] for u in review_auth.read_users()].count("ann") == 1


def test_a_delete_without_the_csrf_header_is_refused_and_deletes_nothing(env):
    no_header = {"Cookie": sess("root")["Cookie"]}
    assert call("DELETE", "/api/users/alice", headers=no_header) == (403, {"error": "cross-site request refused"})
    assert review_auth.find_user(review_auth.read_users(), "alice") is not None


def test_every_account_change_leaves_one_audit_line_with_name_role_and_actor_never_a_password(env, capsys):
    admin = sess("root")
    call("PUT", "/api/users/alice", {"role": "admin"}, admin)
    call("PUT", "/api/users/alice", {"password": "very secret new pw"}, admin)
    call("DELETE", "/api/users/alice", headers=admin)
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if "account " in ln]
    assert any("account role changed: alice user -> admin (by root)" in ln for ln in lines)
    assert any("account password reset: alice role=admin (by root)" in ln for ln in lines)
    assert any("account deleted: alice role=admin (by root)" in ln for ln in lines)
    assert "very secret new pw" not in out and "scrypt$" not in out


def test_a_failed_change_leaves_no_audit_line(env, capsys):
    call("DELETE", "/api/users/root", headers=sess("root"))
    call("PUT", "/api/users/ghost", {"role": "user"}, sess("root"))
    assert not [ln for ln in capsys.readouterr().out.splitlines() if "account deleted" in ln or "account role changed" in ln]


def test_password_change_failures_are_counted_per_account_not_per_address(env):
    here = sess("alice")
    bad = {"current": "nope nope nope", "new": "a fresh password"}
    for i in range(5):
        assert call("PUT", "/api/me/password", bad, here, client=f"10.0.2.{i}")[0] == 403
    assert call("PUT", "/api/me/password", bad, here, client="10.0.2.99")[0] == 429, "the account is locked from every address"
    assert (
        rs.route("POST", "/api/login", {"username": "root", "password": "admin password"}, None, client="10.0.2.0")[0] == 200
    ), "the password-change failures did not count against the address"


def test_a_password_change_success_clears_only_that_accounts_counter(env):
    review_auth.create_user("bob", "user", "bobs password")
    alice, bob = sess("alice"), sess("bob")
    bad = {"current": "nope nope nope", "new": "a fresh password"}
    for _ in range(4):
        call("PUT", "/api/me/password", bad, alice)
        call("PUT", "/api/me/password", bad, bob)
    good = {"current": "alice password", "new": "a fresh password"}
    assert call("PUT", "/api/me/password", good, alice)[0] == 200
    assert call("PUT", "/api/me/password", bad, bob)[0] == 403
    assert call("PUT", "/api/me/password", bad, bob)[0] == 429, "bob's own fifth failure still locks bob"


@pytest.mark.parametrize(
    "method,path", [("GET", "/api/users"), ("POST", "/api/users"), ("PUT", "/api/users/alice"), ("DELETE", "/api/users/alice")]
)
def test_account_routes_are_refused_with_409_while_auth_is_off(env, monkeypatch, method, path):
    monkeypatch.setenv("REVIEW_AUTH", "off")
    before = (env.tmp / "config" / "users.json").read_bytes()
    body = {"username": "mallory", "password": "mallory password", "role": "admin", "password_x": 1}
    assert call(method, path, body, CSRF) == (409, {"error": "accounts cannot be managed while REVIEW_AUTH=off"})
    assert (env.tmp / "config" / "users.json").read_bytes() == before


def test_update_user_validates_the_password_once(env, monkeypatch):
    seen = []
    real = review_auth.validate_password
    monkeypatch.setattr(review_auth, "validate_password", lambda p: seen.append(p) or real(p))
    with pytest.raises(review_auth.Invalid):
        review_auth.update_user("alice", password="short")
    assert seen == ["short"]
