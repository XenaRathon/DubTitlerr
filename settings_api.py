"""Settings API (specs/webui-full-settings, S-3, S-6, S-7): the registry's schema, the effective values with their sources, and
the validated, all-or-nothing writes. Pure functions over an environ mapping and the store; review_server.py only routes.

The role of the caller (user or admin) is enforced before these functions run, by the role table in review_auth.py: the routes
are registered there from ROLE_ENTRIES. The one thing checked here is the secret gate, _secrets_writable()."""

import errno
import os
import re
import urllib.parse

import review_auth
import review_settings
import settings_registry as reg
import settings_store as store

_URL_USERINFO_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@,]*@")

ROLE_ENTRIES = {
    ("GET", "/api/settings"): "user",
    ("GET", "/api/settings/schema"): "user",
    ("PUT", "/api/settings"): "admin",
    ("POST", "/api/settings/reset"): "admin",
    ("POST", "/api/settings/test"): "admin",
    ("POST", "/api/system/restart"): "admin",
}
SECRETS_NEED_LOGIN = "secrets can be changed only after login is enabled"
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
    elif isinstance(out["value"], str):
        v = out["value"]
        if reg.REGISTRY[key]["type"] == "url" or reg.URL_RE.match(v):
            v = store.redact_url(v) if v else v
        out["value"] = _URL_USERINFO_RE.sub(r"\1", v)
    elif isinstance(out["value"], list):
        out["value"] = [_URL_USERINFO_RE.sub(r"\1", item) if isinstance(item, str) else item for item in out["value"]]
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


# --- writing --------------------------------------------------------------------------------------------------------------


def _write_failure(e):
    if e.errno == errno.ENOSPC:
        return 507, {"error": f"the config volume is full ({e.__class__.__name__})"}
    return 503, {"error": f"the config volume is not writable ({e.__class__.__name__})"}


def _validate_values(values):
    """({KEY: ("set"|"reset"|"secret_set"|"secret_clear", canonical)}, {KEY: message}); a secret sent as "" means no change."""
    plan, errors = {}, {}
    for key, value in values.items():
        entry = reg.REGISTRY.get(key) if isinstance(key, str) else None
        if entry is None:
            errors[str(key)] = "unknown setting"
        elif not entry["editable"] and not (entry.get("legacy_override") and value is None):
            errors[key] = "set through a Connection" if entry["managed_by"] == "connections" else "edit in a later release"
        elif entry["secret"]:
            if value == "":
                continue
            if value is None or (isinstance(value, dict) and value == {"clear": True}):
                plan[key] = ("secret_clear", None)
            elif (
                isinstance(value, str)
                and "\n" not in value
                and "\r" not in value
                and "\x00" not in value
                and len(value) <= 512
                and value.strip()
            ):
                plan[key] = ("secret_set", value)
            else:
                errors[key] = 'must be one line of at most 512 characters, or {"clear": true}'
        elif value is None:
            plan[key] = ("reset", None)
        elif entry["type"] == "url" and isinstance(value, str):
            parts = urllib.parse.urlsplit(value.strip())
            if parts.query or parts.fragment:
                errors[key] = "must not contain a query or fragment; tokens belong in a secret field"
            else:
                try:
                    plan[key] = ("set", reg.validate(key, value))
                except reg.Invalid as e:
                    errors[key] = str(e)
        else:
            try:
                plan[key] = ("set", reg.validate(key, value))
            except reg.Invalid as e:
                errors[key] = str(e)
    return plan, errors


def _apply(state, plan):
    """Apply a validated plan to state; the keys that really changed, and the names of the secrets touched."""
    changed, secret_keys = [], []
    for key, (action, value) in plan.items():
        if action == "set" and state.values.get(key, object()) != value:
            state.values[key] = value
            changed.append(key)
        elif action == "reset" and key in state.values:
            del state.values[key]
            changed.append(key)
        elif action == "secret_set" and state.secret_values.get(key) != value:
            state.secret_values[key] = value
            changed.append(key)
            secret_keys.append(key)
        elif action == "secret_clear" and key in state.secret_values:
            del state.secret_values[key]
            changed.append(key)
            secret_keys.append(key)
    return changed, secret_keys


def _commit(environ, who, build, touches_secrets=False, prepare=None):
    """Lock, run prepare() (file moves that must happen under the lock), load fresh, let build(state) -> (changed, secret_keys,
    urls) or an (status, payload) refusal, save, audit. A corrupt settings.json refuses every save; a corrupt secrets.json
    only the ones that touch secrets."""
    try:
        with store.locked(environ) as got:
            if not got:
                return 503, {"error": "settings are busy, try again"}
            if prepare is not None:
                prepare()
            state = store.load(environ)
            if state.error or (state.secrets_error and touches_secrets):
                return 409, {
                    "error": f"{state.error or state.secrets_error}; reset the settings before saving",
                    "reset_required": True,
                }
            outcome = build(state)
            if isinstance(outcome[0], int):
                return outcome
            changed, secret_keys, urls = outcome
            if changed:
                store.save(state, environ)
                store.audit(who, changed, secret_keys, urls)
            return 200, {
                "ok": True,
                "changed": sorted(changed),
                "restart_required": sorted(k for k in changed if k in reg.REGISTRY and reg.REGISTRY[k]["applies"] == "restart"),
                "revision": state.rev,
            }
    except OSError as e:
        return _write_failure(e)


def put_settings(body, environ=None, who="admin"):
    environ = _env(environ)
    if not isinstance(body, dict) or not isinstance(body.get("values", {}), dict):
        return 400, {"errors": {"body": 'send {"values": {KEY: value}, "revision": N}'}}
    extra = sorted(set(body) - {"values", "revision"})
    if extra:
        return 400, {"errors": {"body": f"unknown field: {extra[0]}"}}
    if type(body.get("revision")) is not int:
        return 400, {"errors": {"revision": "send the revision you loaded, as an integer"}}
    plan, errors = _validate_values(body.get("values", {}))
    touches_secrets = any(action.startswith("secret") for action, _ in plan.values())
    if touches_secrets and not _secrets_writable():
        return 403, {"error": SECRETS_NEED_LOGIN}
    if errors:
        return 400, {"errors": errors}

    def build(state):
        if body["revision"] != state.rev:
            status, current = get_settings(environ)
            return 409, {"error": "settings changed since you loaded them", "current": current}
        changed, secret_keys = _apply(state, plan)
        urls = {k: state.values[k] for k in changed if k in state.values and reg.REGISTRY[k]["type"] == "url" and state.values[k]}
        return changed, secret_keys, urls

    return _commit(environ, who, build, touches_secrets)


def _move_aside(path):
    os.replace(path, path + ".corrupt")


def reset_settings(body, environ=None, who="admin"):
    environ = _env(environ)
    shape = 'send {"keys": [...]}, {"category": id} or {"all": true}'
    if not isinstance(body, dict):
        return 400, {"errors": {"body": shape}}
    writable = _secrets_writable()
    everything = body.get("all") is True
    if isinstance(body.get("keys"), list):
        if not all(isinstance(k, str) for k in body["keys"]):
            return 400, {"errors": {"keys": "must be a list of strings"}}
        keys = body["keys"]
        bad = {k: "unknown setting" for k in keys if k not in reg.REGISTRY}
        if bad:
            return 400, {"errors": bad}
        if any(reg.REGISTRY[k]["secret"] for k in keys) and not writable:
            return 403, {"error": SECRETS_NEED_LOGIN}
    elif isinstance(body.get("category"), str):
        if body["category"] not in reg.CATEGORY_IDS:
            return 400, {"errors": {"category": "unknown category"}}
        keys = [k for k, e in reg.REGISTRY.items() if e["category"] == body["category"]]
    elif everything:
        keys = list(reg.REGISTRY)
    else:
        return 400, {"errors": {"body": shape}}
    keys = [
        k
        for k in keys
        if (reg.REGISTRY[k]["editable"] or reg.REGISTRY[k].get("legacy_override")) and (writable or not reg.REGISTRY[k]["secret"])
    ]
    clears_connections = everything or body.get("category") == "connections"
    touches_secrets = any(reg.REGISTRY[k]["secret"] for k in keys) or (clears_connections and writable)

    def prepare():
        if not everything:
            return
        for path, unusable in (
            (store.settings_path(environ), bool(store.load(environ).error)),
            (store.secrets_path(environ), bool(store._read_json(store.secrets_path(environ))[1])),
        ):
            if unusable and os.path.exists(path):
                _move_aside(path)

    def build(state):
        plan = {k: ("secret_clear" if reg.REGISTRY[k]["secret"] else "reset", None) for k in keys}
        changed, secret_keys = _apply(state, plan)
        if clears_connections:
            if state.connections:
                state.connections = []
                changed.append("connections")
            if state.stages:
                state.stages = {}
                changed.append("stages")
            if writable and state.conn_keys:
                state.conn_keys = {}
                changed.append("connection keys")
                secret_keys.append("connection keys")
        return changed, secret_keys, {}

    status, payload = _commit(environ, who, build, touches_secrets, prepare if everything else None)
    if status == 200:
        payload["reset"] = payload.pop("changed")
    return status, payload


# --- dispatch -------------------------------------------------------------------------------------------------------------


def handle(method, path, body=None, environ=None, who="admin", opener=None):
    route = (path or "").split("?", 1)[0]
    if method == "GET" and route == "/api/settings/schema":
        return 200, reg.schema()
    if method == "GET" and route == "/api/settings":
        return get_settings(environ)
    if method == "PUT" and route == "/api/settings":
        return put_settings(body, environ, who)
    if method == "POST" and route == "/api/settings/reset":
        return reset_settings(body, environ, who)
    if method == "POST" and route == "/api/settings/test":
        return review_settings.handle(method, route, body, environ=environ, opener=opener)
    return 404, {"error": "no such route"}
