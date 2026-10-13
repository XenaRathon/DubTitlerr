"""POST /api/webhook/{sonarr,radarr}: their own WEBHOOK_TOKEN, no review token, never in OPEN_ROUTES."""

import http.client
import json
import pathlib
import threading

import pytest

import review_server as rs

REVIEW = "review-token"
HOOK = "webhook-token"
FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "webhooks"
SONARR = "/api/webhook/sonarr"
RADARR = "/api/webhook/radarr"


def payload(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEW_TOKEN", REVIEW)
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    monkeypatch.delenv("REVIEW_ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(rs, "_LOGIN", None)
    root = tmp_path / "Anime"
    (root / "One Pace" / "Season 31").mkdir(parents=True)
    monkeypatch.setenv("ANIME_ROOT", str(root))
    monkeypatch.setenv("REMOTE_PATH_MAPPINGS", f"/tv={root}")
    monkeypatch.setenv("REQUESTS_DIR", str(tmp_path / "requests"))
    import review_requests

    monkeypatch.setattr(review_requests, "REQUESTS_DIR", str(tmp_path / "requests"))
    monkeypatch.setenv("WEBHOOK_TOKEN", HOOK)
    return tmp_path


def post(path, body, token=None, headers=None, review=None):
    h = dict(headers or {})
    if token is not None:
        h["X-Webhook-Token"] = token
    return rs.route("POST", path, body, review, headers=h)


def test_unset_webhook_token_hides_both_routes(env, monkeypatch):
    monkeypatch.delenv("WEBHOOK_TOKEN")
    for path in (SONARR, RADARR):
        assert post(path, payload("sonarr_test.json"), HOOK) == (404, {"error": "no such route"})


def test_missing_token_is_401_wrong_is_403_right_is_200(env):
    body = payload("sonarr_test.json")
    assert post(SONARR, body)[0] == 401
    assert post(SONARR, body, "wrong") == (403, {"error": "wrong token"})
    status, out = post(SONARR, body, HOOK)
    assert status == 200 and out["ok"] is True


def test_the_review_token_neither_opens_nor_is_needed(env):
    body = payload("sonarr_test.json")
    assert post(SONARR, body, HOOK, review=None)[0] == 200, "no review token required"
    assert post(SONARR, body, None, review=REVIEW)[0] == 401, "the review token is not the webhook token"
    assert post(SONARR, body, REVIEW)[0] == 403


def test_the_token_is_also_accepted_in_the_query_string(env):
    assert rs.route("POST", SONARR + f"?token={HOOK}", payload("sonarr_test.json"), None, headers={})[0] == 200
    assert rs.route("POST", SONARR + "?token=bad", payload("sonarr_test.json"), None, headers={})[0] == 403


def test_a_sonarr_download_enqueues_one_request_and_a_repeat_returns_the_same_id(env):
    status, first = post(SONARR, payload("sonarr_download.json"), HOOK)
    assert status == 200 and first["ok"] and first["id"]
    _, again = post(SONARR, payload("sonarr_download.json"), HOOK)
    assert again["id"] == first["id"]
    status, listed = rs.route("GET", "/api/requests", {}, REVIEW)
    assert len(listed) == 1 and listed[0]["season"] == 31


def test_radarr_and_unknown_events(env):
    assert post(RADARR, payload("radarr_test.json"), HOOK)[1]["ok"] is True
    status, out = post(SONARR, payload("sonarr_rename.json"), HOOK)
    assert status == 200 and out.get("ignored") is True


def test_webhook_routes_are_not_open_routes(env):
    assert not any("webhook" in p for _m, p in rs.OPEN_ROUTES)
    assert set(rs.OPEN_ROUTES) == {("GET", "/healthz"), ("GET", "/api/auth-mode"), ("POST", "/api/login")}


def test_a_get_on_a_webhook_path_is_not_served(env):
    assert rs.route("GET", SONARR, {}, None)[0] == 401
    assert rs.route("GET", SONARR, {}, REVIEW)[0] == 404


# --- the HTTP layer: raw body, 400 for bad JSON, 413 over 256 KiB ----------------------------------------------------


@pytest.fixture
def server(env):
    srv = rs.BoundedHTTPServer(("127.0.0.1", 0), rs.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def http_post(srv, path, raw, headers=None):
    conn = http.client.HTTPConnection(*srv.server_address, timeout=5)
    conn.request("POST", path, body=raw, headers={"Content-Type": "application/json", **(headers or {})})
    r = conn.getresponse()
    out = (r.status, json.loads(r.read() or b"{}"))
    conn.close()
    return out


def test_http_good_body_with_the_header_token(server):
    raw = json.dumps(payload("sonarr_test.json")).encode()
    assert http_post(server, SONARR, raw, {"X-Webhook-Token": HOOK})[0] == 200
    assert http_post(server, SONARR + f"?token={HOOK}", raw)[0] == 200


def test_http_bad_json_is_400_not_an_empty_object(server):
    status, out = http_post(server, SONARR, b"{not json", {"X-Webhook-Token": HOOK})
    assert (status, out) == (400, {"error": "invalid JSON"})
    assert http_post(server, SONARR, b"[1, 2]", {"X-Webhook-Token": HOOK})[0] == 400
    assert http_post(server, SONARR, b"", {"X-Webhook-Token": HOOK})[0] == 400


def test_http_body_over_256_kib_is_413_but_only_for_a_good_token(server):
    big = json.dumps({"eventType": "Test", "pad": "x" * (256 * 1024)}).encode()
    assert http_post(server, SONARR, big, {"X-Webhook-Token": HOOK}) == (413, {"error": "body too large"})
    assert http_post(server, SONARR, big)[0] == 401, "token is checked before the body is looked at"
    assert http_post(server, SONARR, big, {"X-Webhook-Token": "bad"})[0] == 403


def test_http_unset_token_is_404_even_with_a_body(server, monkeypatch):
    monkeypatch.delenv("WEBHOOK_TOKEN")
    assert http_post(server, SONARR, b"{}", {"X-Webhook-Token": HOOK})[0] == 404
