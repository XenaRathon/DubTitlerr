"""Settings page backend helpers (specs/webui-settings): allow-listed reads, secret masking, backend probes.

Pure functions with injected inputs (environ dicts, fake openers); no server needed."""

import json
import urllib.error

import review_settings as st

SECRET = "sk-secret-123"


class FakeResponse:
    def __init__(self, status=200, body=b'{"models": []}'):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Stand-in for urllib.request.urlopen: records requests, then returns or raises."""

    def __init__(self, status=200, error=None):
        self.status = status
        self.error = error
        self.requests = []
        self.timeouts = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        return FakeResponse(self.status)


def env(**overrides):
    base = {
        "REPAIR_BACKEND": "llamacpp",
        "REPAIR_MODEL": "qwen3-4b-instruct",
        "REPAIR_LLAMACPP_URL": "http://127.0.0.1:8090/v1/chat/completions",
        "VERIFY_BACKEND": "llamacpp",
        "VERIFY_LLAMACPP_URL": "http://127.0.0.1:8090/v1/chat/completions",
    }
    base.update(overrides)
    return base


def dumped(payload):
    return json.dumps(payload, sort_keys=True, default=str)


# ---- masking: the secret value never appears anywhere ---------------------------------------------------------------

def test_secrets_are_booleans_never_values():
    payload = st.build_settings(
        env(REVIEW_TOKEN=SECRET, REVIEW_PASSWORD=SECRET, LONGCATAI_API_KEY=SECRET),
        {},
    )[1]
    assert payload["secrets"]["REVIEW_TOKEN"] is True
    assert payload["secrets"]["REVIEW_PASSWORD"] is True
    assert payload["secrets"]["LONGCATAI_API_KEY"] is True
    assert SECRET not in dumped(payload), "a set secret must never appear in any returned payload"


def test_unset_secrets_are_false():
    payload = st.build_settings(env(), {})[1]
    assert payload["secrets"]["REVIEW_TOKEN"] is False
    assert SECRET not in dumped(payload)


def test_effective_env_secrets_are_masked_too(tmp_path):
    f = tmp_path / "effective.env"
    f.write_text(f"REPAIR_MODEL=qwen\nREVIEW_TOKEN={SECRET}\n", encoding="utf-8")
    payload = st.build_settings(env(), st.read_effective_env(str(f)))[1]
    assert payload["settings"]["repair_model"] == "qwen"
    assert payload["secrets"]["REVIEW_TOKEN"] is True
    assert SECRET not in dumped(payload)


def test_key_named_by_key_env_is_masked_and_never_echoed():
    e = env(
        REPAIR_BACKEND="openai",
        REPAIR_OPENAI_URL="https://api.example.com",
        REPAIR_OPENAI_KEY_ENV="MY_API_KEY",
        MY_API_KEY=SECRET,
    )
    payload = st.build_settings(e, {})[1]
    assert payload["secrets"]["MY_API_KEY"] is True
    assert SECRET not in dumped(payload)
    opener = FakeOpener()
    result = st.test_backend("repair", e, opener=opener)
    assert result["ok"] is True
    sent = opener.requests[0].get_header("Authorization")
    assert sent == f"Bearer {SECRET}", "the key travels in the header"
    assert SECRET not in dumped(result), "the key is never echoed back"


def test_backend_errors_cannot_carry_the_key():
    e = env(
        REPAIR_BACKEND="openai",
        REPAIR_OPENAI_URL="https://api.example.com",
        REPAIR_OPENAI_KEY_ENV="MY_API_KEY",
        MY_API_KEY=SECRET,
    )
    opener = FakeOpener(error=urllib.error.URLError(f"wrapped {SECRET} ?token={SECRET}"))
    result = st.test_backend("repair", e, opener=opener)
    assert result["ok"] is False
    assert SECRET not in dumped(result)
    assert f"token={SECRET}" not in result["error"], "the full URL query value is redacted too"


# ---- effective.env parsing and precedence ----------------------------------------------------------------------------

def test_effective_env_parses_pairs_ignores_comments_and_bad_lines(tmp_path):
    f = tmp_path / "effective.env"
    f.write_text(
        "# builder snapshot\n"
        "REPAIR_MODEL=qwen\n"
        "export QUOTED='spaced value'\n"
        "EMPTY=\n"
        "no-equals-here\n"
        "=no-key\n"
        "\n",
        encoding="utf-8",
    )
    assert st.read_effective_env(str(f)) == {
        "REPAIR_MODEL": "qwen",
        "QUOTED": "spaced value",
        "EMPTY": "",
    }


def test_missing_effective_env_is_empty_dict(tmp_path):
    assert st.read_effective_env(str(tmp_path / "nope.env")) == {}


def test_effective_env_wins_over_environ_and_sets_source():
    payload = st.build_settings(env(REPAIR_MODEL="from-env"), {"REPAIR_MODEL": "from-file"})[1]
    assert payload["settings"]["repair_model"] == "from-file"
    assert payload["source"] == "effective.env"


def test_missing_file_falls_back_to_env_with_source_env():
    payload = st.build_settings(env(REPAIR_MODEL="from-env"), {})[1]
    assert payload["settings"]["repair_model"] == "from-env"
    assert payload["source"] == "env"


def test_settings_covers_the_spec_allow_list():
    for key in (
        "repair_backend", "repair_model", "repair_llamacpp_url", "repair_openai_url",
        "verify_backend", "verify_decision_model", "acquire_backend", "whisper_model",
        "compute_type", "require_eng", "repair_unanchored", "glossary_arc_tags",
        "rescan_interval", "merge_roots", "anime_order", "acquire_apply",
    ):
        assert key in st.ALLOW_LIST
    payload = st.build_settings(env(), {})[1]
    assert set(payload) == {"settings", "secrets", "source"}
    assert set(payload["settings"]) == set(st.ALLOW_LIST)


# ---- backend probes ---------------------------------------------------------------------------------------------------

def test_openai_probe_hits_models_with_bearer_key():
    e = env(
        REPAIR_BACKEND="openai",
        REPAIR_OPENAI_URL="https://api.example.com/",
        REPAIR_OPENAI_KEY_ENV="MY_API_KEY",
        MY_API_KEY="k",
    )
    opener = FakeOpener()
    result = st.test_backend("repair", e, opener=opener)
    assert result == {"ok": True, "latency_ms": result["latency_ms"], "error": ""}
    assert isinstance(result["latency_ms"], int)
    req = opener.requests[0]
    assert req.full_url == "https://api.example.com/v1/models"
    assert req.get_header("Authorization") == "Bearer k"
    assert opener.timeouts == [5.0]


def test_llamacpp_probe_is_a_plain_get_with_no_auth_header():
    opener = FakeOpener()
    result = st.test_backend("repair", env(), opener=opener)
    assert result["ok"] is True
    req = opener.requests[0]
    assert req.full_url == "http://127.0.0.1:8090/v1/chat/completions"
    assert req.get_header("Authorization") is None


def test_verify_openai_uses_verify_url_and_key_env():
    e = env(
        VERIFY_BACKEND="openai",
        VERIFY_OPENAI_URL="https://verify.example.com",
        VERIFY_OPENAI_KEY_ENV="V_KEY",
        V_KEY="k",
    )
    opener = FakeOpener()
    assert st.test_backend("verify", e, opener=opener)["ok"] is True
    req = opener.requests[0]
    assert req.full_url == "https://verify.example.com/v1/models"
    assert req.get_header("Authorization") == "Bearer k"


def test_missing_key_is_a_clean_failure_not_a_request():
    e = env(REPAIR_BACKEND="openai", REPAIR_OPENAI_URL="https://api.example.com")
    opener = FakeOpener()
    result = st.test_backend("repair", e, opener=opener)
    assert result["ok"] is False and result["latency_ms"] == 0
    assert opener.requests == []


def test_unknown_backend_name_is_unsupported():
    result = st.test_backend("bogus", env(), opener=FakeOpener())
    assert result == {"ok": False, "latency_ms": 0, "error": "unsupported backend"}


def test_timeout_refused_and_http_statuses_map_to_ok_false():
    e = env()
    assert st.test_backend("repair", e, opener=FakeOpener(error=TimeoutError())) == {
        "ok": False, "latency_ms": 0, "error": "timed out",
    }
    refused = st.test_backend("repair", e, opener=FakeOpener(error=ConnectionRefusedError()))
    assert refused == {"ok": False, "latency_ms": 0, "error": "connection refused"}
    for code in (401, 404, 500):
        err = urllib.error.HTTPError("http://127.0.0.1:8090/v1/chat/completions", code, "x", {}, None)
        result = st.test_backend("repair", e, opener=FakeOpener(error=err))
        assert result == {"ok": False, "latency_ms": 0, "error": f"HTTP {code}"}
    plain = st.test_backend("repair", e, opener=FakeOpener(status=500))
    assert plain["ok"] is False and plain["error"] == "HTTP 500"


def test_unconfigured_endpoint_is_a_clean_failure():
    e = env(REPAIR_BACKEND="openai", REPAIR_OPENAI_URL="", REPAIR_OPENAI_KEY_ENV="K", K="k")
    result = st.test_backend("repair", e, opener=FakeOpener())
    assert result == {"ok": False, "latency_ms": 0, "error": "no endpoint configured"}


# ---- handle dispatch ---------------------------------------------------------------------------------------------------

def test_handle_get_settings(monkeypatch, tmp_path):
    f = tmp_path / "effective.env"
    f.write_text("REPAIR_MODEL=qwen\n", encoding="utf-8")
    monkeypatch.setattr(st, "EFFECTIVE_ENV_PATH", str(f))
    status, payload = st.handle("GET", "/api/settings", None, environ=env(REVIEW_TOKEN=SECRET))
    assert status == 200
    assert payload["settings"]["repair_model"] == "qwen"
    assert payload["source"] == "effective.env"
    assert SECRET not in dumped(payload)


def test_handle_test_round_trips_the_probe(monkeypatch):
    monkeypatch.setattr(st, "EFFECTIVE_ENV_PATH", "/nonexistent-effective.env")
    opener = FakeOpener()
    status, payload = st.handle(
        "POST", "/api/settings/test", {"backend": "repair"}, environ=env(), opener=opener
    )
    assert (status, payload["ok"]) == (200, True)
    assert isinstance(payload["latency_ms"], int)


def test_handle_unknown_backend_is_400(monkeypatch):
    monkeypatch.setattr(st, "EFFECTIVE_ENV_PATH", "/nonexistent-effective.env")
    assert st.handle("POST", "/api/settings/test", {"backend": "bogus"}, environ=env()) == (
        400, {"error": "unsupported backend"},
    )
    assert st.handle("POST", "/api/settings/test", {}, environ=env())[0] == 400


def test_handle_unknown_routes_are_404():
    assert st.handle("GET", "/api/nope", None, environ=env()) == (404, {"error": "no such route"})
    assert st.handle("DELETE", "/api/settings", None, environ=env())[0] == 404


def test_userinfo_stripped_from_urls_in_settings():
    e = env(
        REPAIR_LLAMACPP_URL="http://user:basicsecret@host/v1",
        REPAIR_OPENAI_URL="https://admin:pass123@api.example.com/v1",
    )
    status, payload = st.build_settings(e, {})
    assert status == 200
    assert payload["settings"]["repair_llamacpp_url"] == "http://host/v1"
    assert payload["settings"]["repair_openai_url"] == "https://api.example.com/v1"
    assert "basicsecret" not in dumped(payload)
    assert "pass123" not in dumped(payload)


def test_userinfo_redacted_in_backend_probe_error():
    url = "http://user:secret@host/v1"
    e = env(REPAIR_LLAMACPP_URL=url)
    err = urllib.error.URLError(f"connection failed to {url}")
    result = st.test_backend("repair", e, opener=FakeOpener(error=err))
    assert result["ok"] is False
    assert "secret" not in result["error"]
    assert "secret" not in dumped(result)


def test_l6_admin_token_and_webhook_token_reported_as_secrets():
    payload = st.build_settings(
        env(REVIEW_ADMIN_TOKEN="adm123", WEBHOOK_TOKEN="whk456"),
        {},
    )[1]
    assert payload["secrets"]["REVIEW_ADMIN_TOKEN"] is True
    assert payload["secrets"]["WEBHOOK_TOKEN"] is True
    assert "adm123" not in dumped(payload)
    assert "whk456" not in dumped(payload)


def test_l6_merge_window_in_allowlist():
    payload = st.build_settings(
        env(MERGE_WINDOW="10:00-14:00"),
        {},
    )[1]
    assert payload["settings"]["merge_window"] == "10:00-14:00"


def test_l6_dynamic_effective_env_file_env_var(tmp_path):
    f = tmp_path / "custom.env"
    f.write_text("REPAIR_MODEL=custom-model\n", encoding="utf-8")
    e = env(EFFECTIVE_ENV_FILE=str(f))
    status, payload = st.handle("GET", "/api/settings", environ=e)
    assert status == 200
    assert payload["settings"]["repair_model"] == "custom-model"
