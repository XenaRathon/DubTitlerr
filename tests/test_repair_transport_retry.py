"""REPAIR_TRANSPORT_RETRIES: the openai repair backend retries a transport error (before any response) and nothing else.
Default 0 = the legacy single attempt. No network: _post_json is a fake."""

import http.client
import json
import socket
import urllib.error

import pytest

import repair

OK = {"choices": [{"message": {"content": "fixed line"}}]}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(repair, "OPENAI_URL", "https://api.example.test/v1/chat/completions")
    monkeypatch.setattr(repair, "OPENAI_KEY_ENV", "TEST_REPAIR_KEY")
    monkeypatch.setenv("TEST_REPAIR_KEY", "sk-test-0123456789")
    monkeypatch.setenv("REPAIR_EXTRA_BODY", "")
    monkeypatch.delenv("REPAIR_OPENAI_RETRIES", raising=False)
    monkeypatch.delenv("REPAIR_TRANSPORT_RETRIES", raising=False)
    sleeps = []
    monkeypatch.setattr(repair, "_sleep", sleeps.append)
    return sleeps


def sent(exc):
    """A failure after conn.request() completed: the server has the request."""
    exc.not_sent = False
    return exc


def script(monkeypatch, *outcomes):
    """Each call to _post_json pops the next outcome: an exception instance is raised, anything else is returned."""
    calls = []

    def fake(url, body, timeout=180, headers=None):
        calls.append(1)
        out = outcomes[min(len(calls), len(outcomes)) - 1]
        if isinstance(out, BaseException):
            if not hasattr(out, "not_sent"):
                out.not_sent = True  # the default fake fails BEFORE the request is out; sent() marks the others
            raise out
        return out

    monkeypatch.setattr(repair, "_post_json", fake)
    return calls


def test_with_0_a_transport_error_is_one_attempt_and_unreachable(env, monkeypatch):
    """Legacy: REPAIR_TRANSPORT_RETRIES=0 (the default is 2 since phase 27) is the single attempt."""
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "0")
    calls = script(monkeypatch, ConnectionResetError("reset"), OK)
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE
    assert len(calls) == 1 and env == []


def test_a_transport_error_is_retried_and_a_success_counts_as_success(env, monkeypatch):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    calls = script(monkeypatch, ConnectionResetError("reset"), OK)
    before = repair.transport_retries_total()
    assert repair.llm_openai("P", None) == "fixed line"
    assert len(calls) == 2 and repair.transport_retries_total() == before + 1
    assert env == [0.5]  # a short backoff


def test_an_error_that_never_clears_gives_up_after_the_budget(env, monkeypatch, capsys):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    calls = script(monkeypatch, OSError("down"))
    before = repair.transport_retries_total()
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE
    assert len(calls) == 3 and repair.transport_retries_total() == before + 2 and env == [0.5, 1.0]
    assert "OSError" in capsys.readouterr().out


@pytest.mark.parametrize(
    "exc",
    [
        OSError("x"),
        ConnectionResetError("x"),
        ConnectionRefusedError("x"),
        urllib.error.URLError("x"),
        socket.timeout("timed out"),
        http.client.RemoteDisconnected("x"),
        http.client.IncompleteRead(b""),
    ],
)
def test_every_transport_failure_before_a_response_is_retried(env, monkeypatch, exc):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "1")
    calls = script(monkeypatch, exc, OK)
    assert repair.llm_openai("P", None) == "fixed line" and len(calls) == 2


def test_the_request_deadline_is_not_a_transport_error(env, monkeypatch):
    """A watchdog timeout can fire mid-response; it keeps its old meaning (unreachable), no retry."""
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    calls = script(monkeypatch, TimeoutError("request deadline of 300s exceeded"), OK)
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE and len(calls) == 1


@pytest.mark.parametrize("status", [400, 401, 404, 500, 503])
def test_an_http_answer_is_never_a_transport_retry(env, monkeypatch, status):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    monkeypatch.setenv("REPAIR_OPENAI_RETRIES", "0")
    calls = script(monkeypatch, repair._HttpError(status, f"HTTP {status}", None), OK)
    repair.llm_openai("P", None)
    assert len(calls) == 1 and repair.transport_retries_total() >= 0


def test_a_429_keeps_its_own_retry_path_and_adds_no_transport_retries(env, monkeypatch):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    calls = script(monkeypatch, repair._HttpError(429, "HTTP 429", None), OK)
    before = repair.transport_retries_total()
    assert repair.llm_openai("P", None) == "fixed line"
    assert len(calls) == 2 and repair.transport_retries_total() == before and env == [2.0]  # the 429 backoff, not ours


def test_a_parsed_but_unusable_answer_is_not_retried(env, monkeypatch):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    calls = script(monkeypatch, {"choices": []}, OK)  # malformed body: a KeyError/IndexError, not a transport failure
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE and len(calls) == 1
    calls = script(monkeypatch, json.JSONDecodeError("bad", "x", 0), OK)
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE and len(calls) == 1


def test_a_soft_stop_ends_the_retries(env, monkeypatch):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    monkeypatch.setattr(repair, "stop_requested", lambda: True)
    calls = script(monkeypatch, OSError("down"), OK)
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE and len(calls) == 1


def test_the_budget_is_clamped(env, monkeypatch):
    for raw, expect in (("2", 2), ("9", 5), ("-1", 0), ("lots", 2), ("", 2)):
        monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", raw)
        assert repair._transport_retries() == expect, raw


def test_only_the_openai_backend_retries(env, monkeypatch):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    calls = []
    monkeypatch.setattr(repair, "_post_json", lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(OSError("down")))
    monkeypatch.setattr(repair, "LLAMACPP_URL", "http://127.0.0.1:1/v1")
    repair.llm_llamacpp("P", "m")
    assert len(calls) == 1


def test_the_summary_reports_transport_retries_only_when_the_budget_is_set(tmp_path, monkeypatch, env):
    import test_repair

    import glossary

    def run(name):
        sub = tmp_path / name
        sub.mkdir()
        stem = str(sub / "ep")
        conf = stem + repair.CONF_SUFFIX
        segs = [
            {
                "start": float(k * 6),
                "end": float(k * 6 + 6),
                "text": f"garbled line {k}",
                "avg_logprob": -0.6,
                "no_speech_prob": 0.1,
            }
            for k in range(12)
        ]
        test_repair._write_conf(conf, stem + repair.SRT_SUFFIX, segs)
        monkeypatch.setattr(repair, "find_video", lambda s: str(sub / "ep.mkv"))
        monkeypatch.setattr(repair, "glossary_for", lambda video: glossary.load_dict({}))
        monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 80.0, "the official sub")])
        monkeypatch.setattr(repair, "REPAIR_BACKEND", "openai")
        script(monkeypatch, ConnectionResetError("reset"), OK)
        repair.process(conf)
        return json.load(open(stem + ".dubtitles.repair-summary.json"))

    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "0")
    off = run("off")
    assert "transport_retries" not in off and off["unreachable"] == 1  # the legacy single attempt
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    on = run("on")
    assert on["transport_retries"] == 1 and on["unreachable"] == 0 and on["repaired"] > 0


# ---- only failures BEFORE the request is out are retried ----------- ----


@pytest.mark.parametrize(
    "exc",
    [socket.timeout("timed out"), http.client.RemoteDisconnected("closed"), http.client.IncompleteRead(b"par"), OSError("reset")],
)
def test_a_failure_after_the_request_was_sent_is_never_retried(env, monkeypatch, exc):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    calls = script(monkeypatch, sent(exc), OK)
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE and len(calls) == 1 and env == []


def test_retries_stop_at_the_episode_deadline(env, monkeypatch):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    monkeypatch.setattr(repair, "_deadline_passed", lambda: True)
    calls = script(monkeypatch, ConnectionRefusedError("no"), OK)
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE and len(calls) == 1


def test_the_backoff_is_spent_from_the_episode_retry_sleep_budget(env, monkeypatch):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    monkeypatch.setattr(repair, "_retry_budget_left", 1.2)
    monkeypatch.setattr(repair, "_retry_slept", 0.0)
    calls = script(monkeypatch, ConnectionRefusedError("no"))
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE
    # 0.5 s fits (0.7 left), the 1.0 s second wait does not
    assert len(calls) == 2 and env == [0.5] and repair._retry_budget_left == pytest.approx(0.7)


def test_transport_retries_draw_from_the_same_attempt_budget_as_status_retries(env, monkeypatch):
    """At most REPAIR_OPENAI_RETRIES + 1 POSTs for one line, whatever the two layers are set to."""
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "5")
    monkeypatch.setenv("REPAIR_OPENAI_RETRIES", "1")
    calls = script(monkeypatch, ConnectionRefusedError("no"))
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE and len(calls) == 2
    monkeypatch.setenv("REPAIR_OPENAI_RETRIES", "2")
    e503 = repair._HttpError(503, "x", None)
    calls = script(monkeypatch, ConnectionRefusedError("no"), e503, e503, OK)
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE and len(calls) == 3  # one refused + two 503s, then stop


# ---- against a real socket: how many requests did the server RECEIVE ----


class CountingServer:
    """Loopback server that counts requests received IN FULL, then misbehaves as told: 'hang' (read timeout), 'close' (no answer),
    'partial' (headers and half a body, then close) or 'ok'."""

    def __init__(self, mode):
        import threading

        self.mode, self.received = mode, 0
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(8)
        self.port = self.srv.getsockname()[1]
        self.stop = False
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        import threading

        while not self.stop:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(c,), daemon=True).start()

    def handle(self, c):
        import time

        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = c.recv(4096)
            if not chunk:
                return
            buf += chunk
        head, _, body = buf.partition(b"\r\n\r\n")
        want = int([ln.split(b":")[1] for ln in head.split(b"\r\n") if ln.lower().startswith(b"content-length")][0])
        while len(body) < want:
            body += c.recv(4096)
        self.received += 1
        if self.mode == "hang":
            time.sleep(1.5)
        elif self.mode == "partial":
            c.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 500\r\n\r\n{"choices": [')
        elif self.mode == "ok":
            payload = json.dumps(OK).encode()
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n" % len(payload) + payload)
        c.close()

    def close(self):
        self.stop = True
        self.srv.close()


@pytest.fixture
def live(env, monkeypatch):
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    monkeypatch.setattr(repair, "TIMEOUT_READ", 0.3)
    made = []

    def make(mode):
        srv = CountingServer(mode)
        made.append(srv)
        monkeypatch.setattr(repair, "OPENAI_URL", f"http://127.0.0.1:{srv.port}/v1/chat/completions")
        return srv

    yield make
    for srv in made:
        srv.close()


@pytest.mark.parametrize("mode", ["hang", "close", "partial"])
def test_the_server_receives_exactly_one_request_when_the_failure_comes_after_the_send(live, mode):
    srv = live(mode)
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE
    assert srv.received == 1  # a read timeout, RemoteDisconnected and IncompleteRead are not re-sent (and re-billed)


def test_a_refused_connection_is_retried_to_the_budget(live, env, monkeypatch):
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()  # nothing listens on that port now
    monkeypatch.setattr(repair, "OPENAI_URL", f"http://127.0.0.1:{port}/v1/chat/completions")
    before = repair.transport_retries_total()
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE
    assert repair.transport_retries_total() == before + 2 and env == [0.5, 1.0]


def test_a_live_success_needs_no_retry(live, env):
    srv = live("ok")
    assert repair.llm_openai("P", None) == "fixed line" and srv.received == 1 and env == []


# ---- phase 28 F11: a failure once transmission has started is ambiguous and never re-sent --------------------------------------


def _loopback_server(received):
    import contextlib
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            out = json.dumps(OK).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(out)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_a_send_failure_after_the_body_reached_the_server_is_not_resent(env, monkeypatch):
    """Sol's probe: HTTPConnection.send forwards the complete body, then raises OSError before conn.request returns. The server
    HAS the request (and may bill it), so it must not be sent again."""
    received = []
    server, thread = _loopback_server(received)
    base = http.client.HTTPConnection
    failed = []

    class AmbiguousSend(base):
        def send(self, data):
            super().send(data)
            if isinstance(data, bytes) and data.startswith(b"{") and not failed:
                failed.append(True)
                raise OSError("injected send failure after the bytes reached the peer")

    try:
        monkeypatch.setattr(repair, "OPENAI_URL", f"http://127.0.0.1:{server.server_port}/v1/chat/completions")
        monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
        monkeypatch.setattr(repair.http.client, "HTTPConnection", AmbiguousSend)
        result = repair.llm_openai("exact duplicated prompt", None)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert result == repair.LLM_UNREACHABLE and len(received) == 1


def test_a_refused_connection_is_still_retried(env, monkeypatch):
    """The only retried failures are those known to happen before transmission starts."""
    attempts = []
    base = http.client.HTTPConnection

    class Refuses(base):
        def connect(self):
            attempts.append(1)
            if len(attempts) == 1:
                raise ConnectionRefusedError("refused")
            raise OSError("second attempt also fails, after the first was retried")

    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    monkeypatch.setattr(repair.http.client, "HTTPConnection", Refuses)
    monkeypatch.setattr(repair, "OPENAI_URL", "http://127.0.0.1:9/v1/chat/completions")
    assert repair.llm_openai("P", None) == repair.LLM_UNREACHABLE
    assert len(attempts) == 3  # one attempt plus the two retries: connect failures are retried


def test_the_summary_key_appears_only_when_the_openai_backend_ran(env, tmp_path, monkeypatch):
    """transport_retries is about the openai client: a llamacpp/ollama run has no such counter, whatever the budget says."""
    import test_repair_dismiss as d

    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "2")
    monkeypatch.setattr(repair, "REPAIR_BACKEND", "llamacpp")
    _, summary = d._episode(tmp_path, monkeypatch, "the old line", "the old line is here now")
    assert "transport_retries" not in summary
    monkeypatch.setattr(repair, "REPAIR_BACKEND", "openai")
    again = tmp_path / "again"
    again.mkdir()
    _, summary = d._episode(again, monkeypatch, "the old line", "the old line is here now")
    assert summary["transport_retries"] == 0
