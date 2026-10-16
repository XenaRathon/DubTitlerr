"""The settings store (specs/webui-full-settings, S-2): CONFIG_DIR/settings.json and CONFIG_DIR/secrets.json.

settings.json holds the plain values, the Connections and the stage choices; secrets.json (mode 0600) holds the secrets. Both are
written atomically under one lock, with one `.prev` copy of each file per save and one audit log line that names keys but never
secret values. Reading never raises: an unusable file yields an empty State whose `error` says why, so every consumer falls back
to the container environment and the code defaults.

State.rev counts saves; a form that carries an older rev is stale and the API answers 409.
"""

import contextlib
import copy
import json
import os
import tempfile
import urllib.parse

import glossary_lock
import settings_connections as conns
import settings_registry as reg

VERSION = 1
MAX_BYTES = 256 * 1024
_WARNED_UNKNOWN: set = set()


class State:
    def __init__(self):
        self.rev = 0
        self.values = {}  # KEY -> canonical typed value, plain editable settings only
        self.unknown = {}  # keys the registry no longer knows: ignored, but kept in the file
        self.connections = []  # [{name, kind, url, model, extra_body, timeout_connect, timeout_read}]
        self.stages = {}  # stage -> connection name
        self.secret_values = {}  # KEY -> string
        self.conn_keys = {}  # connection name -> API key
        self.error = ""  # settings.json is unusable: why (saving is refused)
        self.secrets_error = ""  # secrets.json is unusable or not private: why (the exporter skips secrets)
        self.notes = []  # entries ignored on load, for the log

    def copy(self):
        return copy.deepcopy(self)


def _env(environ):
    return os.environ if environ is None else environ


def config_dir(environ=None):
    return _env(environ).get("CONFIG_DIR") or "/config"


def settings_path(environ=None):
    return os.path.join(config_dir(environ), "settings.json")


def secrets_path(environ=None):
    return os.path.join(config_dir(environ), "secrets.json")


def _log(message):
    try:
        from common import log
    except ImportError:  # the exporter runs from a minimal app directory in tests
        log = print
    log(message)


def redact_url(url):
    """scheme://host[:port]/path: no user info, query or fragment, so a URL can be logged."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        netloc = host + (f":{parts.port}" if parts.port else "")
        return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except ValueError:
        return "[unparseable url]"


# --- reading --------------------------------------------------------------------------------------------------------------


def _read_json(path):
    """(data, error): the parsed object, or why it cannot be used. A missing file is ({}, "")."""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return {}, ""
    except OSError as e:
        return {}, f"{os.path.basename(path)} is unreadable ({e.__class__.__name__})"
    if len(raw) > MAX_BYTES:
        return {}, f"{os.path.basename(path)} is larger than {MAX_BYTES} bytes"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}, f"{os.path.basename(path)} is not valid JSON"
    if not isinstance(data, dict):
        return {}, f"{os.path.basename(path)} has an unexpected shape"
    if data.get("version") != VERSION:
        return (
            {},
            f"{os.path.basename(path)} is from another version ({data.get('version')!r}); this release reads version {VERSION}",
        )
    return data, ""


def ensure_secret_perms(path):
    """ "" when secrets.json is absent or private (0600); else fix it, and say why when that fails."""
    try:
        mode = os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        return ""
    except OSError as e:
        return f"secrets.json cannot be inspected ({e.__class__.__name__})"
    if mode == 0o600:
        return ""
    try:
        os.chmod(path, 0o600)
    except OSError as e:
        return f"secrets.json is mode {mode:o} and cannot be made private ({e.__class__.__name__})"
    _log(f"review server: secrets.json was mode {mode:o}; set to 600")
    return ""


def _valid_secret(value):
    return (
        isinstance(value, str)
        and "\n" not in value
        and "\r" not in value
        and "\x00" not in value
        and len(value) <= 512
        and bool(value.strip())
    )


def _load_connections(state, items):
    """Keep the connections a PUT would accept; each dropped entry leaves a note naming it, never a value."""
    seen = set()
    for index, item in enumerate(items):
        conn, problems = conns.validate_connection(item)
        label = item.get("name") if isinstance(item, dict) and isinstance(item.get("name"), str) else f"#{index}"
        if problems:
            state.notes.append(f"connection {label} ignored: {'; '.join(f'{f} {m}' for f, m in sorted(problems.items()))}")
        elif conn["name"] in seen:
            state.notes.append(f"connection {label} ignored: the name is used twice")
        else:
            seen.add(conn["name"])
            state.connections.append(conn)


def _load_stages(state, stages):
    """Keep the stage choices validate_stages accepts, dropping the refused ones until the rest agree."""
    while True:
        errors = conns.validate_stages(stages, state.connections)
        if not errors:
            break
        for stage, why in sorted(errors.items()):
            state.notes.append(f"stage {stage} ignored: {why}")
            stages.pop(stage, None)
    state.stages = stages


def load(environ=None):
    """The current State. Never raises."""
    state = State()
    data, state.error = _read_json(settings_path(environ))
    if not state.error:
        state.rev = data.get("rev") if type(data.get("rev")) is int else 0
        values = data.get("values") if isinstance(data.get("values"), dict) else {}
        for key, value in values.items():
            entry = reg.REGISTRY.get(key)
            if entry is None:
                state.unknown[key] = value
                if key not in _WARNED_UNKNOWN:
                    _WARNED_UNKNOWN.add(key)
                    _log(f"settings: {key} is not in this release's registry; ignored and kept in settings.json")
                continue
            if not (entry["editable"] or entry.get("legacy_override")) or entry["secret"]:
                state.notes.append(f"{key} is not editable in this release")
                continue
            try:
                state.values[key] = reg.validate(key, value)
            except reg.Invalid as e:
                state.notes.append(f"{key} ignored: {e}")
        if isinstance(data.get("connections"), list):
            _load_connections(state, data["connections"])
        if isinstance(data.get("stages"), dict):
            _load_stages(state, {k: v for k, v in data["stages"].items() if isinstance(k, str) and isinstance(v, str)})
    state.secrets_error = ensure_secret_perms(secrets_path(environ))
    if not state.secrets_error:
        sdata, state.secrets_error = _read_json(secrets_path(environ))
        if not state.secrets_error:
            raw_values = sdata.get("values") if isinstance(sdata.get("values"), dict) else {}
            for k, v in raw_values.items():
                entry = reg.REGISTRY.get(k)
                if entry is None or not entry["secret"]:
                    continue
                if not entry["editable"]:
                    state.notes.append(f"{k} is not editable in this release")
                    continue
                if _valid_secret(v):
                    state.secret_values[k] = v
                elif v is not None and v != "":
                    state.notes.append(f"{k} ignored: must be one line of at most 512 characters")
            raw_conns = sdata.get("connections") if isinstance(sdata.get("connections"), dict) else {}
            for name, item in raw_conns.items():
                if isinstance(item, dict) and "api_key" in item:
                    k = item["api_key"]
                    conn = next((c for c in state.connections if c["name"] == name), None)
                    why = conns.key_problem(conn, k) if conn and _valid_secret(k) else ""
                    if why:
                        state.notes.append(f"connection key {name} ignored: {why}")
                    elif _valid_secret(k):
                        state.conn_keys[name] = k
                    elif k is not None and k != "":
                        state.notes.append(f"connection key {name} ignored: must be one line of at most 512 characters")
    return state


# --- writing --------------------------------------------------------------------------------------------------------------


@contextlib.contextmanager
def locked(environ=None):
    """Yield True with the settings lock held, False when it is busy. The one lock serialises settings.json and secrets.json."""
    path = settings_path(environ)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    # Ensure the lock file can be opened so glossary_lock never falls back to yielding True unlocked.
    lpath = glossary_lock.lock_path(path)
    try:
        fd = os.open(lpath, os.O_RDWR | os.O_CREAT, 0o664)
        os.close(fd)
    except OSError as e:
        raise OSError(e.errno, f"cannot open settings lock {lpath}: {e.strerror or e}") from e
    with glossary_lock.locked(path, "settings") as got:
        yield got


def atomic_write(path, data, mode):
    """data -> path through a temp file in the same directory, fsynced; the old file survives any failure."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".settings.", suffix=".tmp")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    with contextlib.suppress(OSError):
        dfd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


def _keep_prev(path, mode):
    try:
        with open(path, "rb") as f:
            current = f.read(MAX_BYTES)
    except FileNotFoundError:
        return
    atomic_write(path + ".prev", current, mode)


def _dump(obj):
    return (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8")


def save(state, environ=None):
    """Write secrets first, then settings (the caller holds the lock; the two files are not one atomic step) and bump state.rev.
    Raises OSError."""
    new_rev = state.rev + 1
    plain = {
        "version": VERSION,
        "rev": new_rev,
        "values": {**state.unknown, **state.values},
        "connections": state.connections,
        "stages": state.stages,
    }
    private = {
        "version": VERSION,
        "values": state.secret_values,
        "connections": {n: {"api_key": k} for n, k in sorted(state.conn_keys.items())},
    }
    spath, ppath = settings_path(environ), secrets_path(environ)
    prev_secrets = None
    if not state.secrets_error:  # an unusable secrets.json is left as it is; only a reset-all moves it aside
        try:
            with open(ppath, "rb") as f:
                prev_secrets = f.read()
        except OSError:
            prev_secrets = None
        _keep_prev(ppath, 0o600)
        atomic_write(ppath, _dump(private), 0o600)
    try:
        _keep_prev(spath, 0o664)
        atomic_write(spath, _dump(plain), 0o664)
    except BaseException:
        if not state.secrets_error:
            if prev_secrets is not None:
                atomic_write(ppath, prev_secrets, 0o600)
            else:
                with contextlib.suppress(OSError):
                    os.unlink(ppath)
        raise
    state.rev = new_rev


def scrub(text, state):
    """``text`` with every stored secret (and any connection key) replaced, for an error string that came from outside."""
    for secret in [*state.secret_values.values(), *state.conn_keys.values()]:
        if len(secret) >= 8:
            text = text.replace(secret, "[redacted]")
    return text


def audit(who, keys, secret_keys=(), urls=None):
    """One log line per save: who, the keys, the NAMES of secrets touched (never a value), and each changed URL without
    user info, query or fragment."""
    parts = [f"keys={','.join(sorted(keys))}"]
    if secret_keys:
        parts.append(f"secrets={','.join(sorted(secret_keys))}")
    for name, url in sorted((urls or {}).items()):
        parts.append(f"url {name}={redact_url(url)}")
    _log(f"review server: settings saved by {who}: " + " ".join(parts))
