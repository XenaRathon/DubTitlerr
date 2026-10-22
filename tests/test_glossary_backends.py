"""VERIFY_BACKEND resolution and the openai text backend of common.llm_chat (glossary stages).

Synthetic only; a fake 127.0.0.1 server stands in for the provider."""

import pytest
from fake_servers import FakeServer, chat_reply

import common
import glossary_acquire as ga
import glossary_verify as gv

KEY = "sk-test-SECRET-0123456789"  # gitleaks:allow -- test fixture, not a real credential

# ---- the VERIFY_BACKEND rule ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env,expect",
    [
        ({}, "ollama"),  # today's default, kept byte-identical
        ({"REPAIR_BACKEND": "llamacpp"}, "llamacpp"),  # the legacy inheritance the production compose relies on
        ({"REPAIR_BACKEND": "ollama"}, "ollama"),
        ({"REPAIR_BACKEND": ""}, "ollama"),
        ({"VERIFY_BACKEND": "", "REPAIR_BACKEND": "llamacpp"}, "llamacpp"),  # an empty value is unset
        ({"VERIFY_BACKEND": "llamacpp"}, "llamacpp"),
        ({"VERIFY_BACKEND": "openai"}, "openai"),
        ({"VERIFY_BACKEND": "decision"}, "decision"),
        ({"VERIFY_BACKEND": "ollama", "REPAIR_BACKEND": "openai"}, "ollama"),  # explicit wins, even over a repair openai
        ({"VERIFY_BACKEND": "decision", "REPAIR_BACKEND": "openai"}, "decision"),
    ],
)
def test_resolve_backend_accepts(env, expect):
    assert gv.resolve_backend(env) == (expect, "")


@pytest.mark.parametrize(
    "env,mentions",
    [
        ({"REPAIR_BACKEND": "openai"}, ["REPAIR_BACKEND", "VERIFY_BACKEND"]),  # the stray-openai trap: no silent inherit
        ({"REPAIR_BACKEND": "nonsense"}, ["VERIFY_BACKEND"]),
        ({"VERIFY_BACKEND": "gemini"}, ["VERIFY_BACKEND", "decision"]),
        ({"VERIFY_BACKEND": "OpenAI"}, ["VERIFY_BACKEND"]),  # exact names only
    ],
)
def test_resolve_backend_refuses_with_a_message_that_names_the_fix(env, mentions):
    backend, problem = gv.resolve_backend(env)
    assert backend == "" and all(m in problem for m in mentions)


def test_the_defaults_with_no_new_env_are_the_legacy_ones():
    """GUARD (passes on the old code too): module defaults when none of the new variables is set."""
    assert gv.VERIFY_BACKENDS == ("llamacpp", "ollama", "openai", "decision")
    assert gv.VERIFY_BACKEND in ("llamacpp", "ollama")


def test_verify_refuses_to_run_on_an_unresolved_backend_before_any_work(tmp_path, monkeypatch):
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "REPAIR_BACKEND='openai' cannot be inherited: set VERIFY_BACKEND")
    monkeypatch.setattr(gv, "resolve_wiki", lambda *a, **k: pytest.fail("the wiki must not be touched"))
    path = tmp_path / "S.json"
    path.write_text('{"show": "S", "names": ["Zoro"], "phrases": []}')
    rep = gv.verify(str(path))
    assert rep["note"].startswith("refused:") and "VERIFY_BACKEND" in rep["note"]
    assert path.read_text() == '{"show": "S", "names": ["Zoro"], "phrases": []}'


def test_acquire_refuses_to_run_on_an_unresolved_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "REPAIR_BACKEND='openai' cannot be inherited: set VERIFY_BACKEND")
    path = tmp_path / "S.json"
    path.write_text('{"show": "S", "names": [], "phrases": []}')
    rep = ga.acquire(str(path), str(tmp_path))
    assert rep["note"].startswith("refused:")


def test_the_adjudicators_refuse_on_an_unresolved_backend(monkeypatch):
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "no backend")
    monkeypatch.setattr(gv, "llm_chat", lambda *a, **k: pytest.fail("no model call may be made"))
    with pytest.raises(gv.BackendConfigError):
        gv.adjudicate("Zoro", ["Roronoa Zoro"], "S")
    monkeypatch.setattr(ga, "llm_chat", lambda *a, **k: pytest.fail("no model call may be made"))
    assert ga.adjudicate_merge("a", "b", [], [], "S")["unavailable"] is True


def test_the_legacy_llm_call_is_byte_identical(monkeypatch):
    """GUARD: with a legacy backend the adjudicators call llm_chat with exactly the kwargs they always did."""
    seen = []
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    monkeypatch.setattr(
        gv, "llm_chat", lambda prompt, **kw: seen.append((prompt, kw)) or '{"canonical": "Roronoa Zoro", "confidence": "high"}'
    )
    out = gv.adjudicate("Zoro", ["Roronoa Zoro"], "One Piece")
    assert out == {"canonical": "Roronoa Zoro", "confidence": "high", "dub_note": ""}
    prompt, kw = seen[0]
    assert prompt == gv.build_adjudication_prompt("Zoro", ["Roronoa Zoro"], "One Piece")
    assert kw == {
        "backend": "llamacpp",
        "ollama_url": gv.OLLAMA,
        "llamacpp_url": gv.VERIFY_LLAMACPP_URL,
        "model": gv.VERIFY_MODEL,
        "max_tokens": gv.VERIFY_MAX_TOKENS,
        "first_line": False,
    }
    seen.clear()
    monkeypatch.setattr(
        ga, "llm_chat", lambda prompt, **kw: seen.append((prompt, kw)) or '{"same_entity": true, "confidence": "high"}'
    )
    assert ga.adjudicate_merge("Zorro", "Zoro", ["l1"], ["l2"], "S") == {"same_entity": True, "confidence": "high"}
    assert seen[0][0] == ga.build_merge_prompt("Zorro", "Zoro", ["l1"], ["l2"], "S")
    assert seen[0][1] == kw


# ---- the openai text backend --------------------------------------------------------------------------------------------------


@pytest.fixture
def provider(monkeypatch):
    srv = FakeServer(lambda req: (200, chat_reply('{"canonical": "Roronoa Zoro", "confidence": "high", "dub_note": ""}')))
    monkeypatch.setenv("TEST_PROVIDER_KEY", KEY)
    monkeypatch.setenv("VERIFY_MODEL", "vendor/model-x")
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "openai")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    monkeypatch.setenv("VERIFY_OPENAI_URL", srv.url)
    monkeypatch.setenv("VERIFY_OPENAI_KEY_ENV", "TEST_PROVIDER_KEY")
    monkeypatch.delenv("VERIFY_OPENAI_EXTRA_BODY", raising=False)
    monkeypatch.setattr(common.time, "sleep", lambda s: None)
    yield srv
    srv.close()


def test_adjudicate_over_the_openai_backend_end_to_end(provider):
    out = gv.adjudicate("Zoro", ["Roronoa Zoro", "Zorro"], "One Piece")
    assert out == {"canonical": "Roronoa Zoro", "confidence": "high", "dub_note": ""}
    req = provider.requests[0]
    assert req["auth"] == f"Bearer {KEY}" and req["ua"].startswith("DubTitlerr")
    body = req["body"]
    assert body["model"] == "vendor/model-x" and body["temperature"] == 0 and body["max_tokens"] == gv.VERIFY_MAX_TOKENS
    assert body["messages"] == [
        {"role": "user", "content": gv.build_adjudication_prompt("Zoro", ["Roronoa Zoro", "Zorro"], "One Piece")}
    ]
    assert "chat_template_kwargs" not in body and "prompt" not in body  # neither the llama.cpp nor the Ollama shape


def test_adjudicate_merge_over_the_openai_backend(provider):
    provider.srv.RequestHandlerClass  # noqa: B018 (keeps the fixture referenced)
    out = ga.adjudicate_merge("Zorro", "Zoro", ["l1"], ["l2"], "S")
    assert out["confidence"] in ("high", "low", "none") and "same_entity" in out


def test_only_message_content_is_read_and_the_reply_keeps_its_lines(monkeypatch, provider):
    srv = FakeServer(lambda r: (200, chat_reply('line one\n{"x": 1}', reasoning_content="the monologue", refusal="r")))
    monkeypatch.setenv("VERIFY_OPENAI_URL", srv.url)
    try:
        out = common.llm_chat(
            "P", backend="openai", openai_url=srv.url, openai_key_env="TEST_PROVIDER_KEY", model="m", first_line=False
        )
    finally:
        srv.close()
    assert out == 'line one\n{"x": 1}'  # first_line=False keeps the whole content; reasoning_content is never read


def test_first_line_true_returns_the_first_line_like_the_other_backends(provider):
    srv = FakeServer(lambda r: (200, chat_reply('"Hello"\nsecond')))
    try:
        out = common.llm_chat("P", backend="openai", openai_url=srv.url, openai_key_env="TEST_PROVIDER_KEY", model="m")
    finally:
        srv.close()
    assert out == "Hello"


def test_extra_body_is_merged_but_cannot_replace_model_or_messages(monkeypatch, provider):
    monkeypatch.setenv("VERIFY_OPENAI_EXTRA_BODY", '{"reasoning": {"enabled": false}, "model": "evil", "messages": []}')
    gv.adjudicate("Zoro", ["Roronoa Zoro"], "S")
    body = provider.requests[0]["body"]
    assert body["reasoning"] == {"enabled": False} and body["model"] == "vendor/model-x" and body["messages"]


@pytest.mark.parametrize(
    "status,retried",
    [(500, True), (503, True), (429, True), (400, False), (401, False), (404, False)],
)
def test_http_failures_return_empty_text_and_only_retryable_ones_are_retried(monkeypatch, capsys, status, retried):
    srv = FakeServer(lambda r: (status, {"error": f"echo of {r['auth']} and body"}))
    monkeypatch.setenv("TEST_PROVIDER_KEY", KEY)
    try:
        out = common.llm_chat("P", backend="openai", openai_url=srv.url, openai_key_env="TEST_PROVIDER_KEY", model="m")
        n = len(srv.requests)
    finally:
        srv.close()
    shown = capsys.readouterr().out
    assert out == "" and (n == 3 if retried else n == 1)
    assert f"HTTP {status}" in shown and KEY not in shown and "echo of" not in shown  # the body may echo the key


def test_a_429_followed_by_success_is_recovered(monkeypatch):
    replies = iter([(429, {"error": "slow down"}), (200, chat_reply("ok"))])
    srv = FakeServer(lambda r: next(replies))
    monkeypatch.setenv("TEST_PROVIDER_KEY", KEY)
    monkeypatch.setattr(common.time, "sleep", lambda s: None)
    try:
        assert common.llm_chat("P", backend="openai", openai_url=srv.url, openai_key_env="TEST_PROVIDER_KEY", model="m") == "ok"
    finally:
        srv.close()


def test_a_transport_failure_returns_empty_text_and_logs_only_the_class(monkeypatch, capsys):
    monkeypatch.setenv("TEST_PROVIDER_KEY", KEY)
    out = common.llm_chat(
        "P", backend="openai", openai_url="http://127.0.0.1:9/v1", openai_key_env="TEST_PROVIDER_KEY", model="m"
    )
    shown = capsys.readouterr().out
    assert out == "" and "llm fail:" in shown and KEY not in shown


@pytest.mark.parametrize(
    "kw",
    [
        {"openai_url": "", "model": "m"},
        {"openai_url": "http://127.0.0.1:1/x", "model": ""},
        {"openai_url": "http://127.0.0.1:1/x", "model": "m", "openai_key_env": "NO_SUCH_KEY_VAR"},
        {"openai_url": "http://127.0.0.1:1/x", "model": "m", "openai_key_env": ""},
        {"openai_url": "http://api.example.com/v1/chat/completions", "model": "m"},  # a key never travels over plain http
        {"openai_url": "https://user:pw@api.example.com/v1", "model": "m"},
        {"openai_url": "ftp://api.example.com/v1", "model": "m"},
        {"openai_url": "http://127.0.0.1:1/x", "model": "m", "openai_extra_body": "{not json"},
        {"openai_url": "http://127.0.0.1:1/x", "model": "m", "openai_extra_body": "[1]"},
    ],
)
def test_a_bad_configuration_makes_no_request_and_returns_empty_text(monkeypatch, capsys, kw):
    monkeypatch.setenv("TEST_PROVIDER_KEY", KEY)
    kw.setdefault("openai_key_env", "TEST_PROVIDER_KEY")
    monkeypatch.setattr(common, "_post_json", lambda *a, **k: pytest.fail("no request"))
    import repair

    monkeypatch.setattr(repair, "_post_json", lambda *a, **k: pytest.fail("no request"))
    assert common.llm_chat("P", backend="openai", **kw) == ""
    assert KEY not in capsys.readouterr().out


def test_a_key_with_control_characters_is_refused_and_a_crlf_one_is_cleaned(monkeypatch, capsys):
    srv = FakeServer(lambda r: (200, chat_reply("ok")))
    try:
        monkeypatch.setenv("TEST_PROVIDER_KEY", KEY + "\r\n")
        assert common.llm_chat("P", backend="openai", openai_url=srv.url, openai_key_env="TEST_PROVIDER_KEY", model="m") == "ok"
        assert srv.requests[0]["auth"] == f"Bearer {KEY}"
        monkeypatch.setenv("TEST_PROVIDER_KEY", "bad key\x01")
        assert common.llm_chat("P", backend="openai", openai_url=srv.url, openai_key_env="TEST_PROVIDER_KEY", model="m") == ""
        assert len(srv.requests) == 1
    finally:
        srv.close()
    assert "bad key" not in capsys.readouterr().out


def test_the_old_backends_keep_their_request_shapes_and_the_new_kwargs_default_to_none():
    import inspect

    sig = inspect.signature(common.llm_chat).parameters
    assert (
        sig["openai_url"].default is None and sig["openai_key_env"].default is None and sig["openai_extra_body"].default is None
    )


# ---- preflight: a misconfigured openai backend refuses up front instead of marking every term no-match -----------------------


@pytest.mark.parametrize(
    "mutate,mention",
    [
        (lambda m: m.delenv("VERIFY_OPENAI_URL"), "VERIFY_OPENAI_URL"),
        (lambda m: m.delenv("VERIFY_OPENAI_KEY_ENV"), "VERIFY_OPENAI_KEY_ENV"),
        (lambda m: m.delenv("TEST_PROVIDER_KEY"), "TEST_PROVIDER_KEY"),
        (lambda m: m.delenv("VERIFY_MODEL"), "VERIFY_MODEL"),
        (lambda m: m.setenv("VERIFY_OPENAI_EXTRA_BODY", "{nope"), "VERIFY_OPENAI_EXTRA_BODY"),
        (lambda m: m.setenv("VERIFY_OPENAI_URL", "http://api.example.com/v1"), "https"),
    ],
)
def test_the_openai_preflight_names_what_is_missing(provider, monkeypatch, mutate, mention):
    assert gv.backend_problem() == ""
    mutate(monkeypatch)
    problem = gv.backend_problem()
    assert mention in problem and KEY not in problem


def test_verify_refuses_when_the_openai_backend_is_misconfigured(tmp_path, provider, monkeypatch):
    monkeypatch.delenv("VERIFY_MODEL")
    monkeypatch.setattr(gv, "resolve_wiki", lambda *a, **k: pytest.fail("the wiki must not be touched"))
    path = tmp_path / "S.json"
    path.write_text('{"show": "S", "names": ["Zoro"], "phrases": []}')
    assert gv.verify(str(path))["note"].startswith("refused:")


# ---- phase 7: reasoning_content, the whole-word write guard, the opt-in refusal exit -------------------------------------------


def test_reasoning_content_is_never_read_even_when_content_is_empty(monkeypatch):
    monkeypatch.setenv("TEST_PROVIDER_KEY", KEY)  # without a key the call would return "" for the wrong reason
    srv = FakeServer(lambda r: (200, chat_reply("", reasoning_content='{"canonical": "Leaked", "confidence": "high"}')))
    try:
        out = common.llm_chat(
            "P", backend="openai", openai_url=srv.url, openai_key_env="TEST_PROVIDER_KEY", model="m", first_line=False
        )
    finally:
        srv.close()
    assert out == ""


def test_the_missing_config_message_names_no_other_stages_variables(monkeypatch, capsys):
    monkeypatch.delenv("TEST_PROVIDER_KEY", raising=False)
    assert common.llm_chat("P", backend="openai", model="m") == ""
    shown = capsys.readouterr().out
    assert "the openai backend is not configured for this stage" in shown and "VERIFY_" not in shown


@pytest.mark.parametrize("term,canon", [("Usop", "Usopp"), ("Burn", "Coburn"), ("Zoro", "Zoroaster")])
def test_by_default_a_substring_expansion_is_written_as_before(monkeypatch, term, canon):
    """GUARD (passes on the old code): is_expansion's substring rule writes near-respellings. Default behaviour is unchanged."""
    monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "0")
    g = {"show": "S", "names": [term], "phrases": [], "hard_fixes": {}}
    new = gv.apply_results(g, {term: {"canonical": canon, "confidence": "high", "dub_note": ""}})
    assert canon in new["names"] and "flagged" not in new


@pytest.mark.parametrize("term,canon", [("Usop", "Usopp"), ("Burn", "Coburn"), ("Zoro", "Zoroaster")])
def test_with_the_whole_word_guard_a_near_respelling_is_flagged_not_written(monkeypatch, term, canon):
    monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "1")
    g = {"show": "S", "names": [term], "phrases": [], "hard_fixes": {}}
    new = gv.apply_results(g, {term: {"canonical": canon, "confidence": "high", "dub_note": ""}})
    assert new["names"] == [term] and new["flagged"][term] == {"reason": "respelling-needs-review", "canonical": canon}


@pytest.mark.parametrize(
    "term,canon,dest",
    [
        ("Zoro", "Roronoa Zoro", "phrases"),
        ("Straw Hat", "Monkey D. Luffy's Straw Hat Pirates", "phrases"),
        ("Zoro", "Zoro Jr", "phrases"),
    ],
)
def test_with_the_whole_word_guard_a_whole_word_expansion_is_still_written(monkeypatch, term, canon, dest):
    monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "1")
    g = {"show": "S", "names": [term], "phrases": [], "hard_fixes": {}}
    new = gv.apply_results(g, {term: {"canonical": canon, "confidence": "high", "dub_note": ""}})
    assert canon in new["names"] + new["phrases"] and "flagged" not in new


def test_the_whole_word_guard_is_token_wise_and_casefolded(monkeypatch):
    monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "1")
    assert gv._whole_word("zoro", "Roronoa ZORO") and gv._whole_word("Straw Hat", "The straw hat Pirates")
    assert not gv._whole_word("Straw Hat", "Straw Pirates Hat") and not gv._whole_word("Usop", "Usopp")


def test_verify_counts_applied_the_way_it_writes(monkeypatch, tmp_path):
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: ["Usopp"])
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    monkeypatch.setattr(gv, "llm_chat", lambda *a, **k: '{"canonical": "Usopp", "confidence": "high", "dub_note": ""}')
    path = tmp_path / "g.json"
    path.write_text('{"show": "S", "names": ["Usop"], "phrases": [], "hard_fixes": {}, "initial_prompt": "P"}')
    monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "0")
    assert gv.verify(str(path))["applied"] == 1
    path.write_text('{"show": "S", "names": ["Usop"], "phrases": [], "hard_fixes": {}, "initial_prompt": "P"}')
    monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "1")
    rep = gv.verify(str(path))
    assert rep["applied"] == 0 and rep["escalated"] == 1


def _refused_setup(monkeypatch, tmp_path):
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "no usable backend")
    path = tmp_path / "S.json"
    path.write_text('{"show": "S", "names": ["Zoro"], "phrases": []}')
    return str(path)


def test_a_refused_verify_exits_zero_by_default(monkeypatch, tmp_path, capsys):
    """GUARD: unchanged default -- exit 0, no REFUSED line."""
    path = _refused_setup(monkeypatch, tmp_path)
    monkeypatch.delenv("VERIFY_REFUSE_EXIT", raising=False)
    monkeypatch.setattr("sys.argv", ["glossary_verify", path])
    with pytest.raises(SystemExit) as e:
        gv.main()
    assert e.value.code == 0 and "REFUSED" not in capsys.readouterr().out


def test_a_refused_verify_exits_nonzero_with_a_final_refused_line_when_asked(monkeypatch, tmp_path, capsys):
    path = _refused_setup(monkeypatch, tmp_path)
    monkeypatch.setenv("VERIFY_REFUSE_EXIT", "1")
    monkeypatch.setattr("sys.argv", ["glossary_verify", path])
    with pytest.raises(SystemExit) as e:
        gv.main()
    assert e.value.code not in (0, None)
    assert capsys.readouterr().out.strip().splitlines()[-1].startswith("REFUSED")


def test_a_refused_acquire_exits_nonzero_when_asked_and_zero_otherwise(monkeypatch, tmp_path, capsys):
    path = _refused_setup(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.argv", ["glossary_acquire", path, str(tmp_path)])
    monkeypatch.delenv("VERIFY_REFUSE_EXIT", raising=False)
    ga.main()  # returns normally: exit 0, as before
    assert "REFUSED" not in capsys.readouterr().out
    monkeypatch.setenv("VERIFY_REFUSE_EXIT", "1")
    with pytest.raises(SystemExit) as e:
        ga.main()
    assert e.value.code not in (0, None) and capsys.readouterr().out.strip().splitlines()[-1].startswith("REFUSED")


def test_a_healthy_run_never_exits_nonzero_for_refusal(monkeypatch, tmp_path):
    monkeypatch.setenv("VERIFY_REFUSE_EXIT", "1")
    path = tmp_path / "S.json"
    path.write_text('{"show": "S", "names": [], "phrases": []}')
    monkeypatch.setattr("sys.argv", ["glossary_verify", str(path)])
    with pytest.raises(SystemExit) as e:
        gv.main()
    assert e.value.code == 0  # "nothing pending" is not a refusal
