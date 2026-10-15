"""Accounts, sessions, the API key and the route-role table for the review server (specs/webui-login-roles).

Stdlib only: hashlib.scrypt for passwords, secrets for ids and keys. Nothing here imports review_server; the server
hands in the one thing it owns (the legacy review token) through set_token_fallback().
"""

from __future__ import annotations

import hashlib
import re
import secrets

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024  # OpenSSL's default cap is 32 MiB; n=2^14, r=8 needs about 16 MiB
ROLES = ("admin", "user")
MIN_PASSWORD, MAX_PASSWORD = 10, 256
_USERNAME = re.compile(r"[A-Za-z0-9._-]{1,64}")
_DUMMY = None


def scrypt_available() -> bool:
    try:
        hashlib.scrypt(b"probe", salt=b"0123456789abcdef", n=2, r=1, p=1, dklen=8)
        return True
    except (AttributeError, ValueError, OSError):
        return False


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32, maxmem=_SCRYPT_MAXMEM)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password, stored) -> bool:
    """True when ``password`` matches ``stored``. Always costs one scrypt, also for a malformed hash or a non-string."""
    try:
        scheme, n, r, p, salt, dk = stored.split("$")
        if scheme != "scrypt":
            raise ValueError("not a scrypt hash")
        want = bytes.fromhex(dk)
        got = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(want),
            maxmem=_SCRYPT_MAXMEM,
        )
        return secrets.compare_digest(got, want)
    except (ValueError, AttributeError, TypeError):
        hashlib.scrypt(b"x", salt=b"0123456789abcdef", n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32, maxmem=_SCRYPT_MAXMEM)
        return False


def dummy_hash() -> str:
    """What login verifies against when the username does not exist, so a miss takes as long as a wrong password."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password(secrets.token_urlsafe(24))
    return _DUMMY


def validate_username(name) -> str | None:
    if not isinstance(name, str) or not _USERNAME.fullmatch(name):
        return "username must be 1 to 64 characters: letters, digits, '.', '_' or '-'"
    return None


def validate_password(password) -> str | None:
    if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        return f"password must be {MIN_PASSWORD} to {MAX_PASSWORD} characters"
    return None
