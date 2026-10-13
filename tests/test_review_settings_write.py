"""Runtime settings writes (specs/webui-settings-write): PUT /api/settings, POST /api/settings/reset, the merged GET,
and the safe exporter the shell loops call. Nothing here touches /config: every path is under tmp_path."""

import http.client
import json
import os
import stat
import subprocess
import sys
import threading

import pytest

import review_server as rs
import review_settings
import review_settings_write as w

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = "review-token"
ADMIN = "admin-token"
PROFILES = {
    "local": {"backend": "llamacpp", "url": "http://host.docker.internal:8090/v1/chat/completions"},
    "cloud": {"backend": "openai", "url": "https://api.example.test/v1", "key_env": "CLOUD_API_KEY"},
}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    d = tmp_path / "config"
    d.mkdir()
    monkeypatch.setenv("CONFIG_DIR", str(d))
    monkeypatch.delenv("RUNTIME_ENV_FILE", raising=False)
    monkeypatch.setenv("REPAIR_PROFILES", json.dumps(PROFILES))
    monkeypatch.setenv("GLOSSARY_LOCK_WAIT", "5")
    monkeypatch.setenv("RUNTIME_VERIFY_BACKENDS", "llamacpp,ollama,openai,decision")
    monkeypatch.setenv("RUNTIME_DECISION_MODELS", "typesafe/jev,m-two")
    monkeypatch.setattr(review_settings, "EFFECTIVE_ENV_PATH", str(d / "effective.env"))
    monkeypatch.setenv("REVIEW_TOKEN", TOKEN)
    monkeypatch.setenv("REVIEW_ADMIN_TOKEN", ADMIN)
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    monkeypatch.setattr(rs, "_LOGIN", None)
    return d


def runtime(cfg):
    return cfg / "runtime.env"


def lines(cfg):
    return sorted(runtime(cfg).read_text().splitlines())


# --- PUT: validation ------------------------------------------------------------------------------------------------


def test_a_valid_put_writes_the_file_0664_and_reports_pending(cfg):
    status, payload = w.put_settings({"repair_model": "qwen3-4b-instruct", "require_eng": 0})
    assert status == 200
    assert payload == {"ok": True, "written": {"repair_model": "qwen3-4b-instruct", "require_eng": 0}, "pending": True}
    assert lines(cfg) == ["REPAIR_MODEL=qwen3-4b-instruct", "REQUIRE_ENG=0"]
    assert stat.S_IMODE(runtime(cfg).stat().st_mode) == 0o664


def test_a_later_put_merges_with_what_is_already_there_and_null_clears_a_key(cfg):
    w.put_settings({"repair_model": "a-model", "verify_backend": "openai"})
    status, payload = w.put_settings({"verify_decision_model": "typesafe/jev", "repair_model": None})
    assert status == 200 and payload["written"] == {"verify_decision_model": "typesafe/jev", "repair_model": None}
    assert lines(cfg) == ["VERIFY_BACKEND=openai", "VERIFY_DECISION_MODEL=typesafe/jev"]


def test_an_empty_put_changes_nothing(cfg):
    assert w.put_settings({}) == (200, {"ok": True, "written": {}, "pending": False})
    assert not runtime(cfg).exists()


@pytest.mark.parametrize(
    "key", ["repair_url", "repair_openai_url", "repair_key", "repair_openai_key_env", "merge_roots", "REPAIR_MODEL", "x", ""]
)
def test_unknown_keys_urls_secrets_and_paths_are_refused(cfg, key):
    status, payload = w.put_settings({"repair_model": "ok-model", key: "http://evil.example/"})
    assert (status, payload) == (400, {"error": f"unknown key: {key}"})
    assert not runtime(cfg).exists(), "a refused request writes nothing, not even its valid keys"


HOSTILE = [
    "model\nREPAIR_BACKEND=evil",
    "model\r\nX=1",
    "$(touch /tmp/pwned)",
    "`touch /tmp/pwned`",
    "mo'del",
    'mo"del',
    "mo;del",
    "mo del",
    "mo|del",
    "mo&del",
    "mo>del",
    "mo\\del",
    "-leading-dash",
    ".leading-dot",
    "x" * 129,
    "",
    "mødel",
    "a\x00b",
]


@pytest.mark.parametrize("key", ["repair_model", "verify_decision_model"])
@pytest.mark.parametrize("bad", HOSTILE, ids=[repr(h)[:24] for h in HOSTILE])
def test_hostile_model_names_are_refused(cfg, key, bad):
    assert w.put_settings({key: bad}) == (400, {"error": "invalid model format"})
    assert not runtime(cfg).exists()


@pytest.mark.parametrize("bad", [5, True, ["a"], {"a": 1}, 1.5])
def test_a_non_string_model_is_refused(cfg, bad):
    assert w.put_settings({"repair_model": bad}) == (400, {"error": "invalid model format"})


@pytest.mark.parametrize("good", ["a", "qwen3-4b-instruct", "typesafe/jev", "LongCat-2.0", "org/model:tag_v1.2", "x" * 128])
def test_ordinary_model_names_are_accepted(cfg, good):
    assert w.put_settings({"repair_model": good})[0] == 200


def test_the_profile_must_be_one_the_server_defines(cfg):
    assert w.put_settings({"repair_profile": "attacker"}) == (400, {"error": "unknown repair profile"})
    assert w.put_settings({"repair_profile": 5}) == (400, {"error": "unknown repair profile"})
    assert w.put_settings({"repair_profile": "cloud"})[0] == 200
    assert lines(cfg) == ["REPAIR_PROFILE=cloud"], "the file holds the NAME only: no url, no key name"


def test_the_writer_never_puts_a_url_or_key_name_in_the_file(cfg):
    w.put_settings({"repair_profile": "cloud", "repair_model": "m"})
    text = runtime(cfg).read_text()
    assert "http" not in text and "CLOUD_API_KEY" not in text


def test_verify_backend_and_require_eng_are_checked(cfg):
    for bad in ("", 5, "OPENAI", "openai; x", "llama.cpp", "ollama ", "ollama\n"):
        assert w.put_settings({"verify_backend": bad})[0] == 400
    for bad in (2, -1, "1", True, 1.0, None.__class__):
        assert w.put_settings({"require_eng": bad})[0] == 400
    for good in ("llamacpp", "ollama", "openai", "decision"):
        assert w.put_settings({"verify_backend": good})[0] == 200
    assert w.put_settings({"require_eng": 1})[0] == 200


def test_invalid_repair_profiles_json_disables_writes_and_says_why(cfg, monkeypatch):
    monkeypatch.setenv("REPAIR_PROFILES", "{not json")
    info = w.writable_info()
    assert info["writable"] is False and "REPAIR_PROFILES" in info["reason"]
    status, payload = w.put_settings({"repair_model": "ok"})
    assert status == 503 and "REPAIR_PROFILES" in payload["error"]
    assert not runtime(cfg).exists()


@pytest.mark.parametrize(
    "bad",
    [
        "[]",
        '{"p": "x"}',
        '{"p": {"backend": "ollama", "url": "http://h/"}}',
        '{"p": {"backend": "llamacpp", "url": "file:///etc/passwd"}}',
        '{"p": {"backend": "llamacpp", "url": "http://h/ x"}}',
        '{"p": {"backend": "openai", "url": "http://h/", "key_env": "bad name"}}',
        '{"bad name": {"backend": "llamacpp", "url": "http://h/"}}',
    ],
)
def test_a_malformed_profile_table_disables_writes(cfg, monkeypatch, bad):
    monkeypatch.setenv("REPAIR_PROFILES", bad)
    assert w.writable_info()["writable"] is False


def test_no_profiles_defined_is_fine_but_the_profile_key_has_nothing_to_pick(cfg, monkeypatch):
    monkeypatch.delenv("REPAIR_PROFILES")
    assert w.writable_info() == {"writable": True}
    assert w.put_settings({"repair_model": "ok"})[0] == 200
    assert w.put_settings({"repair_profile": "local"}) == (400, {"error": "unknown repair profile"})


def test_an_unwritable_config_directory_is_reported_not_writable(cfg, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(cfg / "missing"))
    info = w.writable_info()
    assert info["writable"] is False and "not writable" in info["reason"]
    assert w.put_settings({"repair_model": "ok"})[0] == 503


# --- PUT: file safety -----------------------------------------------------------------------------------------------


def test_the_previous_file_is_kept_as_prev(cfg):
    w.put_settings({"repair_model": "first-model"})
    assert not (cfg / "runtime.env.prev").exists(), "nothing to preserve on the first write"
    w.put_settings({"repair_model": "second-model"})
    assert (cfg / "runtime.env.prev").read_text() == "REPAIR_MODEL=first-model\n"
    assert lines(cfg) == ["REPAIR_MODEL=second-model"]


def test_a_failed_replace_leaves_the_file_and_no_temp_behind(cfg, monkeypatch):
    w.put_settings({"repair_model": "first-model"})
    before = runtime(cfg).read_bytes()

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    status, payload = w.put_settings({"repair_model": "second-model"})
    assert status == 500 and "error" in payload
    assert runtime(cfg).read_bytes() == before
    assert sorted(p.name for p in cfg.iterdir() if p.name.startswith(".")) == []


def test_concurrent_puts_keep_a_valid_file_with_every_key(cfg):
    errors = []
    bodies = [
        {"repair_model": "m-one"},
        {"verify_decision_model": "m-two"},
        {"verify_backend": "openai"},
        {"require_eng": 0},
        {"repair_profile": "local"},
    ] * 4

    def go(body):
        try:
            status, _ = w.put_settings(body)
            assert status == 200
        except Exception as e:  # noqa: BLE001 - report from the thread
            errors.append(e)

    threads = [threading.Thread(target=go, args=(b,)) for b in bodies]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    assert lines(cfg) == [
        "REPAIR_MODEL=m-one",
        "REPAIR_PROFILE=local",
        "REQUIRE_ENG=0",
        "VERIFY_BACKEND=openai",
        "VERIFY_DECISION_MODEL=m-two",
    ]


def test_the_audit_line_names_keys_never_values(cfg, capsys):
    w.put_settings({"repair_model": "very-secret-looking-model", "require_eng": 1})
    out = capsys.readouterr().out
    line = [ln for ln in out.splitlines() if "settings updated by admin" in ln]
    assert line == ["review server: settings updated by admin: keys=repair_model,require_eng"]
    assert "very-secret-looking-model" not in out


def test_a_refused_put_logs_no_audit_line(cfg, capsys):
    w.put_settings({"repair_model": "bad model"})
    assert "settings updated" not in capsys.readouterr().out


# --- reset ----------------------------------------------------------------------------------------------------------


def test_reset_keeps_a_copy_as_prev_and_removes_the_file(cfg, capsys):
    w.put_settings({"repair_model": "to-be-reset"})
    status, payload = w.reset_settings()
    assert (status, payload["ok"]) == (200, True)
    assert not runtime(cfg).exists()
    assert (cfg / "runtime.env.prev").read_text() == "REPAIR_MODEL=to-be-reset\n"
    assert "settings reset by admin: keys=repair_model" in capsys.readouterr().out


def test_reset_with_nothing_to_reset_is_ok(cfg):
    assert w.reset_settings()[0] == 200
    assert not runtime(cfg).exists()


# --- GET: profiles, pending, writable ------------------------------------------------------------------------------


def test_get_gains_profiles_pending_and_writable(cfg):
    status, base = review_settings.handle("GET", "/api/settings")
    status, payload = w.augment_get(status, base)
    assert status == 200
    assert payload["profiles"] == ["cloud", "local"]
    assert payload["pending"] == {} and payload["writable"] is True
    assert payload["settings"] == base["settings"], "the existing payload is kept intact"


def test_pending_lists_keys_whose_runtime_value_differs_from_effective(cfg):
    (cfg / "effective.env").write_text("REPAIR_MODEL=old-model\nVERIFY_BACKEND=llamacpp\nREQUIRE_ENG=1\n")
    w.put_settings({"repair_model": "new-model", "verify_backend": "llamacpp", "require_eng": 1})
    _, payload = w.augment_get(*review_settings.handle("GET", "/api/settings"))
    assert payload["pending"] == {"repair_model": "new-model"}, "equal values are already in effect"


def test_pending_compares_a_profile_by_its_backend_and_url(cfg):
    eff = cfg / "effective.env"
    eff.write_text(f"REPAIR_BACKEND=llamacpp\nREPAIR_LLAMACPP_URL={PROFILES['local']['url']}\n")
    w.put_settings({"repair_profile": "local"})
    assert w.augment_get(*review_settings.handle("GET", "/api/settings"))[1]["pending"] == {}
    w.put_settings({"repair_profile": "cloud"})
    assert w.augment_get(*review_settings.handle("GET", "/api/settings"))[1]["pending"] == {"repair_profile": "cloud"}


def test_everything_is_pending_when_the_builder_has_not_reported_yet(cfg, monkeypatch):
    monkeypatch.delenv("REPAIR_MODEL", raising=False)
    w.put_settings({"repair_model": "m"})
    assert w.augment_get(*review_settings.handle("GET", "/api/settings"))[1]["pending"] == {"repair_model": "m"}


def test_get_never_returns_profile_urls_or_key_names(cfg):
    w.put_settings({"repair_profile": "cloud"})
    _, payload = w.augment_get(*review_settings.handle("GET", "/api/settings"))
    text = json.dumps(payload)
    assert "api.example.test" not in text and "CLOUD_API_KEY" not in text


def test_get_says_why_when_writes_are_disabled(cfg, monkeypatch):
    monkeypatch.setenv("REPAIR_PROFILES", "{nope")
    _, payload = w.augment_get(*review_settings.handle("GET", "/api/settings"))
    assert payload["writable"] is False and "REPAIR_PROFILES" in payload["writable_reason"]
    assert payload["profiles"] == []


def test_augment_leaves_errors_alone(cfg):
    assert w.augment_get(404, {"error": "x"}) == (404, {"error": "x"})


# --- the exporter: parse in Python, emit only allow-listed, validated, quoted assignments ---------------------------


def run_export(cfg, content, *extra, env=None):
    if content is not None:
        runtime(cfg).write_text(content)
    e = {**os.environ, "CONFIG_DIR": str(cfg), "REPAIR_PROFILES": json.dumps(PROFILES), **(env or {})}
    return subprocess.run(
        [sys.executable, os.path.join(REPO, "review_settings_write.py"), "export", *extra],
        capture_output=True,
        text=True,
        env=e,
        timeout=30,
    )


def shell_env(cfg, content, marker, extra_env=None):
    """Apply the exporter's output the way the loops do (eval in sh) and return the resulting environment."""
    runtime(cfg).write_text(content)
    script = (
        f'eval "$({sys.executable} {REPO}/review_settings_write.py export)"; '
        'printf "%s\\n" "REPAIR_MODEL=$REPAIR_MODEL" "REPAIR_BACKEND=$REPAIR_BACKEND" "REQUIRE_ENG=$REQUIRE_ENG" '
        '"VERIFY_BACKEND=$VERIFY_BACKEND" "VERIFY_DECISION_MODEL=$VERIFY_DECISION_MODEL" '
        '"REPAIR_LLAMACPP_URL=$REPAIR_LLAMACPP_URL" "REPAIR_OPENAI_URL=$REPAIR_OPENAI_URL" '
        '"REPAIR_OPENAI_KEY_ENV=$REPAIR_OPENAI_KEY_ENV" "LD_PRELOAD=$LD_PRELOAD" "MARK=$MARK"'
    )
    env = {k: v for k, v in os.environ.items() if k not in ("REPAIR_MODEL", "REPAIR_BACKEND", "REQUIRE_ENG")}
    env.update({"CONFIG_DIR": str(cfg), "REPAIR_PROFILES": json.dumps(PROFILES), "MARK": "untouched", **(extra_env or {})})
    out = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, env=env, timeout=30, cwd=str(cfg))
    assert out.returncode == 0, out.stderr
    return dict(line.split("=", 1) for line in out.stdout.splitlines()), out


def test_export_emits_exported_quoted_assignments_for_valid_keys(cfg):
    res = run_export(cfg, "REPAIR_MODEL=qwen3-4b-instruct\nREQUIRE_ENG=0\nVERIFY_BACKEND=openai\n")
    assert res.returncode == 0
    assert sorted(res.stdout.splitlines()) == [
        "export REPAIR_MODEL=qwen3-4b-instruct",
        "export REQUIRE_ENG=0",
        "export VERIFY_BACKEND=openai",
    ]


def test_export_plain_drops_the_export_word(cfg):
    res = run_export(cfg, "REPAIR_MODEL=a-b\n", "--plain")
    assert res.stdout.splitlines() == ["REPAIR_MODEL=a-b"]


def test_export_expands_a_profile_from_the_server_table_only(cfg):
    blanks = ["export REPAIR_EXTRA_BODY=''", "export REPAIR_MODEL_SECONDARY=''"]
    local = run_export(cfg, "REPAIR_PROFILE=local\n").stdout.splitlines()
    assert sorted(local) == sorted(
        [
            "export REPAIR_BACKEND=llamacpp",
            f"export REPAIR_LLAMACPP_URL={PROFILES['local']['url']}",
            "export REPAIR_OPENAI_KEY_ENV=''",
            *blanks,
        ]
    )
    cloud = run_export(cfg, "REPAIR_PROFILE=cloud\n").stdout.splitlines()
    assert sorted(cloud) == sorted(
        [
            "export REPAIR_BACKEND=openai",
            "export REPAIR_OPENAI_URL=https://api.example.test/v1",
            "export REPAIR_OPENAI_KEY_ENV=CLOUD_API_KEY",
            *blanks,
        ]
    )


def test_export_skips_an_unknown_profile_or_a_broken_table_but_keeps_the_rest(cfg):
    res = run_export(cfg, "REPAIR_PROFILE=gone\nREPAIR_MODEL=ok-model\n")
    assert res.stdout.splitlines() == ["export REPAIR_MODEL=ok-model"]
    res = run_export(cfg, "REPAIR_PROFILE=local\nREPAIR_MODEL=ok-model\n", env={"REPAIR_PROFILES": "{broken"})
    assert res.stdout.splitlines() == ["export REPAIR_MODEL=ok-model"]


def test_export_with_no_file_or_an_empty_one_prints_nothing_and_succeeds(cfg):
    assert run_export(cfg, None).returncode == 0 and run_export(cfg, None).stdout == ""
    assert run_export(cfg, "").stdout == ""
    assert run_export(cfg, "# only a comment\n\n").stdout == ""


def test_export_file_option_reads_another_path(cfg, tmp_path):
    other = tmp_path / "elsewhere.env"
    other.write_text("REPAIR_MODEL=from-other\n")
    assert run_export(cfg, None, "--file", str(other)).stdout.splitlines() == ["export REPAIR_MODEL=from-other"]


def test_export_unknown_subcommand_is_a_usage_error(cfg):
    res = subprocess.run(
        [sys.executable, os.path.join(REPO, "review_settings_write.py"), "frobnicate"], capture_output=True, text=True
    )
    assert res.returncode == 2


HAND_EDITED = (
    """\
# a hand-edited file
REPAIR_MODEL=$(touch MARKER_CMDSUB)
REPAIR_MODEL=`touch MARKER_BACKTICK`
VERIFY_DECISION_MODEL=ok;touch MARKER_SEMI
VERIFY_DECISION_MODEL=a b
REPAIR_BACKEND=evil
REPAIR_LLAMACPP_URL=http://evil.example/
REPAIR_OPENAI_KEY_ENV=HOME
LD_PRELOAD=/tmp/evil.so
PATH=/tmp/evil
MARK=changed
touch MARKER_BARE
export REPAIR_MODEL='quoted'
REPAIR_MODEL="dq"
REPAIR_MODEL=ok-first
REPAIR_MODEL=with\\
newline-continuation
REQUIRE_ENG=2
REQUIRE_ENG=0
VERIFY_BACKEND=openai\r
\x00NUL=1
REPAIR_MODEL="""
    + ("x" * 500)
    + """
"""
)


def test_a_hostile_hand_edited_file_cannot_inject_anything(cfg):
    env, out = shell_env(cfg, HAND_EDITED, "marker")
    for marker in ("MARKER_CMDSUB", "MARKER_BACKTICK", "MARKER_SEMI", "MARKER_BARE"):
        assert not (cfg / marker).exists(), f"{marker} was executed"
    assert env["LD_PRELOAD"] == "" and env["MARK"] == "untouched"
    assert env["REPAIR_BACKEND"] == "" and env["REPAIR_LLAMACPP_URL"] == "" and env["REPAIR_OPENAI_KEY_ENV"] == ""
    assert env["VERIFY_DECISION_MODEL"] == ""
    assert env["REQUIRE_ENG"] == "0", "the later valid line wins over the invalid one before it"
    assert env["VERIFY_BACKEND"] == "openai", "a CRLF line ending is tolerated"
    assert env["REPAIR_MODEL"] == "ok-first", "quoted, continued and oversize lines are all skipped"


def test_every_exported_line_is_allow_listed_and_matches_the_validators(cfg):
    res = run_export(cfg, HAND_EDITED)
    assert res.returncode == 0
    names = {ln.split("=", 1)[0].removeprefix("export ") for ln in res.stdout.splitlines()}
    assert names <= {"REPAIR_MODEL", "REQUIRE_ENG", "VERIFY_BACKEND", "VERIFY_DECISION_MODEL"}
    assert all(ln.startswith("export ") for ln in res.stdout.splitlines())


def test_an_exported_value_with_odd_but_valid_characters_is_shell_quoted(cfg):
    env, _ = shell_env(cfg, "REPAIR_MODEL=org/model:tag_v1.2\n", "m")
    assert env["REPAIR_MODEL"] == "org/model:tag_v1.2"


def test_the_exporter_swallows_its_own_errors_so_a_loop_never_dies(cfg):
    runtime(cfg).write_bytes(b"\xff\xfe REPAIR_MODEL=x\n\x80")
    res = run_export(cfg, None)
    assert res.returncode == 0 and res.stdout == ""
    d = cfg / "dirinplace"
    d.mkdir()
    res = run_export(cfg, None, "--file", str(d))
    assert res.returncode == 0 and res.stdout == ""


# --- routes ---------------------------------------------------------------------------------------------------------


def test_put_route_auth_matrix(cfg):
    body = {"repair_model": "a-model"}
    assert rs.route("PUT", "/api/settings", body, None)[0] == 401
    assert rs.route("PUT", "/api/settings", body, "wrong", admin_token=ADMIN)[0] == 401
    assert rs.route("PUT", "/api/settings", body, TOKEN) == (403, {"error": "admin token required"})
    assert rs.route("PUT", "/api/settings", body, TOKEN, admin_token="bad")[0] == 403
    assert not runtime(cfg).exists()
    status, payload = rs.route("PUT", "/api/settings", body, TOKEN, admin_token=ADMIN)
    assert (status, payload["ok"]) == (200, True) and runtime(cfg).exists()


def test_reset_route_auth_matrix(cfg):
    w.put_settings({"repair_model": "a-model"})
    assert rs.route("POST", "/api/settings/reset", {}, None)[0] == 401
    assert rs.route("POST", "/api/settings/reset", {}, "wrong", admin_token=ADMIN)[0] == 401
    assert rs.route("POST", "/api/settings/reset", {}, TOKEN)[0] == 403
    assert rs.route("POST", "/api/settings/reset", {}, TOKEN, admin_token="bad")[0] == 403
    assert runtime(cfg).exists()
    assert rs.route("POST", "/api/settings/reset", {}, TOKEN, admin_token=ADMIN)[0] == 200
    assert not runtime(cfg).exists()


def test_both_routes_are_disabled_without_an_admin_token(cfg, monkeypatch):
    monkeypatch.delenv("REVIEW_ADMIN_TOKEN")
    disabled = (403, {"error": "admin writes are disabled"})
    assert rs.route("PUT", "/api/settings", {"repair_model": "m"}, TOKEN, admin_token=ADMIN) == disabled
    assert rs.route("POST", "/api/settings/reset", {}, TOKEN, admin_token=ADMIN) == disabled


def test_put_route_surfaces_validation_errors(cfg):
    kw = dict(admin_token=ADMIN)
    assert rs.route("PUT", "/api/settings", {"nope": 1}, TOKEN, **kw) == (400, {"error": "unknown key: nope"})
    assert rs.route("PUT", "/api/settings", {"repair_model": "a b"}, TOKEN, **kw) == (400, {"error": "invalid model format"})


def test_get_route_returns_the_merged_payload(cfg):
    status, payload = rs.route("GET", "/api/settings", {}, TOKEN)
    assert status == 200
    assert {"settings", "secrets", "source", "profiles", "pending", "writable"} <= set(payload)
    assert payload["profiles"] == ["cloud", "local"]
    assert rs.route("GET", "/api/settings", {}, None)[0] == 401


def test_the_settings_routes_do_not_change_open_routes():
    assert set(rs.OPEN_ROUTES) == {("GET", "/healthz"), ("GET", "/api/auth-mode"), ("POST", "/api/login")}


@pytest.fixture
def server(cfg):
    srv = rs.BoundedHTTPServer(("127.0.0.1", 0), rs.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def send(srv, method, path, raw, headers=None):
    conn = http.client.HTTPConnection(*srv.server_address, timeout=5)
    conn.request(method, path, body=raw, headers={"Content-Type": "application/json", **(headers or {})})
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, (json.loads(body) if body else {})


def test_http_put_with_both_tokens_and_garbage_json(server, cfg):
    auth = {rs.TOKEN_HEADER: TOKEN, "X-Review-Admin-Token": ADMIN}
    assert send(server, "PUT", "/api/settings", b'{"repair_model": "http-model"}', auth)[0] == 200
    assert "REPAIR_MODEL=http-model" in lines(cfg)
    assert send(server, "PUT", "/api/settings", b"{not json", auth) == (400, {"error": "invalid JSON"})
    assert send(server, "PUT", "/api/settings", b"{not json", {rs.TOKEN_HEADER: TOKEN})[0] == 403
    assert send(server, "POST", "/api/settings/reset", b"", auth)[0] == 200
    assert not runtime(cfg).exists()


def test_the_verify_backend_list_matches_the_pipeline_exactly():
    """The writer must accept exactly what glossary_verify does (a drift here lets the UI save a value the verify stage
    then rejects, or refuses one it would take). Imported here, not in the writer, so the exporter the loops run on
    every pass stays free of the verify stage's heavy imports."""
    import glossary_verify

    assert tuple(w.VERIFY_BACKENDS) == tuple(glossary_verify.VERIFY_BACKENDS)
    assert "ollama" in w.VERIFY_BACKENDS


def test_ollama_round_trips_through_put_and_export(cfg):
    assert w.put_settings({"verify_backend": "ollama"})[0] == 200
    assert run_export(cfg, None).stdout.splitlines() == ["export VERIFY_BACKEND=ollama"]


# =============================== round 6 (reviewer-settings-write) =====================================================

OPEN_ENV = {"RUNTIME_VERIFY_BACKENDS": "llamacpp,ollama,openai,decision", "RUNTIME_DECISION_MODELS": "typesafe/jev,m-two"}


@pytest.fixture
def default_allowlists(monkeypatch):
    monkeypatch.delenv("RUNTIME_VERIFY_BACKENDS", raising=False)
    monkeypatch.delenv("RUNTIME_DECISION_MODELS", raising=False)


# --- M2: a profile URL cannot carry shell syntax, and quoting is what protects the legal-but-odd ones ----------------


@pytest.mark.parametrize(
    "url",
    [
        "http://h/$(touch MARKER)",
        "http://h/`touch MARKER`",
        "http://h/a(b)",
        "http://h/a;touch MARKER",
        "http://h/$HOME",
        "http://h/a'b",
        "http://h/a b",
        "http://h/a|b",
    ],
)
def test_profile_urls_with_shell_syntax_make_the_table_unusable(cfg, monkeypatch, url):
    monkeypatch.setenv("REPAIR_PROFILES", json.dumps({"p": {"backend": "llamacpp", "url": url}}))
    info = w.writable_info()
    assert info["writable"] is False and "REPAIR_PROFILES" in info["reason"]


def test_a_legal_url_with_shell_special_characters_reaches_the_shell_exactly_and_runs_nothing(cfg, tmp_path):
    """& * ! # ? [ ] = , + @ are all legal in a URL. Unquoted, `&touch` would start a command; the exporter's quoting is the
    only thing stopping it, so run the real output through sh with a bait `touch` on PATH."""
    url = "http://h/p&touch?a=1&b=*!#[x],+@y"
    bait = tmp_path / "bait"
    bait.mkdir()
    marker = tmp_path / "BAIT_RAN"
    fake = bait / "touch"
    fake.write_text(f"#!/bin/sh\necho ran > {marker}\n")
    fake.chmod(0o755)
    runtime(cfg).write_text("REPAIR_PROFILE=odd\n")
    table = json.dumps({"odd": {"backend": "llamacpp", "url": url}})
    script = f'eval "$({sys.executable} {REPO}/review_settings_write.py export)"; printf "%s" "$REPAIR_LLAMACPP_URL"'
    env = {**os.environ, "CONFIG_DIR": str(cfg), "REPAIR_PROFILES": table, "PATH": f"{bait}{os.pathsep}{os.environ['PATH']}"}
    res = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=30)
    assert res.returncode == 0, res.stderr
    assert res.stdout == url, "the URL arrives byte for byte"
    assert not marker.exists(), "an unquoted `&touch` ran the bait command"


def test_the_exporter_quotes_every_value(cfg):
    out = w.format_assignments([("REPAIR_LLAMACPP_URL", "http://h/a&b"), ("REPAIR_MODEL", "plain")])
    assert out == "export REPAIR_LLAMACPP_URL='http://h/a&b'\nexport REPAIR_MODEL=plain\n"


# --- M3: a profile replaces the whole repair endpoint ---------------------------------------------------------------


def test_the_module_says_a_profile_replaces_the_whole_repair_endpoint():
    assert "replaces the whole repair endpoint" in w.__doc__


def test_a_profile_without_key_env_blanks_the_key_pointer_and_the_extras(cfg):
    out = run_export(cfg, "REPAIR_PROFILE=local\n").stdout.splitlines()
    assert "export REPAIR_OPENAI_KEY_ENV=''" in out
    assert "export REPAIR_EXTRA_BODY=''" in out
    assert "export REPAIR_MODEL_SECONDARY=''" in out


def test_a_profile_can_carry_extra_body_and_a_secondary_model(cfg):
    table = {
        "p": {
            "backend": "openai",
            "url": "https://x.example/v1",
            "key_env": "K_ENV",
            "extra_body": {"provider": {"only": ["a"]}},
            "model_secondary": "sec/model-2",
        }
    }
    out = run_export(cfg, "REPAIR_PROFILE=p\n", env={"REPAIR_PROFILES": json.dumps(table)}).stdout.splitlines()
    assert "export REPAIR_OPENAI_KEY_ENV=K_ENV" in out
    assert "export REPAIR_MODEL_SECONDARY=sec/model-2" in out
    body = next(ln for ln in out if ln.startswith("export REPAIR_EXTRA_BODY="))
    assert json.loads(shlex_split_value(body)) == {"provider": {"only": ["a"]}}


def shlex_split_value(line):
    import shlex

    return shlex.split(line.removeprefix("export ").split("=", 1)[1])[0]


@pytest.mark.parametrize(
    "bad",
    [
        {"extra_body": "not an object"},
        {"extra_body": ["a"]},
        {"extra_body": {"k": "x" * 4000}},
        {"model_secondary": "bad model"},
        {"model_secondary": 5},
    ],
)
def test_malformed_profile_extras_make_the_table_unusable(cfg, monkeypatch, bad):
    table = {"p": {"backend": "openai", "url": "https://x.example/v1", **bad}}
    monkeypatch.setenv("REPAIR_PROFILES", json.dumps(table))
    assert w.writable_info()["writable"] is False


def test_switching_to_a_keyless_profile_does_not_send_the_containers_key_to_it(cfg, tmp_path):
    table = {"lab": {"backend": "openai", "url": "https://lab.example/v1"}}
    runtime(cfg).write_text("REPAIR_PROFILE=lab\n")
    script = (
        f'eval "$({sys.executable} {REPO}/review_settings_write.py export)"; '
        'printf "%s|%s|%s" "$REPAIR_OPENAI_KEY_ENV" "$REPAIR_EXTRA_BODY" "$REPAIR_MODEL_SECONDARY"'
    )
    env = {
        **os.environ,
        "CONFIG_DIR": str(cfg),
        "REPAIR_PROFILES": json.dumps(table),
        "REPAIR_OPENAI_KEY_ENV": "OPENROUTER_KEY",
        "REPAIR_EXTRA_BODY": '{"provider":"old"}',
        "REPAIR_MODEL_SECONDARY": "old/secondary",
    }
    res = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, env=env, timeout=30)
    assert res.stdout == "||", res.stdout


# --- M4: --scope gen leaves the repair endpoint to merge_pass ---------------------------------------------------------

ALL_KEYS = (
    "REPAIR_PROFILE=local\nREPAIR_MODEL=a-model\nVERIFY_BACKEND=openai\nVERIFY_DECISION_MODEL=typesafe/jev\nREQUIRE_ENG=0\n"
)


def exported_names(res):
    return [ln.split("=", 1)[0].removeprefix("export ") for ln in res.stdout.splitlines()]


def test_the_default_scope_is_merge_and_emits_everything(cfg, monkeypatch):
    for k, v in OPEN_ENV.items():
        monkeypatch.setenv(k, v)
    merge = exported_names(run_export(cfg, ALL_KEYS))
    assert exported_names(run_export(cfg, None, "--scope", "merge")) == merge
    assert {"REPAIR_BACKEND", "REPAIR_LLAMACPP_URL", "REPAIR_OPENAI_KEY_ENV", "REPAIR_MODEL", "REQUIRE_ENG"} <= set(merge)


def test_gen_scope_emits_only_the_four_plain_settings(cfg, monkeypatch):
    for k, v in OPEN_ENV.items():
        monkeypatch.setenv(k, v)
    for form in (["--scope", "gen"], ["--scope=gen"]):
        res = run_export(cfg, ALL_KEYS, *form)
        assert res.returncode == 0
        assert sorted(exported_names(res)) == ["REPAIR_MODEL", "REQUIRE_ENG", "VERIFY_BACKEND", "VERIFY_DECISION_MODEL"]
        assert "http" not in res.stdout and "REPAIR_BACKEND" not in res.stdout


def test_gen_scope_never_applies_a_profile_even_when_that_is_all_there_is(cfg):
    assert run_export(cfg, "REPAIR_PROFILE=local\n", "--scope", "gen").stdout == ""


def test_an_unknown_scope_is_a_usage_error(cfg):
    assert run_export(cfg, None, "--scope", "everything").returncode == 2
    assert run_export(cfg, None, "--scope").returncode == 2


# --- M5: verify backend and decision model are opt-in ---------------------------------------------------------------


def test_by_default_only_the_local_verify_backends_are_allowed(cfg, default_allowlists):
    assert w.put_settings({"verify_backend": "llamacpp"})[0] == 200
    assert w.put_settings({"verify_backend": "ollama"})[0] == 200
    for backend in ("openai", "decision"):
        status, payload = w.put_settings({"verify_backend": backend})
        assert status == 400 and "RUNTIME_VERIFY_BACKENDS" in payload["error"]
    assert lines(cfg) == ["VERIFY_BACKEND=ollama"]


def test_an_openrouter_model_id_is_refused_by_default(cfg, default_allowlists):
    status, payload = w.put_settings({"verify_decision_model": "openai/gpt-6-luna-decisions"})
    assert status == 400 and "RUNTIME_DECISION_MODELS" in payload["error"]
    assert not runtime(cfg).exists()


def test_clearing_a_verify_key_is_always_allowed(cfg, default_allowlists):
    w.put_settings({"verify_backend": "ollama"})
    assert w.put_settings({"verify_backend": None, "verify_decision_model": None})[0] == 200
    assert lines(cfg) == []


def test_the_operator_opts_models_and_backends_in_through_the_environment(cfg, monkeypatch):
    monkeypatch.setenv("RUNTIME_VERIFY_BACKENDS", "decision")
    monkeypatch.setenv("RUNTIME_DECISION_MODELS", "typesafe/jev, other/m-2 ,")
    assert w.put_settings({"verify_backend": "decision", "verify_decision_model": "other/m-2"})[0] == 200
    assert w.put_settings({"verify_backend": "llamacpp"})[0] == 400, "a set list replaces the default, it does not add to it"
    assert w.put_settings({"verify_decision_model": "typesafe/jev2"})[0] == 400, "exact ids only"


def test_the_allow_lists_ignore_entries_that_are_not_valid_values(cfg, monkeypatch):
    monkeypatch.setenv("RUNTIME_VERIFY_BACKENDS", "ollama,ollama2,bad value,")
    monkeypatch.setenv("RUNTIME_DECISION_MODELS", "ok/model,bad model;x,$(x)")
    assert w.allowed_verify_backends() == ("ollama",)
    assert w.allowed_decision_models() == ("ok/model",)


def test_get_returns_the_allowed_lists_for_the_ui(cfg, default_allowlists):
    _, payload = w.augment_get(*review_settings.handle("GET", "/api/settings"))
    assert payload["allowed_verify_backends"] == ["llamacpp", "ollama"]
    assert payload["allowed_decision_models"] == []


def test_a_hand_edited_runtime_file_cannot_get_around_the_allow_lists(cfg, default_allowlists):
    res = run_export(cfg, "VERIFY_BACKEND=decision\nVERIFY_DECISION_MODEL=openai/gpt-6-luna-decisions\nREPAIR_MODEL=ok\n")
    assert res.stdout.splitlines() == ["export REPAIR_MODEL=ok"]
    assert "RUNTIME_VERIFY_BACKENDS" in res.stderr or "not allowed" in res.stderr


def test_a_disallowed_stored_value_is_not_reported_as_an_override_or_pending(cfg, default_allowlists):
    runtime(cfg).write_text("VERIFY_BACKEND=decision\nREPAIR_MODEL=ok\n")
    _, payload = w.augment_get(*review_settings.handle("GET", "/api/settings"))
    assert "verify_backend" not in payload["overrides"] and "verify_backend" not in payload["pending"]


def test_the_spec_and_compose_name_the_allow_lists():
    spec = open(os.path.join(REPO, "specs/webui-settings-write/spec.md")).read()
    compose = open(os.path.join(REPO, "compose.yaml")).read()
    for name in ("RUNTIME_VERIFY_BACKENDS", "RUNTIME_DECISION_MODELS"):
        assert name in spec and name in compose


# --- L1: after a reset, the keys that revert are pending ----------------------------------------------------------------


def test_after_a_reset_the_reverting_keys_are_pending(cfg, monkeypatch):
    monkeypatch.setenv("REPAIR_MODEL", "container-model")
    monkeypatch.delenv("VERIFY_BACKEND", raising=False)
    w.put_settings({"repair_model": "new-m", "verify_backend": "ollama"})
    (cfg / "effective.env").write_text("REPAIR_MODEL=new-m\nVERIFY_BACKEND=ollama\n")  # the builder applied them
    assert w.augment_get(*review_settings.handle("GET", "/api/settings"))[1]["pending"] == {}
    assert w.reset_settings()[1]["pending"] is True
    _, payload = w.augment_get(*review_settings.handle("GET", "/api/settings"))
    assert payload["pending"] == {"repair_model": "container-model", "verify_backend": None}
    assert payload["overrides"] == {}


def test_a_reverting_profile_is_pending_as_none(cfg, monkeypatch):
    monkeypatch.setenv("REPAIR_BACKEND", "llamacpp")
    monkeypatch.setenv("REPAIR_LLAMACPP_URL", "http://container/")
    (cfg / "effective.env").write_text(
        "REPAIR_BACKEND=openai\nREPAIR_OPENAI_URL=https://x/\nREPAIR_LLAMACPP_URL=http://container/\n"
    )
    assert w.augment_get(*review_settings.handle("GET", "/api/settings"))[1]["pending"] == {"repair_profile": None}


def test_nothing_reverts_when_effective_matches_the_container_or_is_missing(cfg, monkeypatch):
    monkeypatch.setenv("REPAIR_MODEL", "same")
    assert w.augment_get(*review_settings.handle("GET", "/api/settings"))[1]["pending"] == {}
    (cfg / "effective.env").write_text("REPAIR_MODEL=same\n")
    assert w.augment_get(*review_settings.handle("GET", "/api/settings"))[1]["pending"] == {}


# --- L3: the pins the review found missing ------------------------------------------------------------------------------


def test_two_profiles_with_one_backend_and_different_urls_are_told_apart(cfg, monkeypatch):
    table = {
        "a": {"backend": "llamacpp", "url": "http://a.example/v1"},
        "b": {"backend": "llamacpp", "url": "http://b.example/v1"},
    }
    monkeypatch.setenv("REPAIR_PROFILES", json.dumps(table))
    (cfg / "effective.env").write_text("REPAIR_BACKEND=llamacpp\nREPAIR_LLAMACPP_URL=http://a.example/v1\n")
    w.put_settings({"repair_profile": "a"})
    assert w.augment_get(*review_settings.handle("GET", "/api/settings"))[1]["pending"] == {}
    w.put_settings({"repair_profile": "b"})
    assert w.augment_get(*review_settings.handle("GET", "/api/settings"))[1]["pending"] == {"repair_profile": "b"}


def test_without_an_effective_file_the_servers_own_environment_is_the_baseline(cfg, monkeypatch):
    monkeypatch.setenv("REPAIR_MODEL", "same-as-container")
    w.put_settings({"repair_model": "same-as-container"})
    assert w.augment_get(*review_settings.handle("GET", "/api/settings"))[1]["pending"] == {}
    w.put_settings({"repair_model": "different"})
    assert w.augment_get(*review_settings.handle("GET", "/api/settings"))[1]["pending"] == {"repair_model": "different"}


def test_repair_keys_are_compared_with_what_the_merge_pass_reported(cfg):
    """effective.env is the generate loop's snapshot, which never applies the profile; merge-effective.env is the merge
    pass's. Comparing a profile with the wrong one would flip it pending and not-pending as the two take turns."""
    w.put_settings({"repair_profile": "local"})
    (cfg / "effective.env").write_text("REPAIR_BACKEND=llamacpp\nREPAIR_LLAMACPP_URL=http://container/\n")
    assert w.augment_get(*review_settings.handle("GET", "/api/settings"))[1]["pending"] == {"repair_profile": "local"}
    (cfg / "merge-effective.env").write_text(f"REPAIR_BACKEND=llamacpp\nREPAIR_LLAMACPP_URL={PROFILES['local']['url']}\n")
    assert w.augment_get(*review_settings.handle("GET", "/api/settings"))[1]["pending"] == {}


# --- L5: the exporter says what it ignored ------------------------------------------------------------------------------


def test_a_clean_file_prints_nothing_on_stderr(cfg):
    assert run_export(cfg, "REPAIR_MODEL=ok\n").stderr == ""


def test_the_exporter_names_what_it_ignored_on_one_stderr_line(cfg):
    runtime(cfg).write_bytes(b"REPAIR_MODEL=ok\n\xff\xfe\n")
    res = run_export(cfg, None)
    assert res.stdout == "" and "not valid UTF-8" in res.stderr and len(res.stderr.splitlines()) == 1

    runtime(cfg).write_text("REPAIR_MODEL=ok\n" + "# pad\n" * 20000)
    res = run_export(cfg, None)
    assert res.stdout == "" and "larger than" in res.stderr

    res = run_export(cfg, "REPAIR_PROFILE=local\nREPAIR_MODEL=ok\n", env={"REPAIR_PROFILES": "{broken"})
    assert res.stdout.splitlines() == ["export REPAIR_MODEL=ok"] and "REPAIR_PROFILES" in res.stderr

    res = run_export(cfg, "REPAIR_PROFILE=gone\n")
    assert "gone" in res.stderr and "REPAIR_PROFILES" in res.stderr

    res = run_export(cfg, "REPAIR_MODEL=bad model\nREQUIRE_ENG=7\nREPAIR_MODEL=ok\n")
    assert res.stdout.splitlines() == ["export REPAIR_MODEL=ok"] and "2 invalid line" in res.stderr


def test_the_server_side_read_stays_quiet(cfg, capsys):
    runtime(cfg).write_bytes(b"\xff\xfe\n")
    w.augment_get(*review_settings.handle("GET", "/api/settings"))
    assert capsys.readouterr().err == ""
