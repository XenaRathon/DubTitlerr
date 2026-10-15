import ast
import http.client
import json
import pathlib
import threading

import pytest

import review_auth
import review_server as rs
import review_webhooks

pytestmark = pytest.mark.real_accounts
KEY = "dispatch-key"
CSRF = {"X-DubTitlerr-Request": "1"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("REVIEW_TOKEN", KEY)
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    monkeypatch.delenv("REVIEW_ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(review_auth, "SCRYPT_N", 2**4)
    monkeypatch.setattr(rs, "ROOTS", [str(tmp_path / "media")])
    monkeypatch.setattr(rs, "_STEMS_CACHE", None)
    monkeypatch.setattr(rs, "_QUEUE_CACHE", {})
    review_auth.create_user("root", "admin", "admin password")
    review_auth.create_user("alice", "user", "user password!")
    return tmp_path


def session(name):
    return {"Cookie": f"dubtitlerr_session={review_auth.sessions().create(name, False)}", **CSRF}


def _dispatcher_paths():
    tree = ast.parse(pathlib.Path(rs.__file__).read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_route")
    return {
        n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("/api/")
    }


def _listed(path):
    return any(p == path or (p.endswith("/*") and path.startswith(p[:-1])) for _m, p in review_auth.ROUTE_ROLES)


def test_the_enumeration_really_sees_the_dispatcher():
    assert {"/api/episodes", "/api/decide", "/api/glossary", "/api/status"} <= _dispatcher_paths()


def test_every_api_path_the_dispatcher_names_is_in_the_role_table():
    assert sorted(p for p in _dispatcher_paths() if not _listed(p)) == []


def _handler_method(name):
    tree = ast.parse(pathlib.Path(rs.__file__).read_text())
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "Handler")
    return cls, next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name), None)


def test_every_path_do_get_serves_itself_is_in_the_role_table():
    _cls, fn = _handler_method("do_GET")
    paths = {
        n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("/")
    }
    assert {"/", "/shared", "/healthz"} <= paths
    assert sorted(p for p in paths if ("GET", p) not in review_auth.ROUTE_ROLES and not _listed(p)) == []


def test_no_do_method_can_bypass_the_dispatcher_unnoticed():
    cls, _ = _handler_method("do_GET")
    names = sorted(n.name for n in cls.body if isinstance(n, ast.FunctionDef) and n.name.startswith("do_"))
    assert names == ["do_DELETE", "do_GET", "do_POST", "do_PUT"], "a new do_* method must go through route_full and be added here"


def test_every_admin_handler_and_webhook_is_in_the_role_table():
    for key in rs.ADMIN_ROUTES:
        assert key in review_auth.ROUTE_ROLES, key
    for path in review_webhooks.WEBHOOK_ROUTES:
        assert review_auth.ROUTE_ROLES[("POST", path)] == "public"


@pytest.mark.parametrize(
    "method,path",
    [
        ("PUT", "/api/settings"),
        ("POST", "/api/requests"),
        ("PUT", "/api/schedule"),
        ("POST", "/api/system/restart"),
        ("POST", "/api/settings/reset"),
        ("POST", "/api/settings/test"),
    ],
)
def test_a_user_gets_403_on_every_admin_route(env, method, path):
    assert rs.route_full(method, path, {}, None, headers=session("alice"))[:2] == (403, {"error": "admin only"})


def test_a_user_is_refused_before_the_body_is_judged(env):
    assert rs.route_full("PUT", "/api/schedule", None, None, headers=session("alice"))[0] == 403


def test_a_user_can_give_verdicts_edit_glossaries_and_read(env, monkeypatch):
    monkeypatch.setattr(rs.review_glossary, "handle", lambda method, path, body, operator="x": (200, {"ok": True}))
    user = session("alice")
    assert rs.route_full("POST", "/api/decide", {"stem": "nope", "index": 0, "verdict": "reject"}, None, headers=user)[0] == 200
    assert rs.route_full("POST", "/api/glossary", {"show": "s"}, None, headers=user)[:2] == (200, {"ok": True})
    assert rs.route_full("GET", "/api/episodes", {}, None, headers=user)[0] == 200


def test_an_admin_session_reaches_an_admin_route(env):
    assert rs.route_full("PUT", "/api/settings", {}, None, headers=session("root"))[0] not in (401, 403)


def test_a_missing_credential_is_401_login_required(env):
    assert rs.route_full("GET", "/api/episodes", {}, None) == (401, {"error": "login required"}, {})


def test_the_api_key_needs_no_admin_token(env, monkeypatch):
    seen = []
    monkeypatch.setitem(rs.ADMIN_ROUTES, ("POST", "/api/_t6_probe"), lambda body: seen.append(body) or (200, {"ok": True}))
    assert rs.route_full("POST", "/api/_t6_probe", {"x": 1}, None, headers={"X-Api-Key": KEY})[:2] == (200, {"ok": True})
    assert seen == [{"x": 1}]


def test_the_alias_reaches_an_admin_route_with_no_second_secret(env, monkeypatch):
    monkeypatch.setitem(rs.ADMIN_ROUTES, ("POST", "/api/_t6_probe"), lambda body: (200, {"ok": True}))
    assert rs.route("POST", "/api/_t6_probe", {}, KEY) == (200, {"ok": True})


def test_route_keeps_its_two_tuple_shape(env):
    assert len(rs.route("GET", "/api/episodes", {}, KEY)) == 2
    assert len(rs.route_full("GET", "/api/episodes", {}, KEY)) == 3


@pytest.fixture
def server(env):
    srv = rs.BoundedHTTPServer(("127.0.0.1", 0), rs.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def get(srv, path, headers=None):
    conn = http.client.HTTPConnection(*srv.server_address, timeout=5)
    conn.request("GET", path, headers=headers or {})
    r = conn.getresponse()
    out = (r.status, json.loads(r.read() or b"{}"))
    conn.close()
    return out


def test_the_http_layer_hands_get_headers_to_the_dispatcher(server):
    assert get(server, "/api/episodes") == (401, {"error": "login required"})
    assert get(server, "/api/episodes", {"X-Api-Key": KEY})[0] == 200
    assert get(server, "/api/episodes", session("alice"))[0] == 200
