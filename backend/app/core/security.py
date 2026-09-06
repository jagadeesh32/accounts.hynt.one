"""Password hashing and the small opaque-secret helpers."""
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Defaults tuned for a 2-vCPU box: ~64 MiB, 3 passes. Raising these later is
# safe — `needs_rehash` upgrades a user's hash on their next successful login.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except Exception:
        return True


def new_opaque_token(nbytes: int = 32) -> str:
    """The value that goes in the cookie / the authorization code."""
    return secrets.token_urlsafe(nbytes)


def sha256(value: str) -> str:
    """What actually gets stored. The row is not the credential."""
    return hashlib.sha256(value.encode()).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


PASSWORD_MIN_LENGTH = 10


def password_problem(password: str) -> str | None:
    """Length is the only rule worth enforcing; composition rules push people
    toward `Password1!` and nothing else."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
    if len(password) > 200:
        return "Password must be at most 200 characters."
    return None
