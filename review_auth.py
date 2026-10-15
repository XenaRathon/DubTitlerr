"""Accounts, sessions, the API key and the route-role table for the review server (specs/webui-login-roles).

Stdlib only: hashlib.scrypt for passwords, secrets for ids and keys. Nothing here imports review_server; the server
hands in the one thing it owns (the legacy review token) through set_token_fallback().
"""

from __future__ import annotations

import collections
import contextlib
import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
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
    except (ValueError, AttributeError, TypeError, OverflowError):
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


REMEMBER_SECONDS = 30 * 86400
IDLE_SECONDS = 12 * 3600
FLUSH_EVERY = 600.0
COOKIE_REFRESH_EVERY = 86400.0
SessionInfo = collections.namedtuple("SessionInfo", "name remember epoch refresh")


def _digest(sid: str) -> str:
    return hashlib.sha256(sid.encode("utf-8")).hexdigest()


class SessionStore:
    """Sessions held in memory and mirrored to ``path`` as SHA-256 hashes of the ids; never the ids themselves.

    ``last_seen`` slides in memory on every lookup and reaches the file at most every FLUSH_EVERY seconds, with a lock
    wait of zero, so a request never waits on the disk and a failed flush is logged, not raised. create() and
    revoke_user() persist for real: a session that was not saved must not be handed out."""

    def __init__(self, path: str):
        self.path = path
        self._mu = threading.Lock()
        self._rows = None  # id_sha256 -> row; loaded on first use
        self._cookie_at = {}  # id_sha256 -> when the cookie was last (re)issued; memory only
        self._flushed = 0.0

    def _load(self) -> None:  # caller holds _mu
        if self._rows is not None:
            return
        rows = {}
        try:
            with open(self.path, encoding="utf-8") as f:
                for r in json.load(f).get("sessions", []):
                    if isinstance(r, dict) and {"id_sha256", "name", "created", "last_seen", "remember"} <= set(r):
                        r.setdefault("epoch", 0)
                        rows[r["id_sha256"]] = r
        except (OSError, ValueError, AttributeError):
            rows = {}
        self._rows, self._flushed = rows, CLOCK()

    @staticmethod
    def _live(row: dict, now: float) -> bool:
        idle = max(0.0, now - row["last_seen"])  # a clock that stepped back never extends or kills a session
        return idle <= (REMEMBER_SECONDS if row["remember"] else IDLE_SECONDS)

    def _snapshot(self, now: float) -> dict:  # caller holds _mu; prunes the expired
        for d in [d for d, r in self._rows.items() if not self._live(r, now)]:
            del self._rows[d]
            self._cookie_at.pop(d, None)
        return {"version": 1, "sessions": [dict(r) for r in self._rows.values()]}

    def _persist(self, doc: dict, wait: float) -> None:
        with _locked(self.path, wait):
            _write_json(self.path, doc)

    def _persist_quietly(self, now: float) -> None:
        with self._mu:
            doc = self._snapshot(now)
        try:
            self._persist(doc, LOCK_WAIT)
        except AuthError as e:
            log(f"review server: could not save the session list ({e.message}); the change holds in memory")

    def create(self, name: str, remember: bool, epoch: int = 0) -> str:
        sid = secrets.token_urlsafe(32)
        now = CLOCK()
        row = {
            "id_sha256": _digest(sid),
            "name": name,
            "created": now,
            "last_seen": now,
            "remember": bool(remember),
            "epoch": int(epoch),
        }
        with self._mu:
            self._load()
            self._rows[row["id_sha256"]] = row
            self._cookie_at[row["id_sha256"]] = now
            doc = self._snapshot(now)
        try:
            self._persist(doc, LOCK_WAIT)
        except AuthError:
            with self._mu:
                self._rows.pop(row["id_sha256"], None)
                self._cookie_at.pop(row["id_sha256"], None)
            raise
        with self._mu:
            self._flushed = now
        return sid

    def lookup(self, sid) -> SessionInfo | None:
        if not isinstance(sid, str) or not sid:
            return None
        digest, now, doc = _digest(sid), CLOCK(), None
        with self._mu:
            self._load()
            row = self._rows.get(digest)
            if row is None or not secrets.compare_digest(row["id_sha256"], digest):
                return None
            if not self._live(row, now):
                del self._rows[digest]
                self._cookie_at.pop(digest, None)
                return None
            row["last_seen"] = max(row["last_seen"], now)
            refresh = bool(row["remember"]) and now - self._cookie_at.get(digest, row["created"]) >= COOKIE_REFRESH_EVERY
            if refresh:
                self._cookie_at[digest] = now
            info = SessionInfo(row["name"], bool(row["remember"]), row.get("epoch", 0), refresh)
            if now - self._flushed >= FLUSH_EVERY:
                self._flushed = now  # also on failure: one attempt per interval
                doc = self._snapshot(now)
        if doc is not None:
            try:
                self._persist(doc, 0.0)
            except AuthError as e:
                log(f"review server: could not flush sessions ({e.message}); keeping them in memory")
        return info

    def revoke(self, sid) -> None:
        if not isinstance(sid, str) or not sid:
            return
        with self._mu:
            self._load()
            self._rows.pop(_digest(sid), None)
            self._cookie_at.pop(_digest(sid), None)
        self._persist_quietly(CLOCK())

    def revoke_user(self, name: str, keep_sid: str | None = None) -> int:
        keep = _digest(keep_sid) if keep_sid else None
        with self._mu:
            self._load()
            gone = [d for d, r in self._rows.items() if r["name"].lower() == str(name).lower() and d != keep]
            for d in gone:
                del self._rows[d]
                self._cookie_at.pop(d, None)
        if gone:
            self._persist_quietly(CLOCK())
        return len(gone)


_STORES: dict = {}
_STORES_MU = threading.Lock()


def sessions() -> SessionStore:
    path = os.path.join(config_dir(), "sessions.json")
    with _STORES_MU:
        if path not in _STORES:
            _STORES[path] = SessionStore(path)
        return _STORES[path]
