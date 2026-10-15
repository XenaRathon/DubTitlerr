"""Unparseable JSON on the NEW write routes is a 400, not a silent empty body. The old inbox routes keep their lenient
behaviour. Auth still comes first: a caller without a token learns nothing about the body."""

import http.client
import json
import threading

import pytest

import review_server as rs

TOKEN = "review-token"
ADMIN = "admin-token"
NEW_ROUTES = [
    ("POST", "/api/requests", True),
    ("PUT", "/api/schedule", True),
    ("POST", "/api/settings/test", False),
    ("POST", "/api/glossary", False),
]


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEW_TOKEN", TOKEN)
    monkeypatch.setenv("REVIEW_ADMIN_TOKEN", ADMIN)
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    monkeypatch.setenv("GLOSSARY_DIR", str(tmp_path))
    # The inbox route in the last test walks ROOTS and fills the stem cache: keep that off the real roots and restore it.
    monkeypatch.setattr(rs, "ROOTS", [str(tmp_path / "media")])
    monkeypatch.setattr(rs, "_STEMS_CACHE", None)
    monkeypatch.setattr(rs, "_QUEUE_CACHE", {})
    srv = rs.BoundedHTTPServer(("127.0.0.1", 0), rs.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def send(srv, method, path, raw, headers=None):
    conn = http.client.HTTPConnection(*srv.server_address, timeout=5)
    conn.request(method, path, body=raw, headers={"Content-Type": "application/json", **(headers or {})})
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, (json.loads(body) if body else {})


AUTH = {rs.TOKEN_HEADER: TOKEN, "X-Review-Admin-Token": ADMIN}


@pytest.mark.parametrize("method, path, _admin", NEW_ROUTES)
@pytest.mark.parametrize("raw", [b"{not json", b"[1, 2]", b'"text"', b"\xff\xfe"], ids=["syntax", "array", "string", "bytes"])
def test_garbage_bodies_are_400_invalid_json(server, method, path, _admin, raw):
    assert send(server, method, path, raw, AUTH) == (400, {"error": "invalid JSON"})


@pytest.mark.parametrize("method, path, _admin", NEW_ROUTES)
def test_an_empty_body_is_not_invalid_json(server, method, path, _admin):
    status, payload = send(server, method, path, b"", AUTH)
    assert payload != {"error": "invalid JSON"}, (status, payload)


@pytest.mark.parametrize("method, path, _admin", NEW_ROUTES)
def test_no_token_still_gets_401_before_the_body_is_judged(server, method, path, _admin):
    assert send(server, method, path, b"{not json")[0] == 401


def test_the_old_inbox_routes_keep_treating_garbage_as_an_empty_body(server):
    status, payload = send(server, "POST", "/api/decide", b"{not json", {rs.TOKEN_HEADER: TOKEN})
    assert payload != {"error": "invalid JSON"}
