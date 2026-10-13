"""Admin token for builder-affecting writes (specs/webui-admin-token).

Second, header-only secret in front of the routes that affect the builder
(settings writes, run requests, schedule). The review token stays the gate
for everything else. Unset means writes are disabled, never open.
"""

import os
import secrets


def admin_token(environ=None) -> str:
    """The admin token: REVIEW_ADMIN_TOKEN, else the file named by REVIEW_ADMIN_TOKEN_FILE.

    File contents are stripped of surrounding whitespace; "" when unset, empty, or unreadable.
    The value is never logged here.
    """
    env = os.environ if environ is None else environ
    get = env.get if hasattr(env, "get") else None
    direct = (get("REVIEW_ADMIN_TOKEN") or "").strip() if get else ""
    if direct:
        return direct
    path = get("REVIEW_ADMIN_TOKEN_FILE") if get else None
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read(4096).strip()  # a FIFO or huge file must not block or exhaust memory on every check
    except OSError:
        return ""


def admin_enabled(environ=None) -> bool:
    """True when an admin token is configured (writes possible)."""
    return bool(admin_token(environ))


def check_admin(presented, environ=None):
    """None when allowed; (403, payload) when disabled, missing, or wrong.

    Disabled (no token configured) reports "admin writes are disabled" so a
    deployment that never set one does not look like a wrong-token retry.
    """
    expected = admin_token(environ)
    if not expected:
        return 403, {"error": "admin writes are disabled"}
    # A non-string is wrong by definition: str() would let the integer 1234 match the token "1234".
    if not isinstance(presented, str) or not presented:
        return 403, {"error": "admin token required"}
    # compare_digest on UTF-8 bytes, not ==: timing-safe, and one path for ASCII and non-ASCII alike
    # (str compare_digest raises TypeError on non-ASCII, and catching it would time differently).
    ok = secrets.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))
    if ok:
        return None
    return 403, {"error": "admin token required"}
