"""Passwords, opaque secrets and constant-time helpers.

One implementation, for all four codebases. Before this existed, terminal used
PBKDF2, intelligence used scrypt and xterminal used a different scrypt — three
parameter sets to keep current, and no way to move a user between platforms.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError, VerificationError

# Argon2id at interactive-login cost. `time_cost`/`memory_cost` are embedded in
# every stored hash, so raising them later re-hashes users on their next login
# (see `needs_rehash`) without invalidating existing passwords.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,   # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

#: Verified against when the account does not exist, so an unknown address costs
#: the same CPU as a known one. Without it, response time answers "does this
#: email have an account here?" for anyone who cares to measure.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    """False for a wrong password, a missing user, or a corrupt hash — and takes
    the same time in every case."""
    try:
        _hasher.verify(stored_hash or _DUMMY_HASH, password)
        return stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True when the hash was made with weaker parameters than the current ones."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True


# --------------------------------------------------------------------------- #
#  Opaque secrets
# --------------------------------------------------------------------------- #
def new_secret(nbytes: int = 32) -> str:
    """A URL-safe random string for session ids, auth codes and refresh tokens."""
    return secrets.token_urlsafe(nbytes)


def token_digest(raw: str) -> str:
    """SHA-256 hex of a bearer secret, for storage.

    Plain SHA-256 rather than Argon2 on purpose: these values are 256 bits of
    entropy already, so there is nothing to brute-force, and this runs on every
    single request that presents a cookie.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
