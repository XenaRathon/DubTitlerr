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
