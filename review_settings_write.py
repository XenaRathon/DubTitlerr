"""Runtime settings writes (specs/webui-settings-write): the web UI picks a repair profile and models, the builder applies
them at the next show / merge-pass boundary.

The web server writes ONE small file, /config/runtime.env, of flat ``KEY=VALUE`` lines for five allow-listed keys.
Nothing ever ``source``s that file: the shell loops call ``python3 review_settings_write.py export`` instead, which parses
it here, re-validates every value, and prints only allow-listed, shell-quoted assignments. A hand-edited or hostile
file can therefore produce nothing but those five validated settings.

A profile replaces the whole repair endpoint: backend, URL, the key variable's NAME, and the optional extra_body and
model_secondary, all together. Picking one never mixes its URL with a previous provider's key or routing flags.

Profiles carry the dangerous parts. ``REPAIR_PROFILES`` is one JSON env var, set in compose by whoever runs the
container: ``{"local": {"backend": "llamacpp", "url": "http://..."}, "cloud": {"backend": "openai", "url": "https://...",
"key_env": "SOME_API_KEY"}}``. The writer accepts only a profile NAME; the URL and the key variable's name are looked up
here at export time, so a stolen admin token cannot point repair at another host or read another variable.

CLI for the loops (gen_loop.sh, merge_pass.sh)::

    eval "$(python3 "$APP_DIR/review_settings_write.py" export 2>/dev/null)"

prints ``export KEY=value`` lines (``--plain`` drops the ``export`` word; ``--file PATH`` reads another file;
``--scope gen|merge`` picks who is asking, default merge). ``gen`` emits only REPAIR_MODEL, VERIFY_BACKEND,
VERIFY_DECISION_MODEL and REQUIRE_ENG: a repair profile belongs to the merge pass (repair), and applying its backend to
the generate loop would also switch punctuation restoration and glossary verify off. It always exits 0 on a read problem
and prints ONE stderr line naming what it ignored, so a bad file falls back to the container environment audibly.

Verify settings are opt-in: RUNTIME_VERIFY_BACKENDS (default llamacpp,ollama) and RUNTIME_DECISION_MODELS (default none)
list what the web UI may select, so an admin token cannot move glossary adjudication to a cloud account the operator
never opted into."""

import contextlib
import json
import os
import re
import shlex
import sys
import tempfile

import glossary_lock

# API key -> runtime.env key.
FILE_KEYS = {
    "repair_profile": "REPAIR_PROFILE",
    "repair_model": "REPAIR_MODEL",
    "verify_backend": "VERIFY_BACKEND",
    "verify_decision_model": "VERIFY_DECISION_MODEL",
    "require_eng": "REQUIRE_ENG",
}
API_KEYS = {v: k for k, v in FILE_KEYS.items()}
MODEL_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
# RFC 3986 characters, without the ones a shell reads as syntax ($ ` ( ) ; ' and friends). Quoting still protects the odd
# legal ones (& * ! # ...), and a test proves it.
URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!&*+,=%-]{1,512}")
EXTRA_BODY_MAX = 2048
VERIFY_BACKENDS = ("llamacpp", "ollama", "openai", "decision")  # parity with glossary_verify.VERIFY_BACKENDS (tested)
PROFILE_BACKENDS = ("llamacpp", "openai")
MAX_FILE_BYTES = 64 * 1024
_LINE_RE = re.compile(r"([A-Z][A-Z_]*)=(.*)")


class Refused(Exception):
    def __init__(self, status, error):
        super().__init__(error)
        self.reply = (status, {"error": error})


def _log(message):
    from common import log

    log(message)


# --- where things live ----------------------------------------------------------------------------------------------


def _env(environ):
    return os.environ if environ is None else environ


def config_dir(environ=None):
    return _env(environ).get("CONFIG_DIR") or "/config"


def runtime_path(environ=None):
    return _env(environ).get("RUNTIME_ENV_FILE") or os.path.join(config_dir(environ), "runtime.env")


# --- profiles -------------------------------------------------------------------------------------------------------


def load_profiles(environ=None):
    """(profiles, reason): the validated REPAIR_PROFILES table, or ({}, why it cannot be used). Unset is ({}, "")."""
    raw = (_env(environ).get("REPAIR_PROFILES") or "").strip()
    if not raw:
        return {}, ""
    try:
        table = json.loads(raw)
    except ValueError as e:
        return {}, f"REPAIR_PROFILES is not valid JSON ({e.__class__.__name__})"
    if not isinstance(table, dict):
        return {}, "REPAIR_PROFILES must be a JSON object of profile names"
    out = {}
    for name, entry in table.items():
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            return {}, "REPAIR_PROFILES has a profile name with unsupported characters"
        if not isinstance(entry, dict):
            return {}, f"REPAIR_PROFILES profile {name!r} must be an object"
        backend, url, key_env = entry.get("backend"), entry.get("url"), entry.get("key_env")
        extra_body, secondary = entry.get("extra_body"), entry.get("model_secondary")
        if backend not in PROFILE_BACKENDS:
            return {}, f"REPAIR_PROFILES profile {name!r} needs backend llamacpp or openai"
        if not isinstance(url, str) or not URL_RE.fullmatch(url):
            return {}, f"REPAIR_PROFILES profile {name!r} needs an http(s) url without spaces or quotes"
        if key_env is not None and not (isinstance(key_env, str) and ENV_NAME_RE.fullmatch(key_env)):
            return {}, f"REPAIR_PROFILES profile {name!r} has an invalid key_env"
        if extra_body is not None:
            try:
                encoded = json.dumps(extra_body, separators=(",", ":"), sort_keys=True) if isinstance(extra_body, dict) else None
            except (TypeError, ValueError):
                encoded = None
            if encoded is None or len(encoded) > EXTRA_BODY_MAX:
                return {}, f"REPAIR_PROFILES profile {name!r} has an invalid extra_body (a small JSON object)"
            extra_body = encoded
        if secondary is not None and not (isinstance(secondary, str) and MODEL_RE.fullmatch(secondary)):
            return {}, f"REPAIR_PROFILES profile {name!r} has an invalid model_secondary"
        out[name] = {"backend": backend, "url": url, "key_env": key_env, "extra_body": extra_body, "model_secondary": secondary}
    return out, ""


def expand_profile(profile):
    """The environment assignments a profile stands for, in a fixed order."""
    out = [("REPAIR_BACKEND", profile["backend"])]
    out.append(("REPAIR_OPENAI_URL" if profile["backend"] == "openai" else "REPAIR_LLAMACPP_URL", profile["url"]))
    # Always set, empty when the profile has none: the previous provider's key pointer, routing flags and secondary model
    # must not carry over to the new endpoint.
    out.append(("REPAIR_OPENAI_KEY_ENV", profile.get("key_env") or ""))
    out.append(("REPAIR_EXTRA_BODY", profile.get("extra_body") or ""))
    out.append(("REPAIR_MODEL_SECONDARY", profile.get("model_secondary") or ""))
    return out


def writable_info(environ=None):
    """{"writable": True} or {"writable": False, "reason": ...}: can this server accept settings writes right now?"""
    _profiles, reason = load_profiles(environ)
    if reason:
        return {"writable": False, "reason": reason}
    directory = os.path.dirname(runtime_path(environ)) or "."
    if not (os.path.isdir(directory) and os.access(directory, os.W_OK)):
        return {"writable": False, "reason": "the config directory is not writable"}
    return {"writable": True}


# --- operator opt-in lists for the verify settings -------------------------------------------------------------------


def _csv(raw):
    return [part.strip() for part in raw.split(",") if part.strip()]


def allowed_verify_backends(environ=None):
    """RUNTIME_VERIFY_BACKENDS (default llamacpp,ollama: the local ones), limited to backends the pipeline knows."""
    raw = _env(environ).get("RUNTIME_VERIFY_BACKENDS")
    return tuple(b for b in _csv("llamacpp,ollama" if raw is None else raw) if b in VERIFY_BACKENDS)


def allowed_decision_models(environ=None):
    """RUNTIME_DECISION_MODELS (default none): exact model ids the web UI may select for the decision backend."""
    return tuple(m for m in _csv(_env(environ).get("RUNTIME_DECISION_MODELS") or "") if MODEL_RE.fullmatch(m))


# --- validation -----------------------------------------------------------------------------------------------------


def _valid_value(file_key, value):
    """The canonical string for one runtime.env value, or None if it is not acceptable."""
    if not isinstance(value, str):
        return None
    if file_key in ("REPAIR_MODEL", "VERIFY_DECISION_MODEL"):
        return value if MODEL_RE.fullmatch(value) else None
    if file_key == "VERIFY_BACKEND":
        return value if value in VERIFY_BACKENDS else None
    if file_key == "REQUIRE_ENG":
        return value if value in ("0", "1") else None
    if file_key == "REPAIR_PROFILE":
        return value if NAME_RE.fullmatch(value) else None
    return None


def _validate_put(body, profiles, environ=None):
    """{file_key: canonical string or None (clear)}, or Refused. Checks the whole body before anything is written."""
    for key in body:
        if key not in FILE_KEYS:
            raise Refused(400, f"unknown key: {key}")
    out = {}
    for key, value in body.items():
        file_key = FILE_KEYS[key]
        if value is None:
            out[file_key] = None
        elif key == "repair_profile":
            if not isinstance(value, str) or value not in profiles:
                raise Refused(400, "unknown repair profile")
            out[file_key] = value
        elif key in ("repair_model", "verify_decision_model"):
            canonical = _valid_value(file_key, value)
            if canonical is None:
                raise Refused(400, "invalid model format")
            if key == "verify_decision_model" and canonical not in allowed_decision_models(environ):
                raise Refused(400, "verify decision model not allowed: the operator lists allowed ids in RUNTIME_DECISION_MODELS")
            out[file_key] = canonical
        elif key == "verify_backend":
            canonical = _valid_value(file_key, value)
            if canonical is None:
                raise Refused(400, "invalid verify backend")
            if canonical not in allowed_verify_backends(environ):
                raise Refused(400, "verify backend not allowed: the operator lists allowed backends in RUNTIME_VERIFY_BACKENDS")
            out[file_key] = canonical
        else:  # require_eng: a real integer 0 or 1, not a bool, float or string
            if type(value) is not int or value not in (0, 1):
                raise Refused(400, "invalid require_eng: use 0 or 1")
            out[file_key] = str(value)
    return out


# --- reading and writing the file -----------------------------------------------------------------------------------


def parse_runtime(path, notes=None):
    """{file_key: validated string} from a runtime.env. Strict and forgiving at once: any line that is not exactly
    ``KEY=VALUE`` for an allow-listed key with a valid value is skipped, and an unreadable file is just empty. Reasons
    for anything ignored are appended to ``notes`` when a list is given (the CLI prints them; the server stays quiet)."""
    notes = [] if notes is None else notes
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_FILE_BYTES + 1)
    except OSError:
        return {}
    if len(raw) > MAX_FILE_BYTES:
        notes.append(f"runtime file is larger than {MAX_FILE_BYTES} bytes")
        return {}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        notes.append("runtime file is not valid UTF-8")
        return {}
    out = {}
    invalid = 0
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _LINE_RE.fullmatch(line)
        value = _valid_value(match.group(1), match.group(2)) if match and match.group(1) in API_KEYS else None
        if value is None:
            invalid += 1
        else:
            out[match.group(1)] = value
    if invalid:
        notes.append(f"{invalid} invalid line(s) in the runtime file")
    return out


def _allowed_only(values, environ=None, notes=None):
    """Drop stored verify values the operator has not opted into (the env lists can change after a value was saved)."""
    notes = [] if notes is None else notes
    out = dict(values)
    if "VERIFY_BACKEND" in out and out["VERIFY_BACKEND"] not in allowed_verify_backends(environ):
        notes.append(f"VERIFY_BACKEND {out.pop('VERIFY_BACKEND')!r} not allowed (RUNTIME_VERIFY_BACKENDS)")
    if "VERIFY_DECISION_MODEL" in out and out["VERIFY_DECISION_MODEL"] not in allowed_decision_models(environ):
        notes.append(f"VERIFY_DECISION_MODEL {out.pop('VERIFY_DECISION_MODEL')!r} not allowed (RUNTIME_DECISION_MODELS)")
    return out


def _atomic_write(path, data):
    """data -> path through a temp file in the same directory, 0664, fsynced; the old file survives any failure."""
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".runtime.env.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o664)  # umask-proof: the builder (root) and the host user both read it
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


def _keep_prev(path):
    """Copy the current file to <path>.prev (atomically) so one reset or hand-revert is always possible."""
    try:
        with open(path, "rb") as f:
            current = f.read(MAX_FILE_BYTES)
    except FileNotFoundError:
        return False
    _atomic_write(path + ".prev", current)
    return True


def _render(values):
    return "".join(f"{key}={values[key]}\n" for key in FILE_KEYS.values() if key in values).encode("utf-8")


def put_settings(body, environ=None):
    """PUT /api/settings after the route has checked both tokens. (status, payload)."""
    info = writable_info(environ)
    if not info["writable"]:
        return 503, {"error": f"settings writes are disabled: {info['reason']}"}
    profiles, _ = load_profiles(environ)
    try:
        updates = _validate_put(body, profiles, environ)
    except Refused as r:
        return r.reply
    if not updates:
        return 200, {"ok": True, "written": {}, "pending": False}
    path = runtime_path(environ)
    try:
        with glossary_lock.locked(path, "settings") as got:
            if not got:
                return 503, {"error": "settings busy, try again"}
            current = parse_runtime(path)
            for key, value in updates.items():
                if value is None:
                    current.pop(key, None)
                else:
                    current[key] = value
            _keep_prev(path)
            _atomic_write(path, _render(current))
    except OSError:
        return 500, {"error": "settings write failed"}
    written = {
        api: (None if updates[file] is None else int(updates[file]) if file == "REQUIRE_ENG" else updates[file])
        for api, file in FILE_KEYS.items()
        if file in updates
    }
    _log(f"review server: settings updated by admin: keys={','.join(sorted(written))}")
    return 200, {"ok": True, "written": written, "pending": True}


def reset_settings(environ=None):
    """POST /api/settings/reset: keep a copy as runtime.env.prev, then delete runtime.env."""
    path = runtime_path(environ)
    try:
        with glossary_lock.locked(path, "settings") as got:
            if not got:
                return 503, {"error": "settings busy, try again"}
            keys = sorted(API_KEYS[k] for k in parse_runtime(path))
            existed = _keep_prev(path)
            if existed:
                os.unlink(path)
    except OSError:
        return 500, {"error": "settings reset failed"}
    if existed:
        _log(f"review server: settings reset by admin: keys={','.join(keys)}")
    return 200, {"ok": True, "reset": True, "pending": existed}


# --- GET: profiles, pending, writable -------------------------------------------------------------------------------


MERGE_EFFECTIVE_NAME = "merge-effective.env"
_REPAIR_KEYS = ("REPAIR_PROFILE", "REPAIR_MODEL")


def _lookup_for(file_key, environ):
    """(mapping, from_a_file). The repair settings are applied by the merge pass, which reports in merge-effective.env;
    the generate loop's effective.env never applies a profile, so comparing a profile with it would flip back and forth
    as the two take turns. Without any report the server's own environment is the baseline."""
    import review_settings

    effective_path = review_settings.EFFECTIVE_ENV_PATH
    if file_key in _REPAIR_KEYS:
        merged = review_settings.read_effective_env(os.path.join(os.path.dirname(effective_path), MERGE_EFFECTIVE_NAME))
        if merged:
            return merged, True
    effective = review_settings.read_effective_env(effective_path)
    return (effective, True) if effective else (dict(_env(environ)), False)


def _revert_value(name, environ):
    value = _env(environ).get(name)
    if value is None or value == "":
        return None
    return int(value) if name == "REQUIRE_ENG" and value.isdigit() else value


def pending_overrides(environ=None, profiles=None):
    """{api key: value} that will change at the next boundary: runtime.env values the builder has not reported yet, and
    (after a reset) settings the builder still runs that revert to the container environment (shown as that value, or
    None when the container leaves it unset)."""
    if profiles is None:
        profiles, _ = load_profiles(environ)
    runtime = _allowed_only(parse_runtime(runtime_path(environ)), environ)
    pending = {}
    for file_key, value in runtime.items():
        seen, _ = _lookup_for(file_key, environ)
        api = API_KEYS[file_key]
        if file_key == "REPAIR_PROFILE":
            profile = profiles.get(value)
            if profile is None or any(seen.get(name, "") != want for name, want in expand_profile(profile)[:2]):
                pending[api] = value
        elif seen.get(file_key, "") != value:
            pending[api] = int(value) if file_key == "REQUIRE_ENG" else value
    for file_key, api in API_KEYS.items():
        if file_key in runtime:
            continue
        seen, from_file = _lookup_for(file_key, environ)
        if not from_file:
            continue
        if file_key == "REPAIR_PROFILE":
            names = ("REPAIR_BACKEND", "REPAIR_LLAMACPP_URL", "REPAIR_OPENAI_URL")
            if any(n in seen and seen[n] != (_env(environ).get(n) or "") for n in names):
                pending[api] = None
        elif file_key in seen and seen[file_key] != (_env(environ).get(file_key) or ""):
            pending[api] = _revert_value(file_key, environ)
    return pending


def augment_get(status, payload, environ=None):
    """Merge profiles, pending, overrides and writable into the GET /api/settings answer; errors pass through."""
    if status != 200 or not isinstance(payload, dict):
        return status, payload
    profiles, _ = load_profiles(environ)
    info = writable_info(environ)
    runtime = _allowed_only(parse_runtime(runtime_path(environ)), environ)
    out = dict(payload)
    out["profiles"] = sorted(profiles)
    out["overrides"] = {API_KEYS[k]: (int(v) if k == "REQUIRE_ENG" else v) for k, v in sorted(runtime.items())}
    out["pending"] = pending_overrides(environ, profiles)
    out["allowed_verify_backends"] = list(allowed_verify_backends(environ))
    out["allowed_decision_models"] = list(allowed_decision_models(environ))
    out["writable"] = info["writable"]
    if not info["writable"]:
        out["writable_reason"] = info["reason"]
    return status, out


# --- the exporter the shell loops call ------------------------------------------------------------------------------


GEN_KEYS = ("REPAIR_MODEL", "VERIFY_BACKEND", "VERIFY_DECISION_MODEL", "REQUIRE_ENG")
SCOPES = ("gen", "merge")


def export_assignments(path=None, environ=None, scope="merge", notes=None):
    """[(NAME, value)] the loops may apply: only allow-listed settings, each re-validated; a profile expands from the
    server-side table and is skipped if the table is unusable or lacks the name. ``scope="gen"`` leaves the profile out
    (the repair endpoint is the merge pass's business). Reasons for anything dropped go to ``notes``."""
    notes = [] if notes is None else notes
    values = _allowed_only(parse_runtime(path or runtime_path(environ), notes), environ, notes)
    out = []
    if scope != "gen" and "REPAIR_PROFILE" in values:
        profiles, reason = load_profiles(environ)
        profile = profiles.get(values["REPAIR_PROFILE"])
        if profile is not None:
            out.extend(expand_profile(profile))
        else:
            notes.append(reason or f"profile {values['REPAIR_PROFILE']!r} is not in REPAIR_PROFILES")
    for key in GEN_KEYS:
        if key in values:
            out.append((key, values[key]))
    return out


def format_assignments(assignments, plain=False):
    prefix = "" if plain else "export "
    return "".join(f"{prefix}{name}={shlex.quote(value)}\n" for name, value in assignments)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    usage = "usage: review_settings_write.py export [--plain] [--file PATH] [--scope gen|merge]"
    if not argv or argv[0] != "export":
        print(usage, file=sys.stderr)
        return 2
    plain, path, scope = False, None, "merge"
    rest = argv[1:]
    while rest:
        arg = rest.pop(0)
        if arg == "--plain":
            plain = True
        elif arg == "--file" and rest:
            path = rest.pop(0)
        elif arg == "--scope" and rest:
            scope = rest.pop(0)
        elif arg.startswith("--scope="):
            scope = arg.split("=", 1)[1]
        else:
            print(f"unknown argument: {arg}\n{usage}", file=sys.stderr)
            return 2
    if scope not in SCOPES:
        print(f"unknown scope: {scope}\n{usage}", file=sys.stderr)
        return 2
    notes = []
    try:
        sys.stdout.write(format_assignments(export_assignments(path, scope=scope, notes=notes), plain))
    except Exception as e:  # noqa: BLE001 - a loop must never die because a settings file is odd
        notes.append(f"unexpected {e.__class__.__name__}")
    if notes:
        print("review_settings_write: ignored: " + "; ".join(notes), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
