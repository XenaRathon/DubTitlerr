import hashlib

import pytest

import review_auth


def test_hash_has_the_documented_shape_and_never_holds_the_password():
    stored = review_auth.hash_password("correct horse battery")
    scheme, n, r, p, salt, dk = stored.split("$")
    assert (scheme, int(n), int(r), int(p)) == ("scrypt", 2**14, 8, 1)
    assert len(bytes.fromhex(salt)) == 16 and len(bytes.fromhex(dk)) == 32
    assert "correct horse" not in stored


def test_two_hashes_of_one_password_use_different_salts():
    a, b = review_auth.hash_password("same password!"), review_auth.hash_password("same password!")
    assert a != b and a.split("$")[4] != b.split("$")[4]


def test_verify_accepts_the_right_password_and_refuses_a_wrong_one():
    stored = review_auth.hash_password("correct horse battery")
    assert review_auth.verify_password("correct horse battery", stored) is True
    assert review_auth.verify_password("correct horse batterz", stored) is False
    assert review_auth.verify_password("", stored) is False
    assert review_auth.verify_password(None, stored) is False


def test_verify_compares_with_compare_digest(monkeypatch):
    stored = review_auth.hash_password("correct horse battery")
    calls = []
    real = review_auth.secrets.compare_digest
    monkeypatch.setattr(review_auth.secrets, "compare_digest", lambda a, b: calls.append((type(a), type(b))) or real(a, b))
    assert review_auth.verify_password("correct horse battery", stored) is True
    assert calls == [(bytes, bytes)]


@pytest.mark.parametrize(
    "stored",
    [
        "not-a-hash",
        "",
        "scrypt$x$8$1$00$00",
        "bcrypt$16384$8$1$00$00",
        "scrypt$16384$8$1$zz$00",
        "scrypt$16384$8$1$00$00",
        "scrypt$18446744073709551616$8$1$00$00",
        None,
    ],
)
def test_a_malformed_or_foreign_hash_is_false_and_still_costs_one_scrypt(monkeypatch, stored):
    calls = []
    real = hashlib.scrypt

    def counted(*a, **k):
        out = real(*a, **k)  # a call the library rejects outright did no work, so only completed calls count
        calls.append(1)
        return out

    monkeypatch.setattr(review_auth.hashlib, "scrypt", counted)
    assert review_auth.verify_password("whatever-long-enough", stored) is False
    assert len(calls) == 1


def test_the_dummy_hash_is_a_real_hash_made_once_that_matches_nothing_typed():
    d = review_auth.dummy_hash()
    assert d.startswith("scrypt$") and review_auth.dummy_hash() == d
    assert review_auth.verify_password("", d) is False


def test_scrypt_is_available_here_and_reported_missing_when_the_primitive_is_gone(monkeypatch):
    assert review_auth.scrypt_available() is True
    monkeypatch.delattr(review_auth.hashlib, "scrypt")
    assert review_auth.scrypt_available() is False


@pytest.mark.parametrize("name", ["a", "Rev.iew_er-1", "x" * 64])
def test_valid_usernames(name):
    assert review_auth.validate_username(name) is None


@pytest.mark.parametrize("name", ["", "x" * 65, "has space", "sl/ash", "ünï", "a\n", 5, None])
def test_invalid_usernames_get_a_message(name):
    assert isinstance(review_auth.validate_username(name), str)


@pytest.mark.parametrize(
    "pw,ok", [("x" * 9, False), ("x" * 10, True), ("x" * 256, True), ("x" * 257, False), (None, False), (12345678901, False)]
)
def test_password_length_limits(pw, ok):
    assert (review_auth.validate_password(pw) is None) is ok
