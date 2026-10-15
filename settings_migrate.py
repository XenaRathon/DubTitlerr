"""One-time migration from the pre-0.3.0 runtime.env (specs/webui-full-settings, S-4).

On the first start with no `runtime.env.migrated` next to the old runtime file:
  * the keys of an existing runtime.env become stored values (REQUIRE_ENG, ACQUIRE_APPLY, REPAIR_MODEL, VERIFY_BACKEND,
    VERIFY_DECISION_MODEL) and runtime.env is renamed to runtime.env.migrated;
  * with no runtime.env, an empty runtime.env.migrated is written, so the migration runs exactly once.
The old exporter applied VERIFY_BACKEND and VERIFY_DECISION_MODEL only when the operator had opted in through
RUNTIME_VERIFY_BACKENDS (default llamacpp,ollama) and RUNTIME_DECISION_MODELS (default none), so the same filter runs here: a
value it refused is skipped with a log note and never imported. After the migration those lists are never read again.

Idempotent: the marker is written last, and a rerun after a crash imports only what the store does not already hold."""

import os
import re

import settings_registry as reg
import settings_store as store

OLD_KEYS = ("REPAIR_MODEL", "VERIFY_BACKEND", "VERIFY_DECISION_MODEL", "REQUIRE_ENG", "ACQUIRE_APPLY")
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


def migrate(environ=None):
    """Run the migration. Returns the notes (empty when it did nothing or everything was clean). Never raises."""
    environ = os.environ if environ is None else environ
    notes = []
    old = runtime_path(environ)
    marker = old + ".migrated"
    if os.path.exists(marker):
        return notes
    runtime = parse_runtime(old, notes)
    if runtime is None:
        return notes
    runtime = _allowed_only(runtime, environ, notes)
    try:
        with store.locked(environ) as got:
            if not got:
                return notes + ["settings busy; migration retried at the next start"]
            state = store.load(environ)
            if state.error or state.secrets_error:
                return notes + [state.error or state.secrets_error]
            imported = []
            for key in ("REQUIRE_ENG", "ACQUIRE_APPLY"):
                if key in runtime and key not in state.values and _flag(runtime[key]) is not None:
                    state.values[key] = _flag(runtime[key])
                    imported.append(key)
            for key in ("REPAIR_MODEL", "VERIFY_BACKEND", "VERIFY_DECISION_MODEL"):
                if key in runtime and key not in state.values:
                    try:
                        state.values[key] = reg.validate(key, runtime[key])
                        imported.append(key)
                    except reg.Invalid:
                        notes.append(f"runtime.env {key} skipped: not a valid value")
            if imported:
                store.save(state, environ)
                store.audit("migration from runtime.env", imported)
            if os.path.exists(old):
                os.replace(old, marker)
            else:
                store.atomic_write(marker, b"", 0o664)
    except OSError as e:
        notes.append(f"migration failed ({e.__class__.__name__}); retried at the next start")
    for note in notes:
        store._log(f"settings migration: {note}")
    return notes
