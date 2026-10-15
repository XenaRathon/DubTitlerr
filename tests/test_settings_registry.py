"""[S-1] The settings registry: schema, first-wave coverage, validation and the environment round trip."""

import os
import re

import pytest

import settings_registry as reg

FIRST_WAVE = {
    "general": ["REVIEW_PORT", "REVIEW_BIND"],
    "library": ["REQUIRE_ENG", "SKIP_IF_SRT", "KEEP_LANGS", "SUB_LANGS", "MIN_FREE_GB", "REMOTE_PATH_MAPPINGS"],
    "transcription": ["WHISPER_MODEL", "COMPUTE_TYPE", "WHISPER_BEAM_SIZE", "ASR_DEVICE"],
    "glossary": [
        "ACQUIRE",
        "ACQUIRE_APPLY",
        "GLOSSARY_ARC_TAGS",
        "VERIFY_ARC_GATE",
        "MINE_MIN_COUNT",
        "ACQUIRE_MIN_SIM",
        "VERIFY_DECISION_TAU",
    ],
    "repair": [
        "DECISIONS_APPLY",
        "REPAIR_UNANCHORED",
        "RESTORE_PUNCTUATION",
        "REPAIR_AUTO_DISMISS_WORDS",
        "REPAIR_KEEP_NAME_PARTS",
        "REPAIR_EPISODE_DEADLINE",
    ],
    "output": ["DUB_FANSUB_FONT", "SIGNS_CROSS_TRACK_DEDUP", "REVIEW_GATE_SHOWS", "REVIEW_GATE_STALE_DAYS", "MERGE_INTERVAL"],
    "schedule": ["MERGE_WINDOW", "WATCH_QUEUE_WINDOW_DAYS", "WATCH_QUEUE_PIN"],
    "connect": ["PLEX_URL", "PLEX_TOKEN", "PLEX_SECTION", "WATCHSTATE_URL", "WATCHSTATE_API_KEY", "WEBHOOK_TOKEN"],
}
FIELDS = ("key", "category", "label", "help", "type", "default", "advanced", "applies", "scope", "editable", "secret")


def test_schema_lists_every_first_wave_key_with_the_spec_fields():
    schema = reg.schema()
    by_key = {s["key"]: s for s in schema["settings"]}
    for category, keys in FIRST_WAVE.items():
        for key in keys:
            entry = by_key[key]
            assert entry["category"] == category and entry["editable"] is True, key
            assert all(field in entry for field in FIELDS), key
            assert entry["help"].strip() and entry["label"].strip(), key


def test_the_categories_are_the_nine_in_the_spec_order():
    assert [c["id"] for c in reg.schema()["categories"]] == [
        "general",
        "library",
        "transcription",
        "glossary",
        "repair",
        "connections",
        "output",
        "schedule",
        "connect",
    ]
    assert all(c["label"] and c["summary"] for c in reg.CATEGORIES)


def test_only_the_three_spec_keys_are_advanced_in_the_first_wave():
    advanced = {k for k, e in reg.REGISTRY.items() if e["first_wave"] and e["advanced"]}
    assert advanced == {"ACQUIRE_MIN_SIM", "VERIFY_DECISION_TAU", "REPAIR_EPISODE_DEADLINE"}


def test_restart_means_a_server_or_container_scope_and_back():
    for key, entry in reg.REGISTRY.items():
        reads_at_boot = set(entry["scope"]) <= {"server", "container"}
        assert (entry["applies"] == "restart") == reads_at_boot, key


def test_only_first_wave_entries_are_editable_and_secrets_are_flagged():
    assert {k for k, e in reg.REGISTRY.items() if e["editable"]} == {k for keys in FIRST_WAVE.values() for k in keys}
    assert {k for k, e in reg.REGISTRY.items() if e["secret"] and e["editable"]} == {
        "PLEX_TOKEN",
        "WATCHSTATE_API_KEY",
        "WEBHOOK_TOKEN",
    }


def test_validate_accepts_canonical_values_and_rejects_the_rest():
    assert reg.validate("REQUIRE_ENG", False) is False
    assert reg.validate("WHISPER_BEAM_SIZE", 5) == 5
    assert reg.validate("MIN_FREE_GB", 5) == 5.0
    assert reg.validate("COMPUTE_TYPE", "float16") == "float16"
    assert reg.validate("REVIEW_GATE_SHOWS", "Show A:Show B") == "Show A:Show B"
    for key, bad, message in [
        ("REQUIRE_ENG", 1, "must be true or false"),
        ("WHISPER_BEAM_SIZE", True, "must be a whole number"),
        ("WHISPER_BEAM_SIZE", 99, "must be between 1 and 20"),
        ("COMPUTE_TYPE", "int3", "must be one of"),
        ("ACQUIRE_MIN_SIM", 1.5, "must be between 0 and 1"),
        ("REVIEW_PORT", 0, "must be between 1 and 65535"),
        ("MERGE_WINDOW", "9-5", "use HH:MM-HH:MM"),
        ("PLEX_URL", "http://user:pw@plex.lan:32400", "must not contain a user name or password"),
        ("PLEX_URL", "ftp://plex.lan", "must be an http(s) URL"),
        ("PLEX_URL", "http://plex.lan/$(id)", "must be an http(s) URL"),
        ("WATCH_QUEUE_PIN", "two\nlines", "one line"),
        ("NOT_A_KEY", 1, "unknown setting"),
        ("PLEX_TOKEN", "abc", "secret field"),
        ("REVIEW_GATE_SHOWS", "One,Two", "use colon-separated show folder names"),
    ]:
        with pytest.raises(reg.Invalid, match=re.escape(message)):
            reg.validate(key, bad)


def test_environment_strings_round_trip_through_the_registry():
    assert reg.from_env("REQUIRE_ENG", "0") == (False, True)
    assert reg.from_env("REQUIRE_ENG", "banana") == ("banana", False)
    assert reg.from_env("ACQUIRE_APPLY", "dry-run") == (False, True)
    assert reg.from_env("WHISPER_BEAM_SIZE", "7") == (7, True)
    assert reg.from_env("WHISPER_BEAM_SIZE", "") == (None, True)
    assert reg.from_env("MIN_FREE_GB", "2.5") == (2.5, True)
    assert reg.to_env(True) == "1" and reg.to_env(False) == "0" and reg.to_env(7) == "7" and reg.to_env(0.72) == "0.72"


def test_keys_for_scope_hands_a_merge_pass_the_gen_keys_too():
    assert "WHISPER_BEAM_SIZE" in reg.keys_for_scope("gen")
    assert "REPAIR_UNANCHORED" not in reg.keys_for_scope("gen")
    assert {"WHISPER_BEAM_SIZE", "REPAIR_UNANCHORED"} <= set(reg.keys_for_scope("merge"))
    assert "REVIEW_PORT" in reg.keys_for_scope("server") and "MERGE_INTERVAL" in reg.keys_for_scope("container")


def test_anime_order_is_read_only_and_not_first_wave():
    assert "ANIME_ORDER" in reg.REGISTRY
    entry = reg.REGISTRY["ANIME_ORDER"]
    assert entry["editable"] is False
    assert entry["first_wave"] is False
    assert entry["category"] == "schedule"
    assert entry["type"] == "string"


def test_review_gate_shows_and_stale_days_help_and_rules():
    shows = reg.REGISTRY["REVIEW_GATE_SHOWS"]
    assert "colon-separated" in shows["help"].lower()
    assert "comma" not in shows["help"].lower()
    stale = reg.REGISTRY["REVIEW_GATE_STALE_DAYS"]
    assert "log line" in stale["help"].lower()


def test_pinned_scopes_for_decisions_requests_schedule_heartbeat():
    assert set(reg.REGISTRY["DECISIONS_DIR"]["scope"]) == {"merge", "server"}
    assert set(reg.REGISTRY["REQUESTS_DIR"]["scope"]) == {"gen", "server"}
    assert set(reg.REGISTRY["SCHEDULE_FILE"]["scope"]) == {"gen", "server"}
    assert set(reg.REGISTRY["HEARTBEAT_PATH"]["scope"]) == {"container", "gen", "merge", "server"}


def test_path_list_validation_accepts_absolute_and_rejects_relative():
    assert reg.validate("MUX_ROOTS", "/data/a:/data/b") == "/data/a:/data/b"
    assert reg.validate("MUX_ROOTS", "") == ""
    for bad in ("relative/path", "/absolute:relative", "rel/one:/data/two"):
        with pytest.raises(reg.Invalid, match="must be absolute paths separated by colons"):
            reg.validate("MUX_ROOTS", bad)


def test_from_env_rejects_bad_enum_and_malformed_numbers():
    assert reg.from_env("COMPUTE_TYPE", "invalid_enum") == ("invalid_enum", False)
    assert reg.from_env("WHISPER_BEAM_SIZE", "not_an_int") == ("not_an_int", False)
    assert reg.from_env("MIN_FREE_GB", "not_a_float") == ("not_a_float", False)
    assert reg.from_env("MIN_FREE_GB", "nan") == ("nan", False)
    assert reg.from_env("MIN_FREE_GB", "inf") == ("inf", False)
    assert reg.from_env("MIN_FREE_GB", "-inf") == ("-inf", False)


def test_url_help_mentions_tokens():
    for key in ("PLEX_URL", "WATCHSTATE_URL", "GITHUB_WIKI", "FORGEJO_WIKI"):
        assert "tokens belong in a secret field" in reg.REGISTRY[key]["help"]


def test_the_web_category_list_matches_the_registry():
    """web/src/lib/route.js hard-codes the nine categories so the sidebar can render before the schema loads."""
    text = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "src", "lib", "route.js")).read()
    listed = re.findall(r"\{ id: '([a-z]+)', label: '([A-Za-z]+)' \}", text)
    assert listed == [(c["id"], c["label"]) for c in reg.CATEGORIES]


def test_a_url_with_a_query_or_fragment_is_refused_everywhere():
    assert "query" in reg.url_problem("http://127.0.0.1:32400/?X-Plex-Token=abc")
    assert "query" in reg.url_problem("http://127.0.0.1:32400/#frag")
    assert reg.url_problem("http://127.0.0.1:32400/path") == ""
    with pytest.raises(reg.Invalid):
        reg.validate("PLEX_URL", "http://127.0.0.1:32400/?X-Plex-Token=abc")


def test_rescan_interval_is_read_by_the_server_too():
    assert set(reg.REGISTRY["RESCAN_INTERVAL"]["scope"]) == {"gen", "server"}
