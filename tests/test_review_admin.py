"""Admin-token helper (specs/webui-admin-token): header-only second secret for builder-affecting writes.

check_admin() returns None when allowed, else (403, payload) -- never raises, never logs the value."""

import secrets

import review_admin as ra

TOKEN = "admin-fixture-token"


def env(token=TOKEN, **extra):
    d = {} if token is None else {"REVIEW_ADMIN_TOKEN": token}
    d.update(extra)
    return d


# ---- source: env unset / empty --------------------------------------------------------------------------------------


def test_unset_token_is_empty_and_disabled():
    e = {}
    assert ra.admin_token(e) == ""
    assert ra.admin_enabled(e) is False


def test_empty_token_is_disabled():
    e = {"REVIEW_ADMIN_TOKEN": ""}
    assert ra.admin_token(e) == ""
    assert ra.admin_enabled(e) is False


def test_disabled_returns_disabled_for_any_presented():
    e = {}
    for presented in (None, "", "anything", TOKEN):
        assert ra.check_admin(presented, e) == (403, {"error": "admin writes are disabled"})


# ---- decisions: missing / wrong / right ------------------------------------------------------------------------------


def test_missing_presented_requires_admin_token():
    e = env()
    assert ra.check_admin(None, e) == (403, {"error": "admin token required"})
    assert ra.check_admin("", e) == (403, {"error": "admin token required"})


def test_wrong_token_requires_admin_token():
    e = env()
    assert ra.check_admin("nope", e) == (403, {"error": "admin token required"})
    assert ra.check_admin(TOKEN + "x", e) == (403, {"error": "admin token required"})


def test_right_token_is_allowed():
    assert ra.check_admin(TOKEN, env()) is None


def test_non_string_presented_is_just_wrong():
    e = env()
    assert ra.check_admin(5, e) == (403, {"error": "admin token required"})
    assert ra.check_admin(["x"], e) == (403, {"error": "admin token required"})


# ---- source: file variant ---------------------------------------------------------------------------------------------


def test_token_from_file(tmp_path):
    f = tmp_path / "admin_token"
    f.write_text("from-a-file\n", encoding="utf-8")
    e = {"REVIEW_ADMIN_TOKEN_FILE": str(f)}
    assert ra.admin_token(e) == "from-a-file"
    assert ra.admin_enabled(e) is True
    assert ra.check_admin("from-a-file", e) is None
    assert ra.check_admin("wrong", e) == (403, {"error": "admin token required"})


def test_token_file_with_surrounding_whitespace_is_stripped(tmp_path):
    f = tmp_path / "admin_token"
    f.write_text("  spaced-token \r\n", encoding="utf-8")
    e = {"REVIEW_ADMIN_TOKEN_FILE": str(f)}
    assert ra.admin_token(e) == "spaced-token"
    assert ra.check_admin("spaced-token", e) is None


def test_missing_or_empty_file_is_disabled(tmp_path):
    assert ra.admin_token({"REVIEW_ADMIN_TOKEN_FILE": str(tmp_path / "nope")}) == ""
    f = tmp_path / "empty"
    f.write_text("\n", encoding="utf-8")
    e = {"REVIEW_ADMIN_TOKEN_FILE": str(f)}
    assert ra.admin_token(e) == ""
    assert ra.check_admin(TOKEN, e) == (403, {"error": "admin writes are disabled"})


def test_env_wins_over_file(tmp_path):
    f = tmp_path / "admin_token"
    f.write_text("from-a-file\n", encoding="utf-8")
    e = {"REVIEW_ADMIN_TOKEN": TOKEN, "REVIEW_ADMIN_TOKEN_FILE": str(f)}
    assert ra.admin_token(e) == TOKEN


# ---- non-ASCII, constant time, no logging -------------------------------------------------------------------------------


def test_non_ascii_token():
    token = "pässwörd-日本語-🔑"
    e = env(token=token)
    assert ra.admin_token(e) == token
    assert ra.check_admin(token, e) is None
    assert ra.check_admin("passwort-日本語-🔑", e) == (403, {"error": "admin token required"})
    assert ra.check_admin("pässwörd-日本語-🔑x", e) == (403, {"error": "admin token required"})


def test_comparison_is_constant_time_on_utf8_bytes(monkeypatch):
    calls = []
    real = secrets.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(ra.secrets, "compare_digest", spy)
    assert ra.check_admin("wrong", env()) == (403, {"error": "admin token required"})
    assert ra.check_admin(TOKEN, env()) is None
    assert [type(a) for a, _ in calls] == [bytes, bytes]
    assert [type(b) for _, b in calls] == [bytes, bytes]


def test_different_lengths_still_go_through_compare_digest(monkeypatch):
    calls = []
    real = secrets.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(ra.secrets, "compare_digest", spy)
    ra.check_admin("short", env(token="a-much-longer-token"))
    assert len(calls) == 1, "no early return on length"


def test_token_value_never_reaches_the_log(capsys):
    e = env(token="s3cr3t-admin-value")
    ra.check_admin("s3cr3t-admin-value", e)
    ra.check_admin("guess-one-s3cr3t", e)
    ra.check_admin(None, {})
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "s3cr3t" not in out


def test_env_token_is_stripped_like_the_file_variant():
    e = {"REVIEW_ADMIN_TOKEN": "abc\r\n"}
    assert ra.admin_token(e) == "abc"
    assert ra.check_admin("abc", e) is None


def test_a_whitespace_only_env_token_is_disabled():
    e = {"REVIEW_ADMIN_TOKEN": " \t\r"}
    assert ra.admin_enabled(e) is False


def test_a_non_string_presented_value_is_never_coerced_to_a_match():
    e = {"REVIEW_ADMIN_TOKEN": "5"}
    for presented in (5, 5.0, b"5", ["5"], True):
        assert ra.check_admin(presented, e) == (403, {"error": "admin token required"}), presented


def test_ascii_and_non_ascii_wrong_values_take_the_same_comparison_path(monkeypatch):
    calls = []
    real = secrets.compare_digest

    def spy(a, b):
        calls.append((type(a), type(b)))
        return real(a, b)

    monkeypatch.setattr(secrets, "compare_digest", spy)
    ra.check_admin("wrong", env())
    ra.check_admin("wrongé", env())
    assert calls == [(bytes, bytes), (bytes, bytes)], "always UTF-8 bytes: no TypeError fallback to time differently"


def test_the_token_file_read_is_bounded(tmp_path):
    big = tmp_path / "big"
    big.write_text("a" * 4096 + "b" * 100000)
    assert ra.admin_token({"REVIEW_ADMIN_TOKEN_FILE": str(big)}) == "a" * 4096
