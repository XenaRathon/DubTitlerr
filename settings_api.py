"""Settings API (specs/webui-full-settings, S-3, S-6, S-7): the registry's schema, the effective values with their sources, and
the validated, all-or-nothing writes. Pure functions over an environ mapping and the store; review_server.py only routes.

The role of the caller (user or admin) is enforced before these functions run, by the role table in review_auth.py: the routes
are registered there from ROLE_ENTRIES. The one thing checked here is the secret gate, _secrets_writable()."""

import os

import review_auth
import review_settings
import settings_registry as reg
import settings_store as store

ROLE_ENTRIES = {
    ("GET", "/api/settings"): "user",
    ("GET", "/api/settings/schema"): "user",
    ("PUT", "/api/settings"): "admin",
    ("POST", "/api/settings/reset"): "admin",
    ("POST", "/api/settings/test"): "admin",
    ("POST", "/api/system/restart"): "admin",
}
RETIRED_ENV = ("REPAIR_PROFILES", "RUNTIME_VERIFY_BACKENDS", "RUNTIME_DECISION_MODELS")


def _env(environ):
    return os.environ if environ is None else environ


def _secrets_writable():
    """Secrets are accepted only with accounts on and the first-run setup finished: before that no admin can be told apart."""
    return review_auth.auth_on() and not review_auth.setup_required()


# --- reading --------------------------------------------------------------------------------------------------------------


def _container_raw(key, environ):
    """What the container holds for key. A boot-applied key reports its pre-store value (DT_BOOT_<KEY>, written by
    `export --boot`), because the process environment already carries the stored value."""
    boot = "DT_BOOT_" + key
    return environ.get(boot) if boot in environ else environ.get(key)


def _reports(environ):
    gen_path = review_settings.get_effective_env_path(environ)
    merge_path = os.path.join(os.path.dirname(gen_path), "merge-effective.env")
    return {
        "gen": (review_settings.read_effective_env(gen_path), _mtime(gen_path)),
        "merge": (review_settings.read_effective_env(merge_path), _mtime(merge_path)),
    }


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _applied(key, entry, environ, reports):
    """What the consuming process reports it runs with: the mapping it reports in (a report file, or the server's own
    environment for a restart-applied key)."""
    scope = set(entry["scope"])
    if "gen" in scope:
        return reports["gen"][0]
    if "merge" in scope:
        return reports["merge"][0]
    return environ


def _resolve(key, state, environ, reports, settings_mtime):
    entry = reg.REGISTRY[key]
    raw = _container_raw(key, environ)
    env_set = bool((raw or "").strip())
    if entry["secret"]:
        stored = key in state.secret_values
        out = {"set": stored or env_set, "source": "ui" if stored else "env" if env_set else "default"}
        if entry["applies"] == "restart":
            pending = stored and environ.get(key) != state.secret_values[key]
        else:
            report_mtime = reports["gen" if "gen" in entry["scope"] else "merge"][1]
            pending = stored and report_mtime < settings_mtime
    else:
        env_value, env_ok = reg.from_env(key, raw)
        if key in state.values:
            value, source, expected = state.values[key], "ui", state.values[key]
        elif env_value is not None:
            value, source, expected = env_value, "env", env_value
        else:
            value, source, expected = entry["default"], "default", None
        reported = _applied(key, entry, environ, reports)
        applied, _ = reg.from_env(key, reported.get(key))
        out = {"value": value, "source": source}
        if source == "env" and not env_ok:
            out["env_invalid"] = True
        # A value nobody stored differs only when the builder reports the key (a reset it has not applied yet): a builder that
        # has not reported at all is not a pending change.
        pending = applied != expected and (source == "ui" or key in reported)
    out["overridden_env"] = (key in state.values or key in state.secret_values) and env_set
    out["pending"] = bool(pending)
    return out


def _redact(key, out):
    """No credential leaves in a value: URLs lose user info and query, an extra body is reported only as set or not."""
    if "value" not in out:
        return out
    if key.endswith("_EXTRA_BODY"):
        out["set"] = bool(str(out.pop("value") or "").strip())
    elif isinstance(out["value"], str) and (reg.REGISTRY[key]["type"] == "url" or reg.URL_RE.match(out["value"])):
        out["value"] = store.redact_url(out["value"]) if out["value"] else out["value"]
    return out


def get_settings(environ=None):
    environ = _env(environ)
    state = store.load(environ)
    reports = _reports(environ)
    settings_mtime = _mtime(store.settings_path(environ))
    values = {key: _redact(key, _resolve(key, state, environ, reports, settings_mtime)) for key in reg.REGISTRY}
    return 200, {
        "values": values,
        "connections": [],
        "stages": dict(state.stages),
        "restart_pending": any(values[k]["pending"] for k, e in reg.REGISTRY.items() if e["applies"] == "restart"),
        "revision": state.rev,
        "store_error": state.error,
        "secrets_error": state.secrets_error,
        "secrets_writable": _secrets_writable() and not state.secrets_error,
        "retired_env": [name for name in RETIRED_ENV if (environ.get(name) or "").strip()],
    }


# --- dispatch -------------------------------------------------------------------------------------------------------------


def handle(method, path, body=None, environ=None, who="admin", opener=None):
    route = (path or "").split("?", 1)[0]
    if method == "GET" and route == "/api/settings/schema":
        return 200, reg.schema()
    if method == "GET" and route == "/api/settings":
        return get_settings(environ)
    if method == "POST" and route == "/api/settings/test":
        return review_settings.handle(method, route, body, environ=environ, opener=opener)
    return 404, {"error": "no such route"}
