"""[S-15] Real-socket HTTP test for review server: body-write stall disconnect."""

import http.client
import json
import socket
import threading
import time

import review_server


def _start_server(monkeypatch, timeout):
    """Start review_server on port 0 in a background thread. Returns (server, thread)."""
    monkeypatch.setattr(review_server.Handler, "timeout", timeout)
    srv = review_server.BoundedHTTPServer(("127.0.0.1", 0), review_server.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)  # let the listener come up before the test connects
    return srv, thread


def _stop_server(srv, thread):
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def test_a_client_that_stalls_its_body_write_is_disconnected_at_handler_timeout(monkeypatch):
    """A client that stalls its body write is disconnected at Handler.timeout.

    A short timeout is patched in so the test stays fast while still exercising the
    real socket deadline: the client sends headers declaring a body, then sends
    nothing further and blocks on recv. The server must close the connection at
    (roughly) `timeout` seconds, not hang forever.
    """
    stall_timeout = 0.5
    srv, thread = _start_server(monkeypatch, stall_timeout)
    try:
        port = srv.server_address[1]
        sock = socket.create_connection(("127.0.0.1", port), timeout=stall_timeout + 5)
        try:
            request = "POST /api/decide HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 1000000\r\n\r\n"
            sock.sendall(request.encode("ascii"))
            # Stall: never send the declared body. recv() blocks until the server
            # hits Handler.timeout and closes the socket (empty read) or the test's
            # own socket timeout fires first, which would be the failure we assert against.
            start = time.monotonic()
            data = sock.recv(4096)
            elapsed = time.monotonic() - start
        finally:
            sock.close()

        assert data == b"", "server should close the connection (empty read), not respond"
        assert elapsed < stall_timeout + 5, (
            f"disconnect took {elapsed:.2f}s, expected close near Handler.timeout={stall_timeout}s"
        )
        assert elapsed >= stall_timeout * 0.5, (
            f"disconnect at {elapsed:.2f}s happened suspiciously before Handler.timeout={stall_timeout}s"
        )
    finally:
        _stop_server(srv, thread)


def test_a_real_socket_get_api_episodes_gated_by_token(monkeypatch, tmp_path):
    """GET /api/episodes is gated by token: no token → 401; with token → 200."""
    token = "test-token-12345"
    monkeypatch.setenv("REVIEW_TOKEN", token)
    # Also monkeypatch Handler.timeout to keep the test fast
    monkeypatch.setattr(review_server.Handler, "timeout", 0.5)

    srv, thread = _start_server(monkeypatch, 0.5)
    try:
        port = srv.server_address[1]

        # Without token → 401
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
        conn.request("GET", "/api/episodes")
        resp = conn.getresponse()
        body = resp.read()
        assert resp.status == 401
        data = json.loads(body.decode("utf-8"))
        assert data.get("error") == "a token is required"
        conn.close()

        # With token → 200
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
        conn.request("GET", "/api/episodes", headers={"X-Review-Token": token})
        resp = conn.getresponse()
        body = resp.read()
        assert resp.status == 200
        data = json.loads(body.decode("utf-8"))
        assert isinstance(data, dict)
        assert isinstance(data.get("episodes"), list)
        conn.close()

    finally:
        _stop_server(srv, thread)


def test_opening_max_concurrent_plus_one_connections_results_in_extra_being_closed(monkeypatch, tmp_path):
    """Opening MAX_CONCURRENT + 1 simultaneous connections results in the extra connection
    being closed by the server rather than queued.

    Deterministic, not a race. MAX_CONCURRENT is read ONCE, in BoundedHTTPServer.__init__
    (`self._slots = threading.Semaphore(MAX_CONCURRENT)`), so it must be monkeypatched BEFORE
    the server is constructed -- patching it afterwards would leave the semaphore at whatever
    size it had already been built with. Both slots are then filled deliberately by two sockets
    held open: each sends request headers with no terminating blank line, so its handler blocks
    in rfile.read() and cannot release its slot. Only the THIRD connection is asserted on --
    process_request finds no free slot, refuses it, and closes the socket, so the client's
    recv() returns an empty read.
    """
    monkeypatch.setattr(review_server, "MAX_CONCURRENT", 2)
    # 5s, not the 0.5s the stall test above uses: the two slot-filling sockets must not be
    # closed out from under this test by Handler.timeout before the third is attempted.
    monkeypatch.setattr(review_server.Handler, "timeout", 5)
    monkeypatch.delenv("REVIEW_TOKEN", raising=False)
    monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
    monkeypatch.setattr(review_server, "known_stems", lambda: [])
    review_server.resolve_token(str(tmp_path))

    srv = review_server.BoundedHTTPServer(("127.0.0.1", 0), review_server.Handler)
    host, port = srv.server_address
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    sockets = []
    try:
        for _ in range(2):
            s = socket.create_connection((host, port), timeout=5)
            s.sendall(b"GET /index.html HTTP/1.1\r\nHost: x\r\n")  # no blank line -- holds the slot
            sockets.append(s)
        # Bounded poll on the server's OWN semaphore instead of a guessed sleep: a
        # threading.Semaphore decrements _value on each successful acquire, so 0 here means
        # both handlers are unambiguously in flight and the third connection will be refused.
        # Waiting on real state turns the old wall-clock race into a named failure rather
        # than a flake -- if the slots are not both taken within 5s, the assert says so.
        deadline = time.monotonic() + 5
        while srv._slots._value > 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert srv._slots._value == 0, "both slots must be taken before the third is attempted"

        third = socket.create_connection((host, port), timeout=5)
        sockets.append(third)
        data = third.recv(4096)

        assert data == b"", "the third connection must be refused while 2 are already in flight"
    finally:
        for s in sockets:
            try:
                s.close()
            except OSError:
                pass
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
