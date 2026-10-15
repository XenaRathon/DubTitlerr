"""Accounts, sessions, the API key and the route-role table for the review server (specs/webui-login-roles).

Stdlib only: hashlib.scrypt for passwords, secrets for ids and keys. Nothing here imports review_server; the server
hands in the one thing it owns (the legacy review token) through set_token_fallback().
"""

from __future__ import annotations

import collections
import contextlib
import dataclasses
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
    global _DUMMY
    if _DUMMY is None:  # only after something cleared it; startup_auth calls this so it is never first-login work
        _DUMMY = _hash_with(secrets.token_urlsafe(24), 2**14, 8, 1)
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


def _no_token() -> str:
    return ""


_TOKEN_FALLBACK = _no_token


def set_token_fallback(fn) -> None:
    """review_server hands in resolve_token: the 0.2.x review token is the API key until a key file exists."""
    global _TOKEN_FALLBACK
    _TOKEN_FALLBACK = fn


def apikey_path() -> str:
    return os.path.join(config_dir(), "apikey")


def _retired_path() -> str:
    return os.path.join(config_dir(), "apikey.retired")


_KEY_STORED: set = set()  # key-file paths this process has seen stored; the marker file remembers it for later processes
_KEY_ERR_LOGGED: set = set()


def _key_file() -> tuple:
    """("ok", key) | ("missing", "") | ("error", ""). Only a missing file may fall back to the old review token; an
    unreadable or empty one fails closed with one log line, so a permissions slip can never revive a retired token."""
    path = apikey_path()
    try:
        with open(path, encoding="utf-8") as f:
            key = f.read().strip()
    except FileNotFoundError:
        return "missing", ""
    except (OSError, ValueError) as e:
        if path not in _KEY_ERR_LOGGED:
            _KEY_ERR_LOGGED.add(path)
            log(f"review server: API key file unreadable ({type(e).__name__}); no key is accepted until it is fixed or reset")
        return "error", ""
    if not key:
        if path not in _KEY_ERR_LOGGED:
            _KEY_ERR_LOGGED.add(path)
            log("review server: API key file unreadable (empty); no key is accepted until it is fixed or reset")
        return "error", ""
    _KEY_ERR_LOGGED.discard(path)
    _KEY_STORED.add(path)
    return "ok", key


def _read_key_file() -> str:
    return _key_file()[1]


def _legacy_allowed() -> bool:
    """The 0.2.x review token may stand in as the key only until a key file has ever been stored."""
    return apikey_path() not in _KEY_STORED and not os.path.exists(_retired_path())


def api_key() -> str:
    state, key = _key_file()
    if state == "ok":
        return key
    return _TOKEN_FALLBACK() if state == "missing" and _legacy_allowed() else ""


def key_matches(presented) -> bool:
    expected = api_key()
    if not expected or not isinstance(presented, str) or not presented:
        return False
    try:
        return secrets.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))
    except UnicodeEncodeError:  # a lone surrogate cannot be the key
        return False


def _warn_if_env_token_differs() -> None:
    """The key file outranks REVIEW_TOKEN once it exists, so a token rotated in the compose file would silently not apply.
    Said once per start, without either value."""
    env, stored = os.environ.get("REVIEW_TOKEN", ""), _read_key_file()
    if env and stored and not secrets.compare_digest(env.encode("utf-8"), stored.encode("utf-8")):
        log("review server: REVIEW_TOKEN differs from the stored API key and is ignored; reset the key in Settings, Security")


def _store_key(key: str) -> None:
    """Caller holds the lock. Writes the key, then a marker that retires the old review token for good."""
    _write_atomic(apikey_path(), key + "\n")
    _KEY_STORED.add(apikey_path())
    _write_atomic(_retired_path(), "the 0.2.x review token no longer stands in for the API key\n")


def init_api_key() -> None:
    """On upgrade the existing review token becomes the API key, so scripts that hold it keep working (S-6). Only the
    first time: once a key file has been stored, a lost file gets a fresh random key, never the old token again."""
    state, _ = _key_file()
    if state == "ok":
        _warn_if_env_token_differs()
        return
    if state == "error":
        return  # an unreadable key file is not ours to overwrite; reset replaces it
    key = (_TOKEN_FALLBACK() if _legacy_allowed() else "") or secrets.token_urlsafe(32)
    try:
        with _locked(apikey_path()):
            if _key_file()[0] != "missing":
                return
            _store_key(key)
        log(f"review server: API key stored in {apikey_path()} (0600)")
    except AuthError as e:
        log(f"review server: could not store the API key ({e.message}); until then the review token, if set, stays the key")


def reset_api_key() -> str:
    key = secrets.token_urlsafe(32)
    with _locked(apikey_path()):
        _store_key(key)
    log("review server: API key reset")
    return key


SESSION_COOKIE = "dubtitlerr_session"
LEGACY_COOKIE = "dubtitlerr_token"
API_KEY_HEADER = "X-Api-Key"
ALIAS_HEADER = "X-Review-Token"
CSRF_HEADER = "X-DubTitlerr-Request"

ROUTE_ROLES: dict[tuple[str, str], str] = {}
_ROLE_VALUES = ("public", "user", "admin")
_ERRORS = {401: "login required", 403: "admin only", 409: "setup required"}


def register_routes(entries: dict) -> None:
    """Add routes to the role table. Validates every entry first, so a bad one adds none of them."""
    for (method, path), role in entries.items():
        if role not in _ROLE_VALUES:
            raise ValueError(f"unknown role {role!r} for {method} {path}")
        if ROUTE_ROLES.get((method, path), role) != role:
            raise ValueError(f"{method} {path} is already registered as {ROUTE_ROLES[(method, path)]}")
    ROUTE_ROLES.update(entries)


register_routes(
    {
        ("GET", "/healthz"): "public",
        ("GET", "/api/auth-mode"): "public",
        ("POST", "/api/login"): "public",
        ("POST", "/api/setup"): "public",
        ("GET", "/review"): "public",
        ("GET", "/review/*"): "public",
        ("POST", "/api/webhook/sonarr"): "public",  # these two carry their own secret in the URL (decided 2026-10-13)
        ("POST", "/api/webhook/radarr"): "public",
        ("GET", "/"): "user",  # the classic pages; Handler.do_GET asks role_for before it renders them
        ("GET", "/index.html"): "user",
        ("GET", "/shared"): "user",
        ("GET", "/api/audio"): "user",
        ("GET", "/api/episodes"): "user",
        ("GET", "/api/shows"): "user",
        ("GET", "/api/episode"): "user",
        ("POST", "/api/decide"): "user",
        ("GET", "/api/shared"): "user",
        ("POST", "/api/shared"): "user",
        ("POST", "/api/apply"): "user",
        ("GET", "/api/requests"): "user",
        ("GET", "/api/schedule"): "user",
        ("GET", "/api/settings"): "user",
        ("GET", "/api/settings/schema"): "user",
        ("GET", "/api/status"): "user",
        ("GET", "/api/glossary"): "user",
        ("POST", "/api/glossary"): "user",
        ("GET", "/api/me"): "user",
        ("PUT", "/api/me/password"): "user",
        ("POST", "/api/logout"): "user",
        ("POST", "/api/requests"): "admin",
        ("PUT", "/api/schedule"): "admin",
        ("PUT", "/api/settings"): "admin",
        ("POST", "/api/settings/reset"): "admin",
        ("POST", "/api/settings/test"): "admin",
        ("POST", "/api/system/restart"): "admin",
        ("GET", "/api/apikey"): "admin",
        ("POST", "/api/apikey/reset"): "admin",
        ("GET", "/api/users"): "admin",
        ("POST", "/api/users"): "admin",
        ("PUT", "/api/users/*"): "admin",
        ("DELETE", "/api/users/*"): "admin",
    }
)


def _required_role(method: str, path: str) -> tuple:
    """(role the route needs, whether the table lists it). An exact entry wins, then the longest ``prefix/*``; an unlisted
    route needs admin, so a route someone forgot to list is closed rather than open."""
    exact = ROUTE_ROLES.get((method, path))
    if exact is not None:
        return exact, True
    best, found = "", "admin"
    for (m, pattern), role in ROUTE_ROLES.items():
        if m == method and pattern.endswith("/*") and path.startswith(pattern[:-1]) and len(pattern) > len(best):
            best, found = pattern, role
    return (found, True) if best else ("admin", False)


def header(headers, name: str) -> str:
    """One request header, whatever the case the client sent, from a dict or an http message; "" when absent."""
    if headers is None or not hasattr(headers, "items"):
        return ""
    wanted = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == wanted:
            return value or ""
    return ""


def _cookie(headers, name: str) -> str:
    raw = header(headers, "Cookie")
    if not raw:
        return ""
    # Not SimpleCookie: one malformed cookie from another app on this host would make it drop ours too.
    for part in raw.split(";"):
        key, sep, value = part.partition("=")
        if sep and key.strip() == name:
            value = value.strip()
            return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value
    return ""


def auth_on() -> bool:
    """False only for REVIEW_AUTH=off, as before."""
    return os.environ.get("REVIEW_AUTH", "") != "off"


@dataclasses.dataclass(frozen=True)
class Principal:
    kind: str  # "key" | "alias" | "session" | "open"
    name: str
    role: str
    sid: str = ""
    refresh: bool = False
    remember: bool = False


@dataclasses.dataclass(frozen=True)
class Decision:
    role: str | None
    status: int | None
    error: str
    required: str
    known: bool
    principal: Principal | None


_ALIAS_LOGGED = False


def _note_alias() -> None:
    global _ALIAS_LOGGED
    if not _ALIAS_LOGGED:
        _ALIAS_LOGGED = True
        log("review server: X-Review-Token is deprecated; it works as an alias of X-Api-Key for this release only")


_PAGE_PATHS = ("/", "/index.html", "/shared")


def _session_principal(headers) -> Principal | None:
    sid = _cookie(headers, SESSION_COOKIE)
    info = sessions().lookup(sid) if sid else None
    if info is None:
        return None
    try:
        row = find_user(read_users(), info.name)
    except Unreadable:
        return None
    if row is None or info.epoch != int(row.get("session_epoch", 0)):
        return None  # deleted, or the password or role changed after this login (possibly from another process)
    return Principal("session", row["name"], row["role"], sid=sid, refresh=info.refresh, remember=info.remember)


def authenticate(headers, method: str = "GET", path: str = "") -> Principal | None:
    """Who is asking. X-Api-Key decides when present, right or wrong. Otherwise a valid session wins over the legacy token,
    so a stale token header or cookie can neither raise a user to admin nor lock a signed-in browser out. The alias header
    works on every route for this release; the legacy token COOKIE authenticates the classic page routes only, never /api/*."""
    presented = header(headers, API_KEY_HEADER)
    if presented:
        return Principal("key", "api key", "admin") if key_matches(presented) else None
    principal = _session_principal(headers)
    if principal is not None:
        return principal
    presented = header(headers, ALIAS_HEADER)
    if presented:
        if not key_matches(presented):
            return None
        _note_alias()
        return Principal("alias", "api key", "admin")
    if method in ("GET", "HEAD") and path in _PAGE_PATHS:
        legacy = _cookie(headers, LEGACY_COOKIE)
        if legacy and key_matches(legacy):
            _note_alias()
            return Principal("alias", "api key", "admin")
    return None


def _refuse(status: int, required: str, known: bool, error: str = "") -> Decision:
    return Decision(None, status, error or _ERRORS[status], required, known, None)


_NO_PRINCIPAL_PREFIXES = ("/healthz", "/review", "/api/webhook/")  # public routes that never read who is asking


def decide(method: str, path: str, headers) -> Decision:
    path = path.split("?", 1)[0].split("#", 1)[0]  # the table knows routes, not query strings
    required, known = _required_role(method, path)
    if not auth_on():
        return Decision("admin", None, "", required, known, Principal("open", "", "admin"))
    if required == "public" and path.startswith(_NO_PRINCIPAL_PREFIXES):
        return Decision("public", None, "", required, known, None)
    principal = authenticate(headers, method, path)
    if required == "public":
        return Decision(principal.role if principal else "public", None, "", required, known, principal)
    if principal is None:
        if header(headers, API_KEY_HEADER) or header(headers, ALIAS_HEADER):
            return _refuse(401, required, known)
        return _refuse(409 if setup_required() else 401, required, known)
    if required == "admin" and principal.role != "admin":
        return _refuse(403, required, known)
    return Decision(principal.role, None, "", required, known, principal)


def role_for(method: str, path: str, headers) -> tuple:
    d = decide(method, path, headers)
    return d.role, d.status


def handle_setup(body) -> tuple:
    """POST /api/setup: create the first admin, only while no account exists. The lock makes a second browser lose with 409."""
    body = body if isinstance(body, dict) else {}
    try:
        if read_users():  # answered before any hashing: this route is public and unthrottled, so a refusal must be cheap
            return 409, {"error": "already set up"}
    except Unreadable as e:
        return e.status, {"error": e.message}
    try:
        row = create_user(body.get("username"), "admin", body.get("password"), only_if_empty=True)
    except AuthError as e:
        return e.status, {"error": e.message}
    log("review server: first admin account created through setup")
    return 200, {"username": row["name"], "role": "admin"}


def import_env_admin(env=None) -> bool:
    """With no accounts yet, turn REVIEW_USERNAME plus REVIEW_PASSWORD (or REVIEW_PASSWORD_FILE, read once, one trailing
    newline stripped) into the first admin, once, so an upgrade skips the setup page. Never logs the password."""
    env = os.environ if env is None else env
    user, password, pw_file = env.get("REVIEW_USERNAME"), env.get("REVIEW_PASSWORD"), env.get("REVIEW_PASSWORD_FILE")
    if not user and not password and not pw_file:
        return False
    try:
        if read_users():
            return False
    except Unreadable:
        log("review server: REVIEW_USERNAME not imported: the accounts file is unreadable")
        return False
    source = "REVIEW_PASSWORD"
    if pw_file:
        try:
            with open(pw_file, "rb") as f:
                raw = f.read(4096).decode("utf-8")
        except OSError as e:
            log(f"review server: REVIEW_PASSWORD_FILE unreadable ({e.__class__.__name__}); nothing imported, use the setup page")
            return False
        except UnicodeDecodeError:
            log("review server: REVIEW_PASSWORD_FILE is not valid UTF-8, nothing imported; use the setup page")
            return False
        source = "REVIEW_PASSWORD_FILE"
        password = raw[:-2] if raw.endswith("\r\n") else raw[:-1] if raw.endswith("\n") else raw
    if not user or not password:
        log("review server: nothing imported: REVIEW_USERNAME needs a non-empty REVIEW_PASSWORD (or REVIEW_PASSWORD_FILE)")
        return False
    problem = validate_username(user) or validate_password(password)
    if problem:
        log(f"review server: REVIEW_USERNAME not imported ({problem}); use the setup page")
        return False
    try:
        create_user(user, "admin", password, only_if_empty=True)
    except Conflict:
        return False
    except AuthError as e:
        log(f"review server: REVIEW_USERNAME not imported ({e.message})")
        return False
    log(
        f"review server: REVIEW_USERNAME imported as the first admin (password from {source}); not read again once accounts exist"
    )
    return True


def is_https(headers) -> bool:
    """True when the request says it came over TLS (X-Forwarded-Proto: https). This server speaks plain HTTP only:
    native TLS is not served here, a reverse proxy in front of it terminates TLS. A client that sends the header
    over plain HTTP just receives a Secure cookie its browser will not return."""
    return header(headers, "X-Forwarded-Proto").split(",")[0].strip().lower() == "https"


def session_cookie(sid: str, remember: bool, secure: bool) -> str:
    parts = [f"{SESSION_COOKIE}={sid}", "Path=/", "HttpOnly", "SameSite=Strict"]
    if remember:
        parts.append(f"Max-Age={REMEMBER_SECONDS}")
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_cookie(secure: bool) -> str:
    parts = [f"{SESSION_COOKIE}=", "Path=/", "HttpOnly", "SameSite=Strict", "Max-Age=0"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def accounts_ok() -> bool:
    try:
        read_users()
        return True
    except Unreadable:
        return False


def check_login(users: list, name, password) -> dict | None:
    """The account for a correct name and password, else None. One scrypt either way: a missing user is verified against a
    dummy hash, so a wrong username takes as long as a wrong password."""
    row = find_user(users, name)
    ok = verify_password(password if isinstance(password, str) else "", row["hash"] if row else dummy_hash())
    return row if (row is not None and ok) else None


LEGACY_CLEAR = f"{LEGACY_COOKIE}=; Path=/; Max-Age=0; SameSite=Strict"


def handle_login(body, client: str, throttle, headers=None) -> tuple:
    body = body if isinstance(body, dict) else {}
    name = body.get("username")
    # Counted per address AND per username: behind a proxy every client shares one address.
    keys = [client] + (["user:" + name.lower()[:64]] if isinstance(name, str) and name else [])
    wait = max(throttle.retry_after(k) for k in keys)
    if wait:
        log("review server: login throttled")
        return 429, {"error": "too many failed logins; wait before trying again", "retry_after": wait}, {}
    try:
        users = read_users()
    except Unreadable as e:
        return 503, {"error": e.message}, {}
    if not users:
        return 409, {"error": "setup required"}, {}
    row = check_login(users, body.get("username"), body.get("password"))
    if row is None:
        for k in keys:
            throttle.failure(k)
        log("review server: login refused")  # the same line for a wrong username and a wrong password
        return 401, {"error": "wrong username or password"}, {}
    for k in keys:
        throttle.success(k)
    remember = body.get("remember") is True
    try:
        sid = sessions().create(row["name"], remember, int(row.get("session_epoch", 0)))  # a fresh id every time
    except AuthError as e:
        return e.status, {"error": e.message}, {}
    out = {"username": row["name"], "role": row["role"]}
    if row["role"] == "admin":
        out["token"] = api_key()  # TRANSITIONAL: the deployed bundle's password sign-in reads it; removed in Task 15
    cookies = [session_cookie(sid, remember, is_https(headers)), LEGACY_CLEAR]  # the legacy token cookie must not outlive a login
    return 200, out, {"Set-Cookie": cookies}


def handle_logout(principal, headers=None) -> tuple:
    if principal is not None and principal.kind == "session":
        sessions().revoke(principal.sid)
    return 200, {"ok": True}, {"Set-Cookie": clear_cookie(is_https(headers))}


def handle_me(principal) -> tuple:
    return 200, {"username": principal.name or "anonymous", "role": principal.role}


def handle_apikey(method: str, path: str) -> tuple:
    """GET /api/apikey and POST /api/apikey/reset. The key is shown here only; the role table makes both admin only."""
    try:
        if method == "POST" and path == "/api/apikey/reset":
            return 200, {"key": reset_api_key()}
        return 200, {"key": api_key()}
    except AuthError as e:
        return e.status, {"error": e.message}
