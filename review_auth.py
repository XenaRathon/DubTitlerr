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


def scrypt_available() -> bool:
    try:
        hashlib.scrypt(b"probe", salt=b"0123456789abcdef", n=2, r=1, p=1, dklen=8)
        return True
    except (AttributeError, ValueError, OSError):
        return False


def _hash_with(password: str, n: int, r: int, p: int) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=_SCRYPT_MAXMEM)
    return f"scrypt${n}${r}${p}${salt.hex()}${dk.hex()}"


def hash_password(password: str) -> str:
    return _hash_with(password, SCRYPT_N, SCRYPT_R, SCRYPT_P)


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
    """What login verifies against when the username does not exist, so a miss takes as long as a wrong password.
    Made at import with the real cost pinned (not the patchable SCRYPT_* names), so the first miss is not slower and a
    test that lowers SCRYPT_N cannot leave a weak dummy behind."""
    return _DUMMY


_DUMMY = _hash_with(secrets.token_urlsafe(24), 2**14, 8, 1)


def validate_username(name) -> str | None:
    if not isinstance(name, str) or not _USERNAME.fullmatch(name):
        return "username must be 1 to 64 characters: letters, digits, '.', '_' or '-'"
    return None


def validate_password(password) -> str | None:
    if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        return f"password must be {MIN_PASSWORD} to {MAX_PASSWORD} characters"
    try:
        password.encode("utf-8")
    except UnicodeEncodeError:  # a lone surrogate from a JSON body would crash the hash
        return "password must be valid text"
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
        with contextlib.suppress(OSError):  # make the rename durable; a failure here must not undo a finished write
            dfd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    except OSError as e:
        if tmp:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
        raise Unavailable("the config volume is not writable") from e


def _write_json(path: str, doc: dict) -> None:
    _write_atomic(path, json.dumps(doc, indent=2) + "\n")


@contextlib.contextmanager
def _locked(path: str, wait: float | None = None):
    """The glossary lock helper on ``path`` (its own ``<path>.lock`` file, never a glossary's). Busy when it stays taken.
    Unavailable when the lock file cannot be opened: the helper would then run unlocked, and auth must never do that."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        os.close(os.open(glossary_lock.lock_path(path), os.O_RDWR | os.O_CREAT, 0o600))
    except OSError as e:
        raise Unavailable("the config volume is not writable") from e
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
    rows = doc.get("users") if isinstance(doc, dict) and doc.get("version") == 1 else None
    if not isinstance(rows, list) or not all(_valid_row(r) for r in rows):
        raise Unreadable(_UNREADABLE)
    if len({r["name"].lower() for r in rows}) != len(rows):
        raise Unreadable(_UNREADABLE)
    return rows


def _valid_row(r) -> bool:
    return (
        isinstance(r, dict)
        and validate_username(r.get("name")) is None
        and r.get("role") in ROLES
        and isinstance(r.get("hash"), str)
        and isinstance(r.get("session_epoch"), int)
        and not isinstance(r.get("session_epoch"), bool)
        and isinstance(r.get("pw_changed_at"), (int, float))
        and not isinstance(r.get("pw_changed_at"), bool)
    )


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


MAX_PER_ACCOUNT = 20
CLOCK_SKEW = 300.0  # a last_seen further ahead than this means the clock stepped; the session is no longer trusted


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _valid_session(r) -> bool:
    return (
        isinstance(r, dict)
        and isinstance(r.get("id_sha256"), str)
        and isinstance(r.get("name"), str)
        and _num(r.get("created"))
        and _num(r.get("last_seen"))
        and isinstance(r.get("remember"), bool)
        and (_num(r.get("epoch", 0)) and isinstance(r.get("epoch", 0), int))
    )


class SessionStore:
    """Sessions held in memory and mirrored to ``path`` as SHA-256 hashes of the ids; never the ids themselves.

    ``last_seen`` is set to now on every lookup and reaches the file at most every FLUSH_EVERY seconds. That flush
    runs in the request thread with a lock wait of zero: it never waits for the lock, but the write itself is
    synchronous disk I/O. A failed flush is logged, not raised. create() raises when the session could not be saved
    (a session that was not saved must not be handed out); revoke() and revoke_user() log a failed save and keep the
    change in memory. Every write takes its snapshot inside the file lock, so writes land in snapshot order."""

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
                doc = json.load(f)
            listed = doc.get("sessions") if isinstance(doc, dict) else None
            if not isinstance(listed, list):
                raise ValueError("no sessions list")
            for r in listed:
                if _valid_session(r):
                    r.setdefault("epoch", 0)
                    rows[r["id_sha256"]] = r
            if len(rows) != len(listed):
                log(f"review server: dropped {len(listed) - len(rows)} malformed session(s) from {self.path}")
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log(f"review server: sessions file unreadable ({e}); starting with no sessions, the next save replaces it")
        self._rows, self._flushed = rows, CLOCK()

    @staticmethod
    def _live(row: dict, now: float) -> bool:
        if row["last_seen"] - now > CLOCK_SKEW:  # the clock stepped back (or forward and was corrected)
            return False
        return now - row["last_seen"] <= (REMEMBER_SECONDS if row["remember"] else IDLE_SECONDS)

    def _snapshot(self, now: float) -> dict:  # caller holds _mu; prunes the expired
        for d in [d for d, r in self._rows.items() if not self._live(r, now)]:
            del self._rows[d]
            self._cookie_at.pop(d, None)
        return {"version": 1, "sessions": [dict(r) for r in self._rows.values()]}

    def _persist(self, wait: float, now: float) -> None:
        """Snapshot and write under the file lock, so a slower writer can never put an older list over a newer one."""
        with _locked(self.path, wait):
            with self._mu:
                doc = self._snapshot(now)
            _write_json(self.path, doc)

    def _persist_quietly(self, now: float) -> None:
        try:
            self._persist(LOCK_WAIT, now)
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
            mine = [d for d, r in self._rows.items() if r["name"].lower() == name.lower()]
            for d in sorted(mine, key=lambda d: self._rows[d]["created"])[: max(0, len(mine) - MAX_PER_ACCOUNT)]:
                del self._rows[d]
                self._cookie_at.pop(d, None)
        try:
            self._persist(LOCK_WAIT, now)
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
        digest, now, flush = _digest(sid), CLOCK(), False
        with self._mu:
            self._load()
            row = self._rows.get(digest)
            if row is None:
                return None
            if not self._live(row, now):
                del self._rows[digest]
                self._cookie_at.pop(digest, None)
                return None
            row["last_seen"] = now
            refresh = bool(row["remember"]) and now - self._cookie_at.get(digest, row["created"]) >= COOKIE_REFRESH_EVERY
            if refresh:
                self._cookie_at[digest] = now
            info = SessionInfo(row["name"], bool(row["remember"]), row.get("epoch", 0), refresh)
            if now - self._flushed >= FLUSH_EVERY:
                self._flushed = now  # also on failure: one attempt per interval
                flush = True
        if flush:
            try:
                self._persist(0.0, now)
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
