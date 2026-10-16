"""Settings page probes (specs/webui-settings): read the builder's effective.env, and probe a backend with a strict timeout.

The settings API itself (schema, values, writes) is settings_api.py. This module keeps what is not about stored settings: the
effective.env reader, the connectivity probe every Test button uses, and the probe of a stage that is still configured from the
container environment (POST /api/settings/test with {"backend": "repair" | "verify" | "acquire"}).

Error text can never carry a key or a URL query. handle() expects an already-authorised call."""

import errno
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request


def get_effective_env_path(env: dict | None = None) -> str:
    source = env if env is not None else os.environ
    if source.get("EFFECTIVE_ENV_FILE"):
        return source["EFFECTIVE_ENV_FILE"]
    if source.get("CONFIG_DIR"):
        return os.path.join(source["CONFIG_DIR"], "effective.env")
    return EFFECTIVE_ENV_PATH


EFFECTIVE_ENV_PATH = os.environ.get("EFFECTIVE_ENV_FILE") or os.path.join(
    os.environ.get("CONFIG_DIR", "/config"), "effective.env"
)

_TEST_BACKENDS = ("repair", "verify", "acquire")
_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def read_effective_env(path: str | None = None) -> dict:
    """Parse KEY=VALUE lines; ignore blanks, full-line comments, and bad lines; {} if unreadable.

    No shell expansion. A leading `export ` and matched surrounding quotes are stripped.
    """
    target = path or get_effective_env_path()
    out = {}
    try:
        with open(target, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not _KEY_RE.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out


def _merged(environ, effective: dict) -> dict:
    """One lookup mapping; a key present in effective.env wins over the process env."""
    merged = dict(environ)
    merged.update(effective)
    return merged


def _sanitize(text, key: str = "", url: str = "") -> str:
    """Scrub a key value, userinfo, and any URL query out of error text; keep it short."""
    out = str(text or "")
    if key:
        out = out.replace(key, "[redacted]")
    if url:
        try:
            parts = urllib.parse.urlsplit(url)
            if parts.password:
                out = out.replace(parts.password, "[redacted]")
            if parts.username:
                out = out.replace(parts.username, "[redacted]")
            if parts.netloc and "@" in parts.netloc:
                userinfo = parts.netloc.rsplit("@", 1)[0]
                out = out.replace(userinfo, "[redacted]")
            if parts.query:
                out = out.replace(parts.query, "[redacted]")
        except Exception:
            pass
    out = re.sub(r"://[^:/@]+:[^@]+@", "://[redacted]:[redacted]@", out)
    return out[:200]


def _resolve_backend(name: str, env: dict):
    """(kind, base_url, key_env_pointer) for a test name, or None when unknown.

    kind is "openai" (GET <base>/v1/models with a Bearer key) or "plain" (a bare
    reachability GET). Acquire has no hosted endpoint of its own, so openai shares
    verify's URL/key and anything else shares verify's llamacpp URL.
    """
    get = lambda n: (env.get(n) or "").strip()  # noqa: E731 -- one tiny local lookup
    if name == "repair":
        kind = get("REPAIR_BACKEND").lower() or "llamacpp"
        if kind == "openai":
            return ("openai", get("REPAIR_OPENAI_URL"), "REPAIR_OPENAI_KEY_ENV")
        return ("plain", get("REPAIR_LLAMACPP_URL"), None)
    if name == "verify":
        kind = get("VERIFY_BACKEND").lower() or "llamacpp"
        if kind == "openai":
            return ("openai", get("VERIFY_OPENAI_URL"), "VERIFY_OPENAI_KEY_ENV")
        if kind == "decision":
            return ("plain", get("VERIFY_DECISION_URL"), None)
        return ("plain", get("VERIFY_LLAMACPP_URL"), None)
    if name == "acquire":
        kind = (get("ACQUIRE_BACKEND") or get("VERIFY_BACKEND")).lower() or "llamacpp"
        if kind == "openai":
            return ("openai", get("VERIFY_OPENAI_URL"), "VERIFY_OPENAI_KEY_ENV")
        if kind == "decision":
            return ("plain", get("VERIFY_DECISION_URL"), None)
        return ("plain", get("VERIFY_LLAMACPP_URL"), None)
    return None


def test_backend(name: str, environ=None, opener=None, timeout: float = 5.0) -> dict:
    """Probe one backend: {"ok": bool, "latency_ms": int, "error": str}.

    The key (read at call time from the var named by the *_KEY_ENV pointer) travels
    in the Authorization header only. Failures map to ok:false with a short error
    that can never carry the key or a URL query.
    """
    env = os.environ if environ is None else environ
    resolved = _resolve_backend(name, env)
    if resolved is None:
        return {"ok": False, "latency_ms": 0, "error": "unsupported backend"}
    kind, base, key_pointer = resolved
    if not base:
        return {"ok": False, "latency_ms": 0, "error": "no endpoint configured"}
    key = ""
    if kind == "openai":
        key_name = (env.get(key_pointer) or "").strip()
        key = (env.get(key_name) or "").strip() if key_name else ""
        if not key:
            return {"ok": False, "latency_ms": 0, "error": "API key not configured"}
        url = base.rstrip("/") + "/v1/models"
        headers = {"Authorization": f"Bearer {key}"}
    else:
        url, headers = base, {}
    return probe(url, headers, key, timeout, opener)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _no_redirect_opener():
    return urllib.request.build_opener(_NoRedirectHandler).open


def probe(url, headers, key="", timeout=5.0, opener=None):
    """GET ``url`` and map the outcome to {"ok", "latency_ms", "error"}. The error text can never carry the key or a URL query."""
    opener = _no_redirect_opener() if opener is None else opener
    display = url.split("?", 1)[0]
    try:
        request = urllib.request.Request(display, headers=headers or {}, method="GET")
        start = time.monotonic()
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            response.read()
        latency_ms = int((time.monotonic() - start) * 1000)
    except urllib.error.HTTPError as e:
        return {"ok": False, "latency_ms": 0, "error": f"HTTP {e.code}"}
    except TimeoutError:
        return {"ok": False, "latency_ms": 0, "error": "timed out"}
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, TimeoutError):
            return {"ok": False, "latency_ms": 0, "error": "timed out"}
        if isinstance(reason, ConnectionRefusedError) or (isinstance(reason, OSError) and reason.errno == errno.ECONNREFUSED):
            return {"ok": False, "latency_ms": 0, "error": "connection refused"}
        return {"ok": False, "latency_ms": 0, "error": _sanitize(f"connection failed: {reason}", key, url)}
    except OSError as e:
        if isinstance(e, ConnectionRefusedError) or e.errno == errno.ECONNREFUSED:
            return {"ok": False, "latency_ms": 0, "error": "connection refused"}
        return {"ok": False, "latency_ms": 0, "error": _sanitize(type(e).__name__, key, url)}
    except Exception as e:  # a fake opener may raise anything; never let text through raw
        return {"ok": False, "latency_ms": 0, "error": _sanitize(type(e).__name__, key, url)}
    if 200 <= status < 300:
        return {"ok": True, "latency_ms": latency_ms, "error": ""}
    return {"ok": False, "latency_ms": latency_ms, "error": f"HTTP {status}"}


def handle(method, path, body=None, token=None, environ=None, opener=None) -> tuple:
    """POST /api/settings/test for an environment-configured stage; 404 otherwise. The settings read is settings_api.py."""
    env = os.environ if environ is None else environ
    eff_path = get_effective_env_path(env)
    route = (path or "").split("?", 1)[0]
    if method == "POST" and route == "/api/settings/test":
        name = body.get("backend") if isinstance(body, dict) else None
        if not name:
            return 400, {"error": "backend is required"}
        if name not in _TEST_BACKENDS:
            return 400, {"error": "unsupported backend"}
        merged = _merged(env, read_effective_env(eff_path))
        return 200, test_backend(name, merged, opener=opener)
    return 404, {"error": "no such route"}
