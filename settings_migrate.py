"""One-time migration from the pre-0.3.0 runtime.env and REPAIR_PROFILES (specs/webui-full-settings, S-4).

On the first start with no `runtime.env.migrated` next to the old runtime file:
  * the keys of an existing runtime.env become stored values (REQUIRE_ENG, ACQUIRE_APPLY, REPAIR_MODEL, VERIFY_BACKEND,
    VERIFY_DECISION_MODEL) and runtime.env is renamed to runtime.env.migrated;
  * with no runtime.env, an empty runtime.env.migrated is written, so the migration runs exactly once;
  * every REPAIR_PROFILES entry becomes a Connection (with the key found in the environment variable its key_env named, if any;
    its model_secondary becomes the Connection's second model), and a REPAIR_PROFILE chosen in runtime.env becomes the repair
    stage. This import has its own marker, CONFIG_DIR/profiles.migrated, so it does not depend on the runtime.env one; the
    REPAIR_PROFILE choice is read from runtime.env, or from runtime.env.migrated once the first step has renamed it.
The old exporter applied VERIFY_BACKEND and VERIFY_DECISION_MODEL only when the operator had opted in through
RUNTIME_VERIFY_BACKENDS (default llamacpp,ollama) and RUNTIME_DECISION_MODELS (default none), so the same filter runs here: a
value it refused is skipped with a log note and never imported. After the migration those lists are never read again.

Idempotent: the marker is written last, and a rerun after a crash imports only what the store does not already hold."""

import json
import math
import os
import re

import settings_connections as conns
import settings_registry as reg
import settings_store as store

OLD_KEYS = ("REPAIR_PROFILE", "REPAIR_MODEL", "VERIFY_BACKEND", "VERIFY_DECISION_MODEL", "REQUIRE_ENG", "ACQUIRE_APPLY")
VERIFY_BACKENDS = ("llamacpp", "ollama", "openai", "decision")  # what the 0.2.x exporter knew
_LINE = re.compile(r"([A-Z][A-Z_]*)=(.*)")
MAX_BYTES = 64 * 1024


def runtime_path(environ):
    return environ.get("RUNTIME_ENV_FILE") or os.path.join(store.config_dir(environ), "runtime.env")


def parse_runtime(path, notes):
    """{KEY: value} for the old runtime keys; None when the file cannot be read (so the migration is retried next start)."""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return {}
    except OSError as e:
        notes.append(f"runtime.env unreadable ({e.__class__.__name__})")
        return None
    out = {}
    for line in raw[:MAX_BYTES].decode("utf-8", "replace").split("\n"):
        match = _LINE.fullmatch(line.rstrip("\r"))
        if match and match.group(1) in OLD_KEYS:
            out[match.group(1)] = match.group(2)
    return out


def _csv(raw):
    return [part.strip() for part in raw.split(",") if part.strip()]


def _allowed_only(runtime, environ, notes):
    """The 0.2.x opt-in filter: drop verify values the operator never listed, and say so (the exporter never applied them)."""
    out = dict(runtime)
    raw = environ.get("RUNTIME_VERIFY_BACKENDS")
    backends = [b for b in _csv("llamacpp,ollama" if raw is None else raw) if b in VERIFY_BACKENDS]
    if "VERIFY_BACKEND" in out and out["VERIFY_BACKEND"] not in backends:
        notes.append(f"runtime.env VERIFY_BACKEND {out.pop('VERIFY_BACKEND')!r} skipped: not allowed by RUNTIME_VERIFY_BACKENDS")
    models = _csv(environ.get("RUNTIME_DECISION_MODELS") or "")
    if "VERIFY_DECISION_MODEL" in out and out["VERIFY_DECISION_MODEL"] not in models:
        skipped = out.pop("VERIFY_DECISION_MODEL")
        notes.append(f"runtime.env VERIFY_DECISION_MODEL {skipped!r} skipped: not allowed by RUNTIME_DECISION_MODELS")
    return out


def _flag(text):
    return {"1": True, "0": False}.get(text)


def _seed_timeout(environ, name, field):
    """The container's own value for REPAIR_TIMEOUT_*, when it is a number from 1 to 600; else the default.
    The Connection always emits its timeouts, so without this a raised REPAIR_TIMEOUT_READ would silently drop back to 120."""
    try:
        value = float((environ.get(name) or "").strip())
    except ValueError:
        return conns.TIMEOUT_DEFAULTS[field]
    return value if math.isfinite(value) and 1 <= value <= 600 else conns.TIMEOUT_DEFAULTS[field]


def import_profiles(environ, notes):
    """[(connection, key)] from REPAIR_PROFILES. Every profile or key that cannot be imported leaves a note; nothing raises."""
    raw = (environ.get("REPAIR_PROFILES") or "").strip()
    if not raw:
        return []
    try:
        table = json.loads(raw)
    except ValueError:
        notes.append("REPAIR_PROFILES is not valid JSON; no connections imported")
        return []
    if not isinstance(table, dict):
        notes.append("REPAIR_PROFILES is not an object; no connections imported")
        return []
    out = []
    for name, entry in table.items():
        if not isinstance(entry, dict):
            notes.append(f"profile {name!r} skipped: not an object")
            continue
        item = {
            "name": name,
            "kind": entry.get("backend"),
            "url": entry.get("url"),
            "model": "",
            "extra_body": entry.get("extra_body") or {},
            "timeout_connect": _seed_timeout(environ, "REPAIR_TIMEOUT_CONNECT", "timeout_connect"),
            "timeout_read": _seed_timeout(environ, "REPAIR_TIMEOUT_READ", "timeout_read"),
        }
        if entry.get("model_secondary"):
            item["model_secondary"] = entry["model_secondary"]
        conn, problems = conns.validate_connection(item)
        if problems:
            notes.append(f"profile {name!r} skipped: " + ", ".join(f"{f} {m}" for f, m in sorted(problems.items())))
            continue
        key_env = entry.get("key_env")
        key = ""
        if isinstance(key_env, str) and key_env:
            value = (environ.get(key_env) or "").strip()
            if not value:
                notes.append(f"profile {name!r}: key not imported, {key_env} is not set; enter the key on the Connections page")
            elif conns.key_problem(conn, value):
                notes.append(f"profile {name!r}: key from {key_env} not imported ({conns.key_problem(conn, value)})")
            else:
                key = value
        out.append((conn, key))
    return out


def _migrate_values(state, values, notes):
    imported = []
    for key in ("REQUIRE_ENG", "ACQUIRE_APPLY"):
        if key in values and key not in state.values and _flag(values[key]) is not None:
            state.values[key] = _flag(values[key])
            imported.append(key)
    for key in ("REPAIR_MODEL", "VERIFY_BACKEND", "VERIFY_DECISION_MODEL"):
        if key in values and key not in state.values:
            try:
                state.values[key] = reg.validate(key, values[key])
                imported.append(key)
            except reg.Invalid:
                notes.append(f"runtime.env {key} skipped: not a valid value")
    return imported


def _migrate_profiles(state, environ, runtime, imported, imported_keys, notes):
    defer_profiles = False
    names = {c["name"] for c in state.connections}
    profile_notes = []
    profiles = import_profiles(environ, profile_notes)
    if state.secrets_error and any(key for _, key in profiles):
        # save() leaves an unusable secrets.json alone, so a connection created now would lose its key for good: a
        # rerun skips connections that already exist. Defer the whole import (no connections, no marker) until fixed.
        defer_profiles = True
        profiles = []
        notes.append(
            f"profile import deferred: {state.secrets_error}; fix or reset secrets.json and the profiles "
            "(with their keys) are imported at the next start"
        )
    else:
        notes.extend(profile_notes)
    for conn, key in profiles:
        if conn["name"] not in names:
            state.connections.append(conn)
            names.add(conn["name"])
            imported.append(f"connection:{conn['name']}")
            if key:
                state.conn_keys[conn["name"]] = key
                imported_keys.append(f"connection:{conn['name']}.api_key")
    chosen = None if defer_profiles else runtime.get("REPAIR_PROFILE")
    if chosen and chosen not in names:
        notes.append(f"REPAIR_PROFILE {chosen!r} is not an imported profile; the repair stage is left unset")
    elif chosen and "repair" not in state.stages:
        state.stages["repair"] = chosen
        imported.append("stages")
    return defer_profiles


def migrate(environ=None):
    """Run the migration. Returns the notes (empty when it did nothing or everything was clean). Never raises."""
    environ = os.environ if environ is None else environ
    notes = []
    old = runtime_path(environ)
    marker = old + ".migrated"
    profiles_marker = os.path.join(store.config_dir(environ), "profiles.migrated")
    runtime_done, profiles_done = os.path.exists(marker), os.path.exists(profiles_marker)
    if runtime_done and profiles_done:
        return notes
    # The runtime values are imported once; the REPAIR_PROFILE choice is still read after the file was renamed.
    runtime = parse_runtime(marker if runtime_done else old, notes)
    if runtime is None:
        if not runtime_done:
            return notes  # retried at the next start
        runtime = {}
    values = {} if runtime_done else _allowed_only(runtime, environ, notes)
    try:
        with store.locked(environ) as got:
            if not got:
                return notes + ["settings busy; migration retried at the next start"]
            state = store.load(environ)
            if state.error:  # secrets are never written here, so an unusable secrets.json must not hold the import back
                return notes + [state.error]
            imported = _migrate_values(state, values, notes)
            imported_keys = []
            defer_profiles = False
            if not profiles_done:
                defer_profiles = _migrate_profiles(state, environ, runtime, imported, imported_keys, notes)
            if imported:
                store.save(state, environ)
                store.audit("migration from runtime.env", imported, imported_keys)
            if not runtime_done:
                if os.path.exists(old):
                    os.replace(old, marker)
                else:
                    store.atomic_write(marker, b"", 0o664)
            if not profiles_done and not defer_profiles:
                store.atomic_write(profiles_marker, b"", 0o664)
    except OSError as e:
        notes.append(f"migration failed ({e.__class__.__name__}); retried at the next start")
    return notes  # the caller logs them: review_settings_write.py prints each once
