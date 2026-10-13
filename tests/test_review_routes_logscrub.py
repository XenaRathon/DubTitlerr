"""Access-log lines must never carry a query string: ?token= (webhooks) would otherwise reach the log."""

import http.client
import json
import threading

import review_server as rs

SECRET = "s3cret-webhook-token"


class FakeHandler:
    """log_message uses nothing from self beyond the base class's formatting, which it receives as arguments."""


def test_log_message_hides_the_query_string(capsys):
    rs.Handler.log_message(FakeHandler(), '"%s" %s %s', f"POST /api/webhook/sonarr?token={SECRET} HTTP/1.1", "200", "-")
    out = capsys.readouterr().out
    assert SECRET not in out
    assert "/api/webhook/sonarr" in out and "200" in out, "the route and status stay in the log"


def test_other_log_lines_pass_through_untouched(capsys):
    rs.Handler.log_message(FakeHandler(), "code %d, message %s", 400, "Bad request syntax ('x?y')")
    assert "Bad request syntax ('x?y')" in capsys.readouterr().out


def test_every_method_and_a_malformed_line_are_scrubbed(capsys):
    for line in (
        f"GET /api/status?token={SECRET}&show=x HTTP/1.1",
        f"PUT /api/schedule?token={SECRET} HTTP/1.1",
        f"GET /api/audio?stem=a&token={SECRET}",
    ):
        rs.Handler.log_message(FakeHandler(), '"%s" %s %s', line, "200", "-")
    assert SECRET not in capsys.readouterr().out


def test_a_real_request_with_a_token_in_the_query_logs_without_it(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("REVIEW_TOKEN", "review-token")
    monkeypatch.setenv("WEBHOOK_TOKEN", SECRET)
    monkeypatch.setattr(rs, "_LOGIN", None)
    srv = rs.BoundedHTTPServer(("127.0.0.1", 0), rs.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection(*srv.server_address, timeout=5)
        conn.request("POST", f"/api/webhook/sonarr?token={SECRET}", body=json.dumps({"eventType": "Test"}))
        assert conn.getresponse().status == 200
        conn.close()
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
    out = capsys.readouterr().out
    assert "/api/webhook/sonarr" in out, "the request was logged"
    assert SECRET not in out


# --- any method token, any case, every request line -------------------------------------------------------------------


import pytest  # noqa: E402


@pytest.mark.parametrize(
    "line",
    [
        f"PROPFIND /dav/x?token={SECRET} HTTP/1.1",
        f"get /api/status?token={SECRET} HTTP/1.1",
        f"Patch /api/glossary?token={SECRET}&x=1 HTTP/1.1",
        f"M-SEARCH /x?token={SECRET} HTTP/1.0",
        f"GET http://example.test/api/status?token={SECRET} HTTP/1.1",
        f"GET /a%20b?token={SECRET}#frag HTTP/1.1",
        f"GET /api/x?a=1?token={SECRET} HTTP/1.1",
    ],
    ids=["PROPFIND", "lowercase", "mixed-case", "hyphenated", "absolute-form", "encoded", "double-question"],
)
def test_the_query_is_scrubbed_whatever_the_method(capsys, line):
    rs.Handler.log_message(FakeHandler(), '"%s" %s %s', line, "200", "-")
    out = capsys.readouterr().out
    assert SECRET not in out
    assert "?[query hidden]" in out


def test_a_request_line_without_a_query_is_left_alone(capsys):
    rs.Handler.log_message(FakeHandler(), '"%s" %s %s', "PROPFIND /dav/x HTTP/1.1", "200", "-")
    assert "PROPFIND /dav/x HTTP/1.1" in capsys.readouterr().out


def test_an_empty_query_is_scrubbed_too(capsys):
    rs.Handler.log_message(FakeHandler(), '"%s" %s %s', "GET /x? HTTP/1.1", "200", "-")
    assert "GET /x?[query hidden] HTTP/1.1" in capsys.readouterr().out


def test_a_question_mark_in_plain_log_text_is_not_touched(capsys):
    rs.Handler.log_message(FakeHandler(), "code %d, message %s", 400, "Bad request syntax ('what?now')")
    assert "what?now" in capsys.readouterr().out
