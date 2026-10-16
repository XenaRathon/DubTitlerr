"""A 127.0.0.1 JSON endpoint for tests that need a real socket. Synthetic data only."""

import http.server
import json
import threading


class FakeServer:
    """`reply(request) -> (status, body_dict_or_bytes)`; every request is kept in ``requests`` as
    {"path", "auth", "ua", "body"}. Replies are looked up per request so a test can script a sequence."""

    def __init__(self, reply):
        outer = self
        self.requests = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"null")
                req = {
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "ua": self.headers.get("User-Agent"),
                    "body": body,
                }
                outer.requests.append(req)
                status, payload = reply(req)
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"
        self.url = self.base + "/v1/chat/completions"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def chat_reply(content, **message):
    """A chat/completions body whose assistant message has this content."""
    return {"choices": [{"message": {"role": "assistant", "content": content, **message}, "finish_reason": "stop"}]}
