"""[S-8] Connections: validation, the link-local rule, stage rules, and the environment a stage choice stands for."""

import socket

import pytest

import decision_client
import settings_connections as conns
import settings_store as store


def conn(**kw):
    base = {
        "name": "local",
        "kind": "llamacpp",
        "url": "http://192.168.1.20:8090/v1/chat/completions",
        "model": "qwen3-4b-instruct",
    }
    base.update(kw)
    return base


def test_a_lan_or_loopback_connection_is_valid_and_defaults_are_filled():
    clean, errors = conns.validate_connection(conn())
    assert errors == {} and clean["timeout_connect"] == 10.0 and clean["timeout_read"] == 120.0 and clean["extra_body"] == {}
    assert conns.validate_connection(conn(url="http://127.0.0.1:8080/v1"))[1] == {}
    assert conns.validate_connection(conn(url="http://[::1]:8080/v1"))[1] == {}


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://169.254.1.1:8080/v1",
        "http://[fe80::1]:8080/v1",
        "http://[::ffff:169.254.169.254]/v1",
        "http://2852039166/v1",
        "http://0xA9FEA9FE/v1",
    ],
)
def test_link_local_and_metadata_addresses_are_refused_however_they_are_spelled(url):
    errors = conns.validate_connection(conn(url=url))[1]
    assert "link-local" in errors.get("url", ""), url


@pytest.mark.parametrize(
    "item, field",
    [
        (conn(url="http://user:pw@host/v1"), "url"),
        (conn(url="ftp://host/v1"), "url"),
        (conn(url="http://host/$(id)"), "url"),
        (conn(name="has space"), "name"),
        (conn(kind="gemini"), "kind"),
        (conn(model="bad model!"), "model"),
        (conn(extra_body={"x": "y" * 3000}), "extra_body"),
        (conn(extra_body={"x": 1}), "extra_body"),
        (conn(timeout_read=0), "timeout_read"),
        (conn(timeout_connect=601), "timeout_connect"),
    ],
)
def test_each_invalid_field_is_named(item, field):
    assert field in conns.validate_connection(item)[1]


def test_a_key_needs_an_openai_connection_over_https_or_loopback():
    hosted = conn(kind="openai", url="https://api.example.test/v1/chat/completions")
    assert conns.key_problem(hosted, "sk-abcdefgh12345678") == ""
    assert "https" in conns.key_problem({**hosted, "url": "http://192.168.1.20/v1"}, "sk-abcdefgh12345678")
    assert conns.key_problem({**hosted, "url": "http://127.0.0.1:9/v1"}, "sk-abcdefgh12345678") == ""
    assert "OpenAI" in conns.key_problem(conn(), "sk-abcdefgh12345678")
    assert "one line" in conns.key_problem(hosted, "two words")


def test_stage_rules_name_the_stage_and_the_reason():
    connections = [
        conn(),
        conn(name="cloud", kind="openai", url="https://openrouter.ai/api/alpha/decisions", model="m"),
        conn(name="oll", kind="ollama", url="http://127.0.0.1:11434/api/generate"),
        conn(name="oll2", kind="ollama", url="http://127.0.0.1:11435/api/generate"),
    ]
    ok = {"repair": "cloud", "restore": "local", "verify": "local", "decision": "cloud", "acquire": "local"}
    assert conns.validate_stages(ok, connections) == {}
    assert conns.validate_stages({"repair": "gone"}, connections) == {"repair": "points at a connection that does not exist"}
    assert "llamacpp or ollama" in conns.validate_stages({"restore": "cloud"}, connections)["restore"]
    assert "openai" in conns.validate_stages({"decision": "local"}, connections)["decision"]
    assert "same connection" in conns.validate_stages({"verify": "local", "acquire": "oll"}, connections)["acquire"]
    assert "Ollama" in conns.validate_stages({"repair": "oll", "restore": "oll2"}, connections)["restore"]
    assert conns.validate_stages({"verify": "@decision", "decision": "cloud", "acquire": "local"}, connections) == {}
    nomodel = [conn(name="bare", kind="openai", url="https://openrouter.ai/api/alpha/decisions", model="")]
    assert "model" in conns.validate_stages({"verify": "bare"}, nomodel)["verify"]
    assert conns.validate_stages({"repair": "bare"}, nomodel) == {}
    assert "decision connection first" in conns.validate_stages({"verify": "@decision"}, connections)["verify"]


def test_stage_rules_refuse_two_different_ollama_connections_across_all_five_stages():
    connections = [
        conn(name="oll1", kind="ollama", url="http://127.0.0.1:11434/api/generate"),
        conn(name="oll2", kind="ollama", url="http://192.168.1.50:11434/api/generate"),
    ]
    # pair across repair and verify
    res = conns.validate_stages({"repair": "oll1", "verify": "oll2"}, connections)
    assert "Ollama" in res.get("verify", "") or "Ollama" in res.get("repair", "")
    # pair across restore and acquire
    res2 = conns.validate_stages({"restore": "oll1", "acquire": "oll2"}, connections)
    assert "Ollama" in res2.get("acquire", "") or "Ollama" in res2.get("restore", "")


def test_stage_rules_refuse_host_decision_client_will_not_call():
    connections = [
        conn(name="unsupported_cloud", kind="openai", url="https://api.openai.com/v1/chat/completions", model="gpt-4o"),
        conn(name="openrouter", kind="openai", url=decision_client.DECISIONS_URL, model="inception/mercury-decide:free"),
        conn(name="commandcode", kind="openai", url=decision_client.COMMANDCODE_URL, model="typesafe/jev"),
        conn(name="loopback", kind="openai", url="http://127.0.0.1:8000/v1", model="m"),
    ]
    errors = conns.validate_stages({"decision": "unsupported_cloud"}, connections)
    assert "decision_client" in errors.get("decision", "")

    # Allowed hosts are accepted
    assert conns.validate_stages({"decision": "openrouter"}, connections) == {}
    assert conns.validate_stages({"decision": "commandcode"}, connections) == {}
    assert conns.validate_stages({"decision": "loopback"}, connections) == {}


def test_check_test_target_refuses_link_local_and_probes_checked_address(monkeypatch):
    # 1. Host resolves to link-local -> refused
    def mock_gai_link_local(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_gai_link_local)
    target_url, headers, problem = conns.check_test_target("http://evil-meta.test:8080/v1/models")
    assert "link-local" in problem

    # 2. Host resolves to IPv4-mapped link-local -> refused
    def mock_gai_mapped(host, port, *args, **kwargs):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:169.254.1.1", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_gai_mapped)
    target_url, headers, problem = conns.check_test_target("http://evil-meta.test:8080/v1/models")
    assert "link-local" in problem

    # 3. Host resolves to normal LAN IP -> returns URL with checked IP and Host header
    def mock_gai_lan(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.55", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_gai_lan)
    target_url, headers, problem = conns.check_test_target("http://my-llm.lan:8090/v1/models")
    assert problem == ""
    assert target_url == "http://192.168.1.55:8090/v1/models"
    assert headers == {"Host": "my-llm.lan:8090"}


def state_with(stages, connections, keys=None):
    state = store.State()
    state.connections = [conns.validate_connection(c)[0] for c in connections]
    state.stages = stages
    state.conn_keys = keys or {}
    return state


CLOUD = conn(
    name="cloud",
    kind="openai",
    url="https://api.example.test/v1/chat/completions",
    model="gpt-x",
    extra_body={"reasoning": {"effort": "low"}},
    timeout_read=30,
)


def test_a_repair_connection_expands_to_the_variables_repair_reads_and_the_key_goes_through_a_holder():
    state = state_with({"repair": "cloud"}, [CLOUD], {"cloud": "sk-abcdefgh12345678"})
    merge = dict(conns.expand(state, "merge"))
    assert merge["REPAIR_BACKEND"] == "openai" and merge["REPAIR_OPENAI_URL"] == CLOUD["url"] and merge["REPAIR_MODEL"] == "gpt-x"
    assert merge["REPAIR_OPENAI_KEY_ENV"] == "DT_CONN_KEY_REPAIR" and merge["DT_CONN_KEY_REPAIR"] == "sk-abcdefgh12345678"
    assert merge["REPAIR_EXTRA_BODY"] == '{"reasoning":{"effort":"low"}}'
    assert merge["REPAIR_TIMEOUT_CONNECT"] == "10" and merge["REPAIR_TIMEOUT_READ"] == "30"
    assert dict(conns.expand(state, "gen")) == {"REPAIR_MODEL": "gpt-x"}, "the generate loop never gets the repair endpoint"


def test_a_llamacpp_repair_connection_clears_the_previous_providers_flags():
    merge = dict(conns.expand(state_with({"repair": "local"}, [conn()]), "merge"))
    assert merge["REPAIR_BACKEND"] == "llamacpp" and merge["REPAIR_LLAMACPP_URL"] == conn()["url"]
    assert merge["REPAIR_EXTRA_BODY"] == "" and merge["REPAIR_OPENAI_KEY_ENV"] == "" and "DT_CONN_KEY_REPAIR" not in merge


def test_verify_decision_and_acquire_expand_for_the_generate_loop():
    state = state_with(
        {"verify": "local", "decision": "cloud", "acquire": "local"}, [conn(), CLOUD], {"cloud": "sk-abcdefgh12345678"}
    )
    gen = dict(conns.expand(state, "gen"))
    assert (
        gen["VERIFY_BACKEND"] == "llamacpp"
        and gen["VERIFY_LLAMACPP_URL"] == conn()["url"]
        and gen["ACQUIRE_BACKEND"] == "llamacpp"
    )
    assert gen["VERIFY_DECISION_URL"] == CLOUD["url"] and gen["VERIFY_DECISION_MODEL"] == "gpt-x"
    assert gen["VERIFY_DECISION_KEY_ENV"] == "DT_CONN_KEY_DECISION" and gen["DT_CONN_KEY_DECISION"] == "sk-abcdefgh12345678"


def test_verify_following_the_decision_stage_selects_the_decision_backend():
    state = state_with({"verify": "@decision", "decision": "cloud", "acquire": "local"}, [conn(), CLOUD])
    gen = dict(conns.expand(state, "gen"))
    assert (
        gen["VERIFY_BACKEND"] == "decision"
        and gen["ACQUIRE_BACKEND"] == "llamacpp"
        and gen["VERIFY_LLAMACPP_URL"] == conn()["url"]
    )


def test_restore_and_repair_both_ollama_use_one_address_and_repair_comes_last():
    ollama = conn(name="oll", kind="ollama", url="http://127.0.0.1:11434/api/generate", model="q")
    merge = conns.expand(state_with({"restore": "oll", "repair": "oll"}, [ollama]), "merge")
    assert dict(merge)["OLLAMA_URL"] == ollama["url"] and dict(merge)["RESTORE_BACKEND"] == "ollama"
    assert [n for n, _ in merge].index("RESTORE_BACKEND") < [n for n, _ in merge].index("REPAIR_BACKEND")


def test_an_unset_stage_or_a_dangling_name_adds_nothing():
    assert conns.expand(state_with({}, [conn()]), "merge") == []
    assert conns.expand(state_with({"repair": "gone"}, [conn()]), "merge") == []


def test_models_url_for_openai_endpoints():
    assert conns.models_url("https://api.example.test/v1/chat/completions") == "https://api.example.test/v1/models"
    assert conns.models_url("https://api.example.test/v1") == "https://api.example.test/v1/models"
