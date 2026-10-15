"""Accounts, sessions, the API key and the route-role table for the review server (specs/webui-login-roles).

Stdlib only: hashlib.scrypt for passwords, secrets for ids and keys. Nothing here imports review_server; the server
hands in the one thing it owns (the legacy review token) through set_token_fallback().
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import tempfile
import time

import glossary_lock
from common import log

CLOCK = time.time
LOCK_WAIT = 2.0

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024  # OpenSSL's default cap is 32 MiB; n=2^14, r=8 needs about 16 MiB
ROLES = ("admin", "user")
MIN_PASSWORD, MAX_PASSWORD = 10, 256
_USERNAME = re.compile(r"[A-Za-z0-9._-]{1,64}")
_DUMMY = None


def scrypt_available() -> bool:
    try:
        hashlib.scrypt(b"probe", salt=b"0123456789abcdef", n=2, r=1, p=1, dklen=8)
        return True
    except (AttributeError, ValueError, OSError):
        return False


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32, maxmem=_SCRYPT_MAXMEM)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password, stored) -> bool:
    """True when ``password`` matches ``stored``. Always costs one scrypt, also for a malformed hash or a non-string."""
    try:
        scheme, n, r, p, salt, dk = stored.split("$")
        if scheme != "scrypt":
            raise ValueError("not a scrypt hash")
        want = bytes.fromhex(dk)
        got = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(want),
            maxmem=_SCRYPT_MAXMEM,
        )
        return secrets.compare_digest(got, want)
    except (ValueError, AttributeError, TypeError):
        hashlib.scrypt(b"x", salt=b"0123456789abcdef", n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32, maxmem=_SCRYPT_MAXMEM)
        return False


def dummy_hash() -> str:
    """What login verifies against when the username does not exist, so a miss takes as long as a wrong password."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password(secrets.token_urlsafe(24))
    return _DUMMY


def validate_username(name) -> str | None:
    if not isinstance(name, str) or not _USERNAME.fullmatch(name):
        return "username must be 1 to 64 characters: letters, digits, '.', '_' or '-'"
    return None


def validate_password(password) -> str | None:
    if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        return f"password must be {MIN_PASSWORD} to {MAX_PASSWORD} characters"
    return None


class AuthError(Exception):
    status = 500

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class Invalid(AuthError):
    status = 400


class Forbidden(AuthError):
    status = 403


class NotFound(AuthError):
    status = 404


class Conflict(AuthError):
    status = 409


class Busy(AuthError):
    status = 503


class Unavailable(AuthError):
    status = 503


class Unreadable(AuthError):
    status = 503


_UNREADABLE = "accounts file unreadable; recover with: python3 review_users.py reset-admin <name>"


def config_dir() -> str:
    return os.environ.get("CONFIG_DIR") or "/config"


def users_path() -> str:
    return os.path.join(config_dir(), "users.json")


def _write_atomic(path: str, text: str) -> None:
    """Temp file in the same directory, fsync, 0600, then os.replace: a reader sees the old file or the new one, never half."""
    tmp = None
    try:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=os.path.basename(path) + ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError as e:
        if tmp:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
        raise Unavailable("the config volume is not writable") from e


def _write_json(path: str, doc: dict) -> None:
    _write_atomic(path, json.dumps(doc, indent=2) + "\n")


@contextlib.contextmanager
def _locked(path: str, wait: float | None = None):
    """The glossary lock helper on ``path`` (its own ``<path>.lock`` file, never a glossary's). Busy when it stays taken."""
    with glossary_lock.locked(path, "review_auth", wait=LOCK_WAIT if wait is None else wait) as got:
        if not got:
            raise Busy("busy, try again")
        yield


def read_users() -> list:
    try:
        with open(users_path(), encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise Unreadable(_UNREADABLE) from e
    rows = doc.get("users") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not all(
        isinstance(r, dict) and isinstance(r.get("name"), str) and r.get("role") in ROLES and isinstance(r.get("hash"), str)
        for r in rows
    ):
        raise Unreadable(_UNREADABLE)
    return rows


def setup_required() -> bool:
    """True when the accounts file is readable and empty. A corrupt file is NOT first run."""
    try:
        return not read_users()
    except Unreadable:
        return False


def find_user(users: list, name) -> dict | None:
    if not isinstance(name, str):
        return None
    wanted = name.lower()
    return next((u for u in users if u["name"].lower() == wanted), None)


def create_user(name, role, password, *, only_if_empty: bool = False) -> dict:
    problem = validate_username(name) or validate_password(password)
    if problem:
        raise Invalid(problem)
    if role not in ROLES:
        raise Invalid("role must be admin or user")
    stored = hash_password(password)  # the slow part stays outside the lock
    with _locked(users_path()):
        users = read_users()
        if only_if_empty and users:
            raise Conflict("already set up")
        if find_user(users, name):
            raise Conflict("username taken")
        users.append({"name": name, "role": role, "hash": stored, "pw_changed_at": CLOCK(), "session_epoch": 0})
        _write_json(users_path(), {"version": 1, "users": users})
    log(f"review server: account created ({role})")
    return {"name": name, "role": role}
