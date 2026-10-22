"""[S-7] [S-8] Connections through PUT /api/settings and the Test action: keys are write-only, a new URL drops the stored key,
link-local targets are refused, and a stage can only name a connection that exists."""

import http.server
import json
import os
import socket
import stat
import threading
import urllib.error

import pytest

import settings_api as api
import settings_store as store

KEY = "sk-conn-key-0123456789abcdef"  # gitleaks:allow -- test fixture, not a real credential
LOCAL = {"name": "local", "kind": "llamacpp", "url": "http://192.168.1.20:8090/v1/chat/completions", "model": "qwen3-4b-instruct"}
CLOUD = {
    "name": "cloud",
    "kind": "openai",
    "url": "https://api.example.test/v1/chat/completions",
    "model": "gpt-x",
    "api_key": KEY,
}


@pytest.fixture
def env(tmp_path):
    return {"CONFIG_DIR": str(tmp_path), "EFFECTIVE_ENV_FILE": str(tmp_path / "effective.env")}


@pytest.fixture(autouse=True)
def login_on(monkeypatch):
    monkeypatch.setattr(api, "_secrets_writable", lambda: True)


@pytest.fixture(autouse=True)
def mock_dns(monkeypatch):
    real_gai = socket.getaddrinfo

    def fake_gai(host, port, *args, **kwargs):
        if host == "api.example.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 443))]
        return real_gai(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_gai)


def put(env, **body):
    if "revision" not in body:
        body["revision"] = store.load(env).rev
    return api.handle("PUT", "/api/settings", body, environ=env)


def listed(env):
    return {c["name"]: c for c in api.handle("GET", "/api/settings", environ=env)[1]["connections"]}


def test_a_connection_is_created_picked_for_a_stage_and_the_key_is_only_a_flag(env, tmp_path):
    status, payload = put(env, connections=[LOCAL, CLOUD], stages={"repair": "cloud", "verify": "local"})
    assert status == 200 and payload["changed"] == ["connection:cloud", "connection:local", "stages"]
    got = api.handle("GET", "/api/settings", environ=env)[1]
    assert got["stages"] == {"repair": "cloud", "verify": "local"}
    assert listed(env)["cloud"]["api_key"] == {"set": True} and listed(env)["local"]["api_key"] == {"set": False}
    assert KEY not in json.dumps(got)
    assert stat.S_IMODE(os.stat(tmp_path / "secrets.json").st_mode) == 0o600
    assert KEY in (tmp_path / "secrets.json").read_text() and KEY not in (tmp_path / "settings.json").read_text()


def test_a_changed_url_without_a_new_key_leaves_the_key_unset(env):
    put(env, connections=[CLOUD])
    moved = {k: v for k, v in CLOUD.items() if k != "api_key"} | {"url": "https://attacker.example.test/v1/chat/completions"}
    status, payload = put(env, connections=[moved])
    assert status == 200 and listed(env)["cloud"]["api_key"] == {"set": False}
    assert store.load(env).conn_keys == {}


def test_a_changed_url_with_a_key_in_the_same_save_keeps_that_key(env):
    put(env, connections=[CLOUD])
    moved = {**CLOUD, "url": "https://other.example.test/v1/chat/completions", "api_key": KEY + "-new"}
    assert put(env, connections=[moved])[0] == 200
    assert store.load(env).conn_keys == {"cloud": KEY + "-new"}


def test_an_unchanged_connection_without_a_key_field_keeps_its_key(env):
    put(env, connections=[CLOUD])
    kept = {k: v for k, v in CLOUD.items() if k != "api_key"} | {"model": "gpt-y"}
    assert put(env, connections=[kept])[0] == 200 and store.load(env).conn_keys == {"cloud": KEY}


def test_a_key_can_be_cleared_and_a_deleted_connection_takes_its_key_along(env):
    put(env, connections=[CLOUD, LOCAL])
    assert put(env, connections=[{**CLOUD, "api_key": {"clear": True}}, LOCAL])[0] == 200 and store.load(env).conn_keys == {}
    put(env, connections=[CLOUD, LOCAL])
    assert put(env, connections=[LOCAL])[0] == 200 and store.load(env).conn_keys == {} and list(listed(env)) == ["local"]


def test_a_link_local_url_is_refused_with_400_naming_the_field(env, tmp_path):
    status, payload = put(env, connections=[{**LOCAL, "url": "http://169.254.169.254/latest"}])
    assert (
        status == 400 and "link-local" in payload["errors"]["connections.local.url"] and not (tmp_path / "settings.json").exists()
    )


def test_a_stage_may_not_name_a_connection_that_does_not_exist_or_was_deleted(env):
    status, payload = put(env, connections=[LOCAL], stages={"repair": "ghost"})
    assert status == 400 and payload["errors"] == {"stages.repair": "points at a connection that does not exist"}
    put(env, connections=[LOCAL], stages={"repair": "local"})
    status, payload = put(env, connections=[])
    assert status == 400 and "stages.repair" in payload["errors"]
    assert (
        put(env, connections=[], stages={"repair": None})[0] == 200
        and api.handle("GET", "/api/settings", environ=env)[1]["stages"] == {}
    )


def test_key_rules_name_the_field(env):
    status, payload = put(env, connections=[{**LOCAL, "api_key": KEY}])
    assert status == 400 and "OpenAI" in payload["errors"]["connections.local.api_key"]
    status, payload = put(env, connections=[{**CLOUD, "url": "http://192.168.1.20/v1/chat/completions"}])
    assert status == 400 and "https" in payload["errors"]["connections.cloud.api_key"]
    status, payload = put(env, connections=[LOCAL, LOCAL])
    assert status == 400 and "already used" in payload["errors"]["connections.local.name"]


def test_a_connection_key_needs_login_and_writes_nothing_without_it(env, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_secrets_writable", lambda: False)
    assert put(env, connections=[CLOUD])[0] == 403 and not (tmp_path / "secrets.json").exists()
    assert put(env, connections=[LOCAL])[0] == 200, "a connection with no key is not a secret write"


def test_the_audit_line_names_the_connection_url_host_and_never_the_key(env, capsys):
    put(env, connections=[CLOUD])
    out = capsys.readouterr().out
    assert "connection:cloud" in out and "url connection cloud=https://api.example.test/v1/chat/completions" in out
    assert "connection:cloud.api_key" in out and KEY not in out


def test_refuse_two_different_ollama_connections_across_stages(env):
    oll1 = {"name": "oll1", "kind": "ollama", "url": "http://127.0.0.1:11434/api/generate"}
    oll2 = {"name": "oll2", "kind": "ollama", "url": "http://192.168.1.50:11434/api/generate"}
    status, payload = put(env, connections=[oll1, oll2], stages={"repair": "oll1", "verify": "oll2"})
    assert status == 400
    assert "stages.verify" in payload["errors"] or "stages.repair" in payload["errors"]


def test_decision_stage_refuses_host_decision_client_will_not_call(env):
    openai_bad = {"name": "bad_dec", "kind": "openai", "url": "https://api.openai.com/v1/chat/completions", "model": "gpt-4o"}
    status, payload = put(env, connections=[openai_bad], stages={"decision": "bad_dec"})
    assert status == 400
    assert "decision_client" in payload["errors"]["stages.decision"]


class Response:
    status = 200

    def read(self):
        return b"{}"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_test_action_probes_a_saved_connection_with_its_key_and_models_address(env):
    put(env, connections=[CLOUD])
    seen = []

    def opener(request, timeout=None):
        seen.append((request.full_url, request.get_header("Authorization"), timeout))
        return Response()

    status, payload = api.handle("POST", "/api/settings/test", {"connection": "cloud"}, environ=env, opener=opener)
    assert status == 200 and payload["ok"] is True
    # The hostname (api.example.test) is kept in the URL; socket is pinned
    assert seen == [("https://api.example.test/v1/models", f"Bearer {KEY}", 10.0)]
    assert KEY not in json.dumps(payload)


def test_a_failing_probe_cannot_carry_the_key_or_the_query(env):
    put(env, connections=[CLOUD])

    def opener(request, timeout=None):
        raise urllib.error.URLError(f"connection failed to {request.full_url}?key={KEY}")

    status, payload = api.handle("POST", "/api/settings/test", {"connection": "cloud"}, environ=env, opener=opener)
    assert status == 200 and payload["ok"] is False and KEY not in json.dumps(payload)


def test_testing_a_connection_that_does_not_exist_is_400_and_a_keyless_openai_one_says_so(env):
    assert api.handle("POST", "/api/settings/test", {"connection": "ghost"}, environ=env)[0] == 400
    put(env, connections=[{k: v for k, v in CLOUD.items() if k != "api_key"}])
    assert api.handle("POST", "/api/settings/test", {"connection": "cloud"}, environ=env)[1]["error"] == "API key not configured"


def test_the_test_action_is_an_admin_route():
    assert api.ROLE_ENTRIES[("POST", "/api/settings/test")] == "admin"


def test_the_test_action_refuses_when_resolved_address_is_link_local(env, monkeypatch):
    conn_meta = {"name": "meta", "kind": "llamacpp", "url": "http://some-host.test:8090/v1/chat/completions"}
    put(env, connections=[conn_meta])

    def mock_gai_meta(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_gai_meta)
    status, payload = api.handle("POST", "/api/settings/test", {"connection": "meta"}, environ=env)
    assert status == 200 and payload["ok"] is False
    assert "link-local" in payload["error"]


def test_the_test_action_redirect_reports_302_and_second_server_never_sees_auth(env):
    """Test probe uses an opener whose redirect handler returns None (3xx reports HTTP 302);
    two-server test asserts the second server never sees Authorization."""
    server2_seen = []

    class Server2Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            server2_seen.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server2 = http.server.HTTPServer(("127.0.0.1", 0), Server2Handler)
    s2_port = server2.server_address[1]
    threading.Thread(target=server2.serve_forever, daemon=True).start()

    class Server1Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{s2_port}/v1/models")
            self.end_headers()

        def log_message(self, *args):
            pass

    server1 = http.server.HTTPServer(("127.0.0.1", 0), Server1Handler)
    s1_port = server1.server_address[1]
    threading.Thread(target=server1.serve_forever, daemon=True).start()

    redirect_conn = {
        "name": "redir",
        "kind": "openai",
        "url": f"http://127.0.0.1:{s1_port}/v1/chat/completions",
        "api_key": KEY,
    }
    put(env, connections=[redirect_conn])

    # No opener passed -> uses default probe opener with _NoRedirectHandler
    status, payload = api.handle("POST", "/api/settings/test", {"connection": "redir"}, environ=env)
    assert status == 200
    assert payload["ok"] is False
    assert payload["error"] == "HTTP 302"
    assert server2_seen == []


def test_test_connection_over_tls_with_ca_pinned_context(env, tmp_path):
    import ssl
    import subprocess

    key_path = str(tmp_path / "server_key.pem")
    cert_path = str(tmp_path / "server_cert.pem")
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            key_path,
            "-out",
            cert_path,
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        capture_output=True,
        check=True,
    )

    class TLSHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"data": []}')

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), TLSHandler)
    port = server.server_port
    s_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    s_ctx.load_cert_chain(cert_path, key_path)
    server.socket = s_ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    c_ctx = ssl.create_default_context(cafile=cert_path)
    put(
        env,
        connections=[
            {"name": "tlsconn", "kind": "openai", "url": f"https://localhost:{port}/v1/chat/completions", "api_key": KEY}
        ],
    )

    status, payload = api.test_connection("tlsconn", environ=env, context=c_ctx)
    assert status == 200
    assert payload["ok"] is True


def test_test_connection_tries_every_checked_address_in_order(env, monkeypatch):
    class ServerHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"data": []}')

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), ServerHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # Host resolves to [dead_ip, 127.0.0.1]
    dead_ip = "127.0.0.244"  # port not open on this loopback address

    def mock_gai(host, p, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (dead_ip, p)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", p)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mock_gai)

    put(
        env,
        connections=[{"name": "fallback", "kind": "llamacpp", "url": f"http://myhost.test:{port}/v1/chat/completions"}],
    )
    status, payload = api.handle("POST", "/api/settings/test", {"connection": "fallback"}, environ=env)
    assert status == 200
    assert payload["ok"] is True


def test_orphan_key_dropped_when_new_connection_has_no_key(env):
    st = store.load(env)
    st.conn_keys["cloud"] = KEY
    store.save(st, env)
    assert store.load(env).conn_keys == {"cloud": KEY}

    # PUT creates connection "cloud" with NO key in save
    status, payload = put(env, connections=[{k: v for k, v in CLOUD.items() if k != "api_key"}])
    assert status == 200
    assert store.load(env).conn_keys == {}
    assert listed(env)["cloud"]["api_key"] == {"set": False}


def test_get_redacts_connection_url_and_reports_extra_body_as_set_bool(env):
    st = store.load(env)
    st.connections = [
        {
            "name": "redactme",
            "kind": "openai",
            "url": "https://admin:pass123@api.example.test/v1/chat/completions?key=QLEAK",
            "model": "gpt-x",
            "extra_body": {},
            "timeout_connect": 10.0,
            "timeout_read": 120.0,
        },
        {
            "name": "bodyleak",
            "kind": "openai",
            "url": "https://api.example.test/v1/chat/completions",
            "model": "gpt-x",
            "extra_body": {"api_key": "sk-BODYLEAK"},
            "timeout_connect": 10.0,
            "timeout_read": 120.0,
        },
    ]
    st.conn_keys = {"bodyleak": KEY}
    store.save(st, env)

    got = api.handle("GET", "/api/settings", environ=env)[1]
    # load refuses a stored URL with user info or a query, so it never reaches the page at all
    assert [c["name"] for c in got["connections"]] == ["bodyleak"]
    conn = got["connections"][0]
    assert conn["url"] == "https://api.example.test/v1/chat/completions"
    assert "admin" not in json.dumps(got)
    assert "pass123" not in json.dumps(got)
    assert "QLEAK" not in json.dumps(got)
    assert conn["extra_body"] == {"set": True}
    assert "sk-BODYLEAK" not in json.dumps(got)

    # Refuse query or fragment on connection url at PUT
    status, payload = put(
        env,
        connections=[
            {
                "name": "badurl",
                "kind": "openai",
                "url": "https://api.example.test/v1?key=QLEAK",
            }
        ],
    )
    assert status == 400
    assert "query or fragment" in payload["errors"]["connections.badurl.url"]


def test_get_to_put_round_trip_preserves_extra_body(env):
    conn_openai = {
        "name": "cloud",
        "kind": "openai",
        "url": "https://api.example.test/v1/chat/completions",
        "model": "gpt-x",
        "extra_body": {"provider": {"order": ["x"]}},
        "api_key": KEY,
    }
    put(env, connections=[conn_openai, LOCAL])
    assert store.load(env).connections[0]["extra_body"] == {"provider": {"order": ["x"]}}

    got = api.handle("GET", "/api/settings", environ=env)[1]
    conns_from_get = got["connections"]
    cloud_get = next(c for c in conns_from_get if c["name"] == "cloud")
    local_get = next(c for c in conns_from_get if c["name"] == "local")
    assert cloud_get["extra_body"] == {"set": True}
    assert local_get["extra_body"] == {"set": False}

    # Round trip: take GET's connection list, drop api_key, and PUT it back
    body_conns = [{k: v for k, v in c.items() if k != "api_key"} for c in conns_from_get]
    status, payload = put(env, connections=body_conns, revision=got["revision"])
    assert status == 200
    assert payload["changed"] == []

    loaded = store.load(env)
    assert loaded.connections[0]["extra_body"] == {"provider": {"order": ["x"]}}
    assert loaded.connections[1]["extra_body"] == {}

    # Changing model while sending {"set": True} keeps the prior extra_body
    body_conns[0]["model"] = "gpt-y"
    status, payload = put(env, connections=body_conns)
    assert status == 200
    assert payload["changed"] == ["connection:cloud"]
    assert store.load(env).connections[0]["extra_body"] == {"provider": {"order": ["x"]}}

    # Explicitly sending {} clears extra_body
    body_conns[0]["extra_body"] = {}
    status, payload = put(env, connections=body_conns)
    assert status == 200
    assert store.load(env).connections[0]["extra_body"] == {}

    # {"set": True} on a non-openai connection is rejected
    status, payload = put(env, connections=[{**LOCAL, "extra_body": {"set": True}}])
    assert status == 400
    assert "OpenAI-compatible" in payload["errors"]["connections.local.extra_body"]
