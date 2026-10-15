"""Settings API (specs/webui-full-settings, S-3, S-6, S-7): the registry's schema, the effective values with their sources, and
the validated, all-or-nothing writes. Pure functions over an environ mapping and the store; review_server.py only routes.

The role of the caller (user or admin) is enforced before these functions run, by the role table in review_auth.py: the routes
are registered there from ROLE_ENTRIES. The one thing checked here is the secret gate, _secrets_writable()."""

import errno
import http.client
import os
import re
import socket
import urllib.parse
import urllib.request

import review_auth
import review_settings
import settings_connections as conns
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


def public_connection(conn, state):
    """A Connection as the page sees it: every field, and whether a key is stored. Never the key."""
    out = {f: conn.get(f) for f in conns.FIELDS}
    out["url"] = store.redact_url(out["url"]) if out.get("url") else ""
    out["extra_body"] = {"set": bool(out.get("extra_body"))}
    out["api_key"] = {"set": conn["name"] in state.conn_keys}
    return out


def get_settings(environ=None):
    environ = _env(environ)
    state = store.load(environ)
    reports = _reports(environ)
    settings_mtime = _mtime(store.settings_path(environ))
    values = {key: _redact(key, _resolve(key, state, environ, reports, settings_mtime)) for key in reg.REGISTRY}
    return 200, {
        "values": values,
        "connections": [public_connection(c, state) for c in state.connections],
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


def _validate_connections(items):
    """(clean connections, {name: key action}, errors). A key action is ("set", key) or ("clear", None); absent, "" or null mean
    no change."""
    clean, actions, errors, seen = [], {}, {}, set()
    if not isinstance(items, list):
        return [], {}, {"connections": "must be a list"}
    for index, item in enumerate(items):
        conn, problems = conns.validate_connection(item)
        label = (
            item.get("name") if isinstance(item, dict) and isinstance(item.get("name"), str) and item.get("name") else str(index)
        )
        for field, message in problems.items():
            errors[f"connections.{label}.{field}"] = message
        if problems:
            continue
        if conn["name"] in seen:
            errors[f"connections.{label}.name"] = "is already used by another connection"
            continue
        seen.add(conn["name"])
        clean.append(conn)
        raw = item.get("api_key")
        if raw == {"clear": True}:
            actions[conn["name"]] = ("clear", None)
        elif isinstance(raw, str) and raw:
            why = conns.key_problem(conn, raw)
            if why:
                errors[f"connections.{label}.api_key"] = why
            else:
                actions[conn["name"]] = ("set", raw)
        elif raw not in (None, ""):
            errors[f"connections.{label}.api_key"] = 'must be text, or {"clear": true}'
    return clean, actions, errors


def _apply_connections(state, clean, actions):
    """Replace the Connection list. A changed URL or kind drops the stored key unless a key arrives in the same save, so a stolen
    session cannot point a saved key at another host. Returns (changed labels, secret labels, url map)."""
    old = {c["name"]: c for c in state.connections}
    changed, secret_keys, urls = [], [], {}

    def touch(name, key_changed=False):
        label = f"connection:{name}"
        if label not in changed:
            changed.append(label)
        if key_changed:
            secret_keys.append(f"{label}.api_key")

    for conn in clean:
        name, prior, action = conn["name"], old.get(conn["name"]), actions.get(conn["name"])
        extra = conn.get("extra_body")
        if isinstance(extra, dict) and list(extra.keys()) == ["set"] and type(extra.get("set")) is bool:
            conn["extra_body"] = dict(prior.get("extra_body", {})) if prior else {}
        if prior != conn:
            touch(name)
        if prior is None or prior["url"] != conn["url"]:
            urls[f"connection {name}"] = conn["url"]
        orphan = prior is None and action is None
        moved = prior is not None and (prior["url"] != conn["url"] or prior["kind"] != conn["kind"])
        if ((moved or orphan) and action is None) or action == ("clear", None):
            if state.conn_keys.pop(name, None) is not None:
                touch(name, True)
        elif action and action[0] == "set" and state.conn_keys.get(name) != action[1]:
            state.conn_keys[name] = action[1]
            touch(name, True)
    for name in sorted(set(old) - {c["name"] for c in clean}):
        touch(name, state.conn_keys.pop(name, None) is not None)
    state.connections = clean
    return changed, secret_keys, urls


def put_settings(body, environ=None, who="admin"):
    environ = _env(environ)
    if not isinstance(body, dict) or not isinstance(body.get("values", {}), dict):
        return 400, {"errors": {"body": 'send {"values": {KEY: value}}'}}
    extra = sorted(set(body) - {"values", "revision", "connections", "stages"})
    if extra:
        return 400, {"errors": {"body": f"unknown field: {extra[0]}"}}
    if type(body.get("revision")) is not int:
        return 400, {"errors": {"revision": "send the revision you loaded, as an integer"}}
    plan, errors = _validate_values(body.get("values", {}))
    clean, actions = None, {}
    if "connections" in body:
        clean, actions, problems = _validate_connections(body["connections"])
        errors.update(problems)
    stages_in = body.get("stages")
    if stages_in is not None and not (
        isinstance(stages_in, dict)
        and all(isinstance(k, str) and (v is None or isinstance(v, str)) for k, v in stages_in.items())
    ):
        errors["stages"] = "must map a stage to a connection name, or null"
        stages_in = None
    touches_secrets = any(action.startswith("secret") for action, _ in plan.values()) or bool(actions)
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
        if clean is not None:
            more, more_secrets, more_urls = _apply_connections(state, clean, actions)
            changed, secret_keys, urls = changed + more, secret_keys + more_secrets, {**urls, **more_urls}
        if stages_in is not None:
            before = dict(state.stages)
            for stage, name in stages_in.items():
                if name:
                    state.stages[stage] = name
                else:
                    state.stages.pop(stage, None)
            if state.stages != before:
                changed.append("stages")
        if clean is not None or stages_in is not None:
            problems = {f"stages.{k}": v for k, v in conns.validate_stages(state.stages, state.connections).items()}
            if problems:
                return 400, {"errors": problems}
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


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port=None, *, checked_ips=None, **kwargs):
        super().__init__(host, port, **kwargs)
        self._checked_ips = checked_ips or []

    def connect(self):
        port = self.port or 80
        errors = []
        for ip in self._checked_ips:
            try:
                self.sock = socket.create_connection((ip, port), self.timeout, self.source_address)
                try:
                    self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError:
                    pass
                return
            except OSError as e:
                errors.append(e)
        if errors:
            raise errors[-1]
        raise OSError(f"no addresses to connect to for {self.host}")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port=None, *, checked_ips=None, **kwargs):
        super().__init__(host, port, **kwargs)
        self._checked_ips = checked_ips or []

    def connect(self):
        port = self.port or 443
        errors = []
        for ip in self._checked_ips:
            try:
                sock = socket.create_connection((ip, port), self.timeout, self.source_address)
                try:
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError:
                    pass
                server_hostname = self._tunnel_host or self.host
                self.sock = self._context.wrap_socket(sock, server_hostname=server_hostname)
                return
            except OSError as e:
                errors.append(e)
        if errors:
            raise errors[-1]
        raise OSError(f"no addresses to connect to for {self.host}")


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, checked_ips):
        super().__init__()
        self._checked_ips = checked_ips

    def http_open(self, req):
        return self.do_open(
            lambda host, **kw: _PinnedHTTPConnection(host, checked_ips=self._checked_ips, **kw),
            req,
        )


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, checked_ips, context=None):
        super().__init__(context=context)
        self._checked_ips = checked_ips

    def https_open(self, req):
        return self.do_open(
            lambda host, **kw: _PinnedHTTPSConnection(host, checked_ips=self._checked_ips, **kw),
            req,
            context=self._context,
        )


def _pinned_opener(checked_ips, context=None):
    return urllib.request.build_opener(
        _NoRedirectHandler,
        _PinnedHTTPHandler(checked_ips),
        _PinnedHTTPSHandler(checked_ips, context=context),
    ).open


def test_connection(name, environ=None, opener=None, context=None):
    """Probe one saved Connection with its own timeouts and key. Always 200 with {ok, latency_ms, error}; the key is read here
    and travels in the Authorization header only."""
    state = store.load(_env(environ))
    conn = next((c for c in state.connections if c["name"] == name), None) if isinstance(name, str) else None
    if conn is None:
        return 400, {"error": "unknown connection"}
    key = state.conn_keys.get(conn["name"], "")
    if conn["kind"] == "openai":
        if not key:
            return 200, {"ok": False, "latency_ms": 0, "error": "API key not configured"}
        url, headers = conns.models_url(conn["url"]), {"Authorization": f"Bearer {key}"}
    else:
        url, headers = conn["url"], {}
    target_url, checked_ips, problem = conns.check_test_target(url)
    if problem:
        return 200, {"ok": False, "latency_ms": 0, "error": problem}
    if opener is None:
        opener = _pinned_opener(checked_ips, context=context)
    result = review_settings.probe(target_url, headers, key, conn["timeout_connect"], opener)
    return 200, {**result, "error": store.scrub(result["error"], state)}


def request_restart(environ=None, who="admin"):
    """Ask the builder for a soft stop: touch the flag every loop checks between units of work. The episode in flight (a mux
    included) finishes, the loops exit 0, and the container's restart policy brings the container back with a new boot id."""
    from common import boot_id, log

    flag = _env(environ).get("STOP_FLAG") or "/tmp/dubtitlerr.stop"
    try:
        with open(flag, "a"):
            os.utime(flag, None)
    except OSError as e:
        return 500, {"error": f"could not write the stop flag ({e.__class__.__name__})"}
    log(f"review server: restart requested by {who}: soft stop flag written")
    return 202, {"ok": True, "boot_id": boot_id()}


# --- dispatch -------------------------------------------------------------------------------------------------------------


def handle(method, path, body=None, environ=None, who="admin", opener=None, context=None):
    route = (path or "").split("?", 1)[0]
    if method == "GET" and route == "/api/settings/schema":
        return 200, {**reg.schema(), "connections": conns.rules()}
    if method == "GET" and route == "/api/settings":
        return get_settings(environ)
    if method == "PUT" and route == "/api/settings":
        return put_settings(body, environ, who)
    if method == "POST" and route == "/api/settings/reset":
        return reset_settings(body, environ, who)
    if method == "POST" and route == "/api/settings/test":
        if isinstance(body, dict) and "connection" in body:
            return test_connection(body["connection"], environ, opener, context=context)
        return review_settings.handle(method, route, body, environ=environ, opener=opener)
    if method == "POST" and route == "/api/system/restart":
        return request_restart(environ, who)
    return 404, {"error": "no such route"}
