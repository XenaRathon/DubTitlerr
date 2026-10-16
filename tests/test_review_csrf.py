import http.client
import json
import threading

import pytest

import review_auth
import review_server as rs

pytestmark = pytest.mark.real_accounts
KEY = "csrf-key"
CSRF = {"X-DubTitlerr-Request": "1"}


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("REVIEW_TOKEN", KEY)
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    monkeypatch.setattr(review_auth, "SCRYPT_N", 2**4)
    monkeypatch.setattr(rs, "ROOTS", [str(tmp_path / "media")])
    monkeypatch.setattr(rs, "_STEMS_CACHE", None)
    monkeypatch.setattr(rs, "_QUEUE_CACHE", {})
    review_auth.create_user("root", "admin", "admin password")
    srv = rs.BoundedHTTPServer(("127.0.0.1", 0), rs.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def cookie():
    return {"Cookie": f"dubtitlerr_session={review_auth.sessions().create('root', False)}"}


def post(srv, headers, path="/api/decide", method="POST"):
    conn = http.client.HTTPConnection(*srv.server_address, timeout=5)
    conn.request(
        method,
        path,
        body=json.dumps({"stem": "x", "index": 0, "verdict": "reject"}),
        headers={"Content-Type": "application/json", **headers},
    )
    r = conn.getresponse()
    body = r.read()
    conn.close()
    try:
        payload = json.loads(body) if body else {}
    except ValueError:  # the 501 for OPTIONS is an HTML page
        payload = {}
    return r.status, payload, r


def own(srv):
    return "http://{}:{}".format(*srv.server_address)


def test_a_cookie_post_without_the_header_is_403_even_with_no_origin_and_no_referer(server):
    status, payload, _ = post(server, cookie())
    assert (status, payload) == (403, {"error": "cross-site request refused"})


def test_the_header_alone_is_enough(server):
    assert post(server, {**cookie(), **CSRF})[0] == 200


def test_a_foreign_origin_with_a_valid_cookie_and_header_is_403(server):
    assert post(server, {**cookie(), **CSRF, "Origin": "https://evil.example"})[0] == 403
    assert post(server, {**cookie(), **CSRF, "Origin": "null"})[0] == 403


def test_the_servers_own_origin_passes(server):
    assert post(server, {**cookie(), **CSRF, "Origin": own(server)})[0] == 200


def test_the_scheme_is_not_compared_so_a_missing_forwarded_proto_is_fine(server):
    host = "127.0.0.1"
    assert post(server, {**cookie(), **CSRF, "Origin": f"https://{host}"})[0] == 200
    assert post(server, {**cookie(), **CSRF, "Origin": f"http://{host}:9999"})[0] == 200, "ports are not compared either"


def test_a_rewritten_host_is_fine_when_the_proxy_forwards_the_public_host(server):
    proxy = {"Host": "vm102:8080", "X-Forwarded-Host": "dub.example.com"}
    assert post(server, {**cookie(), **CSRF, **proxy, "Origin": "https://dub.example.com"})[0] == 200
    assert post(server, {**cookie(), **CSRF, **proxy, "Origin": "https://evil.example"})[0] == 403
    assert post(server, {**cookie(), **CSRF, "Host": "vm102:8080", "Origin": "https://dub.example.com"})[0] == 403, (
        "no forwarded host: only the real Host counts"
    )


def test_a_non_default_public_port_is_fine_with_or_without_the_port_in_the_forwarded_host(server):
    for forwarded in ("dub.example.com:8443", "dub.example.com"):
        headers = {**cookie(), **CSRF, "Host": "vm102:8080", "X-Forwarded-Host": forwarded}
        assert post(server, {**headers, "Origin": "https://dub.example.com:8443"})[0] == 200
        assert post(server, {**headers, "Origin": "https://evil.example:8443"})[0] == 403


def test_with_auth_off_a_form_post_is_415_and_a_json_write_needs_the_header_or_the_key(server, monkeypatch):
    monkeypatch.setenv("REVIEW_AUTH", "off")
    assert post(server, {"Content-Type": "text/plain"})[0] == 415
    assert post(server, {"Content-Type": "application/x-www-form-urlencoded"})[0] == 415
    status, payload, _ = post(server, {})
    assert (status, payload) == (403, {"error": "cross-site request refused"})
    assert post(server, CSRF)[0] == 200
    assert post(server, {"X-Api-Key": KEY})[0] == 200
    conn = http.client.HTTPConnection(*server.server_address, timeout=5)
    conn.request("GET", "/api/episodes")
    assert conn.getresponse().status == 200, "reads stay open with auth off"
    conn.close()


def test_with_auth_off_a_webhook_needs_no_header(server, monkeypatch):
    monkeypatch.setenv("REVIEW_AUTH", "off")
    monkeypatch.setattr(rs.review_webhooks, "handle", lambda *a, **k: (202, {"ok": True}))
    assert post(server, {}, path="/api/webhook/sonarr")[0] == 202


def test_the_api_key_needs_neither_header_nor_origin(server):
    assert post(server, {"X-Api-Key": KEY})[0] == 200
    assert post(server, {"X-Api-Key": KEY, "Origin": "https://evil.example"})[0] == 200


def test_reads_with_a_cookie_need_no_header(server):
    conn = http.client.HTTPConnection(*server.server_address, timeout=5)
    conn.request("GET", "/api/me", headers=cookie())
    assert conn.getresponse().status == 200
    conn.close()


def test_the_legacy_token_cookie_never_authenticates_a_write(server):
    assert post(server, {"Cookie": f"dubtitlerr_token={KEY}"})[0] == 401


def test_the_legacy_token_cookie_alone_gets_401_on_api_routes_at_route_level(server):
    legacy = {"Cookie": f"dubtitlerr_token={KEY}"}
    for method, path in [("GET", "/api/episodes"), ("GET", "/api/status"), ("POST", "/api/decide")]:
        assert rs.route_full(method, path, {}, None, headers={**legacy, **CSRF})[0] == 401, (method, path)


def test_no_preflight_is_answered_and_no_cors_header_is_sent(server):
    status, _, resp = post(server, {"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}, method="OPTIONS")
    assert status == 501 and resp.getheader("Access-Control-Allow-Origin") is None
    _, _, ok = post(server, {"X-Api-Key": KEY})
    assert ok.getheader("Access-Control-Allow-Origin") is None


def test_login_itself_needs_no_header(server):
    status, _, _ = post(server, {}, path="/api/login")
    assert status == 401


def test_a_wrong_key_still_runs_the_constant_time_comparison(server, monkeypatch):
    ran = []
    real = review_auth.secrets.compare_digest
    monkeypatch.setattr(review_auth.secrets, "compare_digest", lambda a, b: ran.append(1) or real(a, b))
    assert rs.route_full("GET", "/api/episodes", {}, None, headers={"X-Api-Key": "wrong-key"})[0] == 401
    assert ran, "the token comparison must go through compare_digest"


def test_origin_null_is_refused_even_with_a_valid_cookie_and_header(server):
    status, payload, _ = post(server, {**cookie(), **CSRF, "Origin": "null"})
    assert (status, payload) == (403, {"error": "cross-site request refused"})


@pytest.mark.parametrize("value", ["true", "0", "yes", "11", "1 ", ""])
def test_a_csrf_header_value_other_than_1_is_refused(server, value):
    status, payload, _ = post(server, {**cookie(), "X-DubTitlerr-Request": value})
    assert (status, payload) == (403, {"error": "cross-site request refused"})


def test_a_put_without_the_header_is_refused_as_cross_site_before_the_route_is_judged(server):
    status, payload, _ = post(server, cookie(), path="/api/schedule", method="PUT")
    assert (status, payload) == (403, {"error": "cross-site request refused"})


@pytest.mark.parametrize(
    "ctype",
    ["text/plain", "multipart/form-data; boundary=x", "TEXT/PLAIN; charset=utf-8", "application/x-www-form-urlencoded"],
)
def test_form_content_types_are_415_on_a_session_route_with_auth_on(server, ctype):
    status, payload, _ = post(server, {**cookie(), **CSRF, "Content-Type": ctype})
    assert (status, payload) == (415, {"error": "application/json is required"})
