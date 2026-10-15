"""Connections (specs/webui-full-settings, S-8): named LLM connections and the stage each one serves.

A Connection is {name, kind, url, model, extra_body, timeout_connect, timeout_read} in settings.json plus an optional write-only
API key in secrets.json. A stage (repair, restore, verify, decision, acquire) picks one by name. The exporter turns the choice
into the environment variables the pipeline already reads; nothing in the pipeline changes. A stage without a Connection keeps
whatever the container environment says.

The API key never travels in a variable named after the stage's key: the exporter puts it in DT_CONN_KEY_<STAGE> and points the
stage's existing *_KEY_ENV variable at that name, which is how the pipeline already looks a key up."""

import ipaddress
import json
import re
import socket
import urllib.parse

import decision_client
import settings_registry as reg

KINDS = ("llamacpp", "ollama", "openai")
STAGES = ("repair", "restore", "verify", "decision", "acquire")
STAGE_KINDS = {
    "repair": ("llamacpp", "ollama", "openai"),
    "restore": ("llamacpp", "ollama"),
    "verify": ("llamacpp", "ollama", "openai"),
    "decision": ("openai",),
    "acquire": ("llamacpp", "ollama", "openai"),
}
KEY_ENV = {"repair": "DT_CONN_KEY_REPAIR", "verify": "DT_CONN_KEY_VERIFY", "decision": "DT_CONN_KEY_DECISION"}
VIA_DECISION = "@decision"  # verify stage value: adjudicate with the decision stage's Connection
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
EXTRA_BODY_MAX = 2048
TIMEOUT_DEFAULTS = {"timeout_connect": 10.0, "timeout_read": 120.0}
LINK_LOCAL = (ipaddress.ip_network("169.254.0.0/16"), ipaddress.ip_network("fe80::/10"))
NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
METADATA_ADDRESSES = {
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("fd00:ec2::254"),
}
FIELDS = ("name", "kind", "url", "model", "extra_body", "timeout_connect", "timeout_read")
ALLOWED_DECISION_HOSTS = {urllib.parse.urlsplit(u).hostname.lower() for u, _ in decision_client.PROVIDERS.values()} | {
    "127.0.0.1",
    "localhost",
    "::1",
}


def _unwrapped_addresses(addr):
    """Yield addr plus any IPv4 address it wraps via ipv4_mapped, 6to4, or NAT64 (64:ff9b::/96)."""
    yield addr
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        yield mapped
    s24 = getattr(addr, "sixtofour", None)
    if s24 is not None:
        yield s24
    if addr.version == 6 and addr in NAT64_PREFIX:
        yield ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)


def _is_refused_address(addr):
    for item in _unwrapped_addresses(addr):
        if item in METADATA_ADDRESSES:
            return True
        if any(item in net for net in LINK_LOCAL if item.version == net.version):
            return True
    return False


def host_problem(url):
    """Why the host of ``url`` is refused, or "". Link-local and metadata addresses (169.254.0.0/16, fe80::/10,
    100.100.100.200, fd00:ec2::254) are never a Connection target, however they are spelled (dotted, decimal, hex,
    IPv4-mapped, 6to4, NAT64); loopback and LAN hosts are normal."""
    host = urllib.parse.urlsplit(url).hostname or ""
    candidates = []
    try:
        candidates.append(ipaddress.ip_address(host.split("%", 1)[0]))
    except ValueError:
        try:  # legacy IPv4 spellings: 2852039166, 0xA9FEA9FE, 169.254.43518
            candidates.append(ipaddress.ip_address(socket.inet_ntoa(socket.inet_aton(host))))
        except (OSError, ValueError):
            pass
    for address in candidates:
        if _is_refused_address(address):
            return "must not point at a link-local or metadata address (169.254.0.0/16, fe80::/10)"
    return ""


def check_test_target(url):
    """(url, checked_ips, error). Resolves host with getaddrinfo. Refuses if any resolved address
    (including ipv4_mapped, sixtofour, NAT64, or metadata) is link-local or metadata.
    Returns (url, checked_ips, "") on success, keeping the hostname in the URL."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        addrs = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return None, [], f"name resolution failed: {e.strerror or e}"
    if not addrs:
        return None, [], "name resolution returned no addresses"
    checked_ips = []
    for *_, sockaddr in addrs:
        ip = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if _is_refused_address(addr):
            return None, [], "must not point at a link-local or metadata address (169.254.0.0/16, fe80::/10)"
        if ip not in checked_ips:
            checked_ips.append(ip)
    return url, checked_ips, ""


def _number(item, field):
    value = item.get(field, TIMEOUT_DEFAULTS[field])
    if type(value) not in (int, float) or not 1 <= value <= 600:
        raise reg.Invalid(f"{field} must be between 1 and 600 seconds")
    return float(value)


def validate_connection(item):
    """(clean connection dict, {field: message}); the API key is handled by the caller."""
    errors, clean = {}, {}
    if not isinstance(item, dict):
        return {}, {"connection": "must be an object"}
    unknown = sorted(set(item) - set(FIELDS) - {"api_key"})
    if unknown:
        errors["connection"] = f"unknown field: {unknown[0]}"
    name = item.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        errors["name"] = "use letters, digits, . _ - (up to 64 characters)"
    kind = item.get("kind")
    if kind not in KINDS:
        errors["kind"] = "must be llamacpp, ollama or openai"
    url = item.get("url")
    if not isinstance(url, str) or not url.strip():
        errors["url"] = "is required"
    else:
        parts = urllib.parse.urlsplit(url.strip())
        if parts.query or parts.fragment:
            errors["url"] = "must not contain a query or fragment; tokens belong in a secret field"
        else:
            why = reg.url_problem(url.strip()) or host_problem(url.strip())
            if why:
                errors["url"] = why
    model = item.get("model", "")
    if not isinstance(model, str) or (model and not reg.MODEL_RE.fullmatch(model)):
        errors["model"] = "must look like qwen3-4b-instruct"
    extra = item.get("extra_body", {})
    if extra in ("", None):
        extra = {}
    try:
        encoded = json.dumps(extra, sort_keys=True, separators=(",", ":")) if isinstance(extra, dict) else None
    except (TypeError, ValueError):
        encoded = None
    if encoded is None or len(encoded) > EXTRA_BODY_MAX:
        errors["extra_body"] = f"must be a small JSON object (at most {EXTRA_BODY_MAX} characters)"
    elif extra and kind != "openai":
        errors["extra_body"] = "is used only by OpenAI-compatible connections"
    for field in ("timeout_connect", "timeout_read"):
        try:
            clean[field] = _number(item, field)
        except reg.Invalid as e:
            errors[field] = str(e)
    if not errors:
        clean.update(name=name, kind=kind, url=url.strip(), model=model, extra_body=extra)
    return clean, errors


def key_problem(conn, key):
    """Why ``key`` may not be stored for ``conn``, or "". A key is used only by OpenAI-compatible connections and only
    travels over https, or to a loopback host (the rule the pipeline itself applies before sending one)."""
    if not isinstance(key, str) or len(key) < 8 or len(key) > 512 or any(ch.isspace() or ord(ch) < 32 for ch in key):
        return "must be one line of 8 to 512 characters without spaces or control characters"
    if conn["kind"] != "openai":
        return "is used only by OpenAI-compatible connections"
    parts = urllib.parse.urlsplit(conn["url"])
    if parts.scheme != "https" and parts.hostname not in ("127.0.0.1", "localhost", "::1"):
        return "can only be sent over https (plain http is for loopback only)"
    return ""


def validate_stages(stages, connections):
    """{stage: message} for a stage that names no connection, one of the wrong kind, or a combination the pipeline cannot
    honour."""
    errors = {}
    by_name = {c["name"]: c for c in connections}
    for stage, name in stages.items():
        if stage not in STAGES:
            errors[stage] = "unknown stage"
        elif name == VIA_DECISION:
            if stage != "verify":
                errors[stage] = "only verify can follow the decision stage"
            elif "decision" not in stages:
                errors[stage] = "choose a decision connection first"
        elif name not in by_name:
            errors[stage] = "points at a connection that does not exist"
        elif by_name[name]["kind"] not in STAGE_KINDS[stage]:
            errors[stage] = "needs a " + " or ".join(STAGE_KINDS[stage]) + " connection"
        elif stage in ("verify", "decision", "acquire") and by_name[name]["kind"] == "openai" and not by_name[name]["model"]:
            errors[stage] = "needs a connection with a model (the hosted glossary stages have no default)"
        elif stage == "decision":
            d_host = (urllib.parse.urlsplit(by_name[name]["url"]).hostname or "").lower()
            if d_host not in ALLOWED_DECISION_HOSTS:
                errors[stage] = (
                    f"points at a host decision_client.py will not call ({d_host}); "
                    f"allowed hosts are openrouter.ai, api.commandcode.ai, or loopback"
                )
    if not errors:
        verify, acquire = stages.get("verify"), stages.get("acquire")
        if acquire and verify and verify != VIA_DECISION and acquire != verify:
            errors["acquire"] = "shares verify's endpoint settings: pick the same connection, or leave it to follow verify"
        if acquire and verify == VIA_DECISION and by_name[acquire]["kind"] == "openai":
            errors["acquire"] = "needs a llamacpp or ollama connection while verify follows the decision stage"

        # Refuse two different Ollama connections across all five stages
        ollama_conns = []
        for s in STAGES:
            choice = stages.get(s)
            if choice and choice in by_name and by_name[choice]["kind"] == "ollama":
                ollama_conns.append((s, choice))
        if len({c for _, c in ollama_conns}) > 1:
            first_stage, first_name = ollama_conns[0]
            for s, c in ollama_conns[1:]:
                if c != first_name:
                    msg = (
                        f"all stages must share the same Ollama connection "
                        f"(shares {first_stage}'s Ollama address: pick the same connection)"
                    )
                    errors[s] = msg
    return errors


# --- the environment a stage choice stands for -----------------------------------------------------------------------------


def _body(conn):
    return json.dumps(conn["extra_body"], sort_keys=True, separators=(",", ":")) if conn.get("extra_body") else ""


def _stage_env(stage, conn, key, stages):
    kind = conn["kind"]
    if stage == "repair":
        url_var = {"llamacpp": "REPAIR_LLAMACPP_URL", "openai": "REPAIR_OPENAI_URL", "ollama": "OLLAMA_URL"}[kind]
        env = [("REPAIR_BACKEND", kind), (url_var, conn["url"])]
        if conn["model"]:
            env.append(("REPAIR_MODEL", conn["model"]))
        # Always set, empty when unused: the previous provider's routing flags and key pointer must not carry over.
        env += [
            ("REPAIR_EXTRA_BODY", _body(conn) if kind == "openai" else ""),
            ("REPAIR_OPENAI_KEY_ENV", KEY_ENV["repair"] if key else ""),
        ]
        if key:
            env.append((KEY_ENV["repair"], key))
        env += [("REPAIR_TIMEOUT_CONNECT", f"{conn['timeout_connect']:g}"), ("REPAIR_TIMEOUT_READ", f"{conn['timeout_read']:g}")]
        return env
    if stage == "restore":
        env = [("RESTORE_BACKEND", kind), ("RESTORE_LLAMACPP_URL" if kind == "llamacpp" else "OLLAMA_URL", conn["url"])]
        return env + ([("RESTORE_MODEL", conn["model"])] if conn["model"] else [])
    if stage == "verify" or (stage == "acquire" and stages.get("verify") == VIA_DECISION):
        env = [("VERIFY_BACKEND", kind)] if stage == "verify" else []
        url_var = {"llamacpp": "VERIFY_LLAMACPP_URL", "openai": "VERIFY_OPENAI_URL", "ollama": "OLLAMA_URL"}[kind]
        env.append((url_var, conn["url"]))
        if conn["model"]:
            env.append(("VERIFY_MODEL", conn["model"]))
        if kind == "openai":
            env += [("VERIFY_OPENAI_EXTRA_BODY", _body(conn)), ("VERIFY_OPENAI_KEY_ENV", KEY_ENV["verify"] if key else "")]
            if key:
                env.append((KEY_ENV["verify"], key))
        return env
    if stage == "decision":
        env = [("VERIFY_DECISION_URL", conn["url"]), ("VERIFY_DECISION_KEY_ENV", KEY_ENV["decision"] if key else "")]
        if conn["model"]:
            env.append(("VERIFY_DECISION_MODEL", conn["model"]))
        return env + ([(KEY_ENV["decision"], key)] if key else [])
    return []  # acquire following verify: ACQUIRE_BACKEND below is all it adds


KEY_HOLDER_SCOPES = {
    "DT_CONN_KEY_REPAIR": ("merge",),
    "DT_CONN_KEY_VERIFY": ("gen", "merge"),
    "DT_CONN_KEY_DECISION": ("gen", "merge"),
}


def extra_names(scope):
    """The variable names a Connection can set in this scope that are not registry keys: the per-stage key holders. The repair
    key never reaches the generate loop, for the same reason the repair endpoint does not."""
    return sorted(name for name, scopes in KEY_HOLDER_SCOPES.items() if scope in scopes)


def expand(state, scope):
    """[(NAME, value)] the stage choices stand for in this scope, repair and restore last so they win in a merge pass. Names the
    registry does not put in this scope are left out (the generate loop never receives the repair endpoint)."""
    by_name = {c["name"]: c for c in state.connections}
    allowed = set(reg.keys_for_scope(scope)) | set(extra_names(scope))
    out = []
    for stage in ("verify", "decision", "acquire", "restore", "repair"):
        choice = state.stages.get(stage)
        if not choice:
            continue
        if choice == VIA_DECISION:
            out.append(("VERIFY_BACKEND", "decision"))
            continue
        conn = by_name.get(choice)
        if conn is None:
            continue
        env = _stage_env(stage, conn, state.conn_keys.get(choice, ""), state.stages)
        if stage == "acquire":
            env = [("ACQUIRE_BACKEND", conn["kind"])] + env
        out.extend((name, value) for name, value in env if name in allowed)
    return out


def models_url(url):
    """The model-list address of an OpenAI-compatible endpoint, which is what the Test button asks."""
    parts = urllib.parse.urlsplit(url)
    path = parts.path.rstrip("/")
    for tail in ("/chat/completions", "/completions"):
        if path.endswith(tail):
            path = path[: -len(tail)]
            break
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path + "/models", "", ""))


def rules():
    """What the page needs to build the stage pickers without copying these rules: the kinds, and which kinds each stage
    accepts."""
    return {
        "kinds": list(KINDS),
        "stages": [{"id": stage, "kinds": list(STAGE_KINDS[stage])} for stage in STAGES],
        "via_decision": VIA_DECISION,
        "timeout_defaults": dict(TIMEOUT_DEFAULTS),
    }
