import stat

import pytest

import review_auth

pytestmark = pytest.mark.real_accounts


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(review_auth, "_TOKEN_FALLBACK", lambda: "old-review-token")
    return tmp_path


def test_before_any_key_file_the_review_token_is_the_key(cfg):
    assert review_auth.api_key() == "old-review-token"
    assert review_auth.key_matches("old-review-token") is True
    assert review_auth.key_matches("old-review-tokeN") is False


def test_init_seeds_the_file_from_the_review_token_0600_and_is_idempotent(cfg, monkeypatch, capsys):
    review_auth.init_api_key()
    path = cfg / "apikey"
    assert path.read_text() == "old-review-token\n" and stat.S_IMODE(path.stat().st_mode) == 0o600
    monkeypatch.setattr(review_auth, "_TOKEN_FALLBACK", lambda: "a-different-token")
    review_auth.init_api_key()
    assert review_auth.api_key() == "old-review-token", "the stored key outranks the review token"
    assert "old-review-token" not in capsys.readouterr().out, "the key is never logged"


def test_a_review_token_that_differs_from_the_stored_key_is_logged_at_start_without_values(cfg, monkeypatch, capsys):
    review_auth.init_api_key()
    capsys.readouterr()
    monkeypatch.setenv("REVIEW_TOKEN", "rotated-token-in-compose")
    review_auth.init_api_key()
    out = capsys.readouterr().out
    assert "REVIEW_TOKEN differs from the stored API key" in out
    assert "rotated-token-in-compose" not in out and "old-review-token" not in out
    monkeypatch.setenv("REVIEW_TOKEN", "old-review-token")
    review_auth.init_api_key()
    assert "differs" not in capsys.readouterr().out


def test_init_without_any_review_token_generates_a_key(cfg, monkeypatch):
    monkeypatch.setattr(review_auth, "_TOKEN_FALLBACK", lambda: "")
    review_auth.init_api_key()
    key = (cfg / "apikey").read_text().strip()
    assert len(key) >= 43 and review_auth.key_matches(key)


def test_reset_returns_a_new_key_and_the_old_one_stops_matching(cfg):
    review_auth.init_api_key()
    new = review_auth.reset_api_key()
    assert len(new) >= 43 and new != "old-review-token"
    assert (cfg / "apikey").read_text() == new + "\n" and stat.S_IMODE((cfg / "apikey").stat().st_mode) == 0o600
    assert review_auth.key_matches(new) is True and review_auth.key_matches("old-review-token") is False


def test_reset_works_when_the_key_was_never_seeded(cfg):
    new = review_auth.reset_api_key()
    assert review_auth.key_matches(new) and not review_auth.key_matches("old-review-token")


@pytest.mark.parametrize("presented", ["", None, 5, b"old-review-token", ["old-review-token"]])
def test_only_a_non_empty_string_can_match(cfg, presented):
    assert review_auth.key_matches(presented) is False


def test_the_match_uses_compare_digest_on_bytes(cfg, monkeypatch):
    seen = []
    real = review_auth.secrets.compare_digest
    monkeypatch.setattr(review_auth.secrets, "compare_digest", lambda a, b: seen.append((type(a), type(b))) or real(a, b))
    review_auth.key_matches("old-review-token")
    assert seen == [(bytes, bytes)]


def test_an_unwritable_volume_logs_and_keeps_the_review_token_as_the_key(cfg, monkeypatch, capsys):
    def refuse(*a, **k):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(review_auth.os, "replace", refuse)
    review_auth.init_api_key()
    assert "could not store the API key" in capsys.readouterr().out
    assert review_auth.api_key() == "old-review-token"


def test_an_unreadable_key_file_after_a_reset_fails_closed_and_never_revives_the_old_token(cfg, capsys):
    review_auth.init_api_key()
    new = review_auth.reset_api_key()
    capsys.readouterr()
    (cfg / "apikey").chmod(0o000)
    try:
        assert review_auth.key_matches("old-review-token") is False
        assert review_auth.key_matches(new) is False
        assert review_auth.api_key() == ""
        out = capsys.readouterr().out
        assert out.count("API key file unreadable") == 1, "one log line, not one per request"
        assert new not in out and "old-review-token" not in out
    finally:
        (cfg / "apikey").chmod(0o600)


def test_a_missing_key_file_after_a_reset_neither_revives_nor_reseeds_the_old_token(cfg, monkeypatch):
    review_auth.init_api_key()
    review_auth.reset_api_key()
    (cfg / "apikey").unlink()
    assert review_auth.key_matches("old-review-token") is False, "this process"
    monkeypatch.setattr(review_auth, "_KEY_STORED", set())  # a later process: only the marker file remembers
    assert review_auth.key_matches("old-review-token") is False, "a later process"
    review_auth.init_api_key()
    fresh = (cfg / "apikey").read_text().strip()
    assert fresh != "old-review-token" and review_auth.key_matches(fresh)
    assert review_auth.key_matches("old-review-token") is False


def test_a_key_file_that_is_deleted_after_seeding_does_not_fall_back_to_the_review_token(cfg):
    review_auth.init_api_key()
    (cfg / "apikey").unlink()
    assert review_auth.key_matches("old-review-token") is False


def test_a_lone_surrogate_cannot_crash_the_match(cfg):
    assert review_auth.key_matches("abc\ud800") is False


def test_a_review_token_longer_than_512_characters_is_seeded_whole_and_still_matches(cfg, monkeypatch):
    long_token = "t" * 600
    monkeypatch.setattr(review_auth, "_TOKEN_FALLBACK", lambda: long_token)
    review_auth.init_api_key()
    assert review_auth.key_matches(long_token) is True


def test_reset_and_init_never_log_the_key(cfg, capsys):
    review_auth.init_api_key()
    new = review_auth.reset_api_key()
    review_auth.init_api_key()
    out = capsys.readouterr().out
    assert new not in out and "old-review-token" not in out
