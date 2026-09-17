"""TOTP second factor: the secret's at-rest encryption, replay-safe
verification, and the recovery codes that stand in for a lost phone.

Why the secret is encrypted and not just hashed: TOTP needs the raw key to
compute the expected code, so a hash would be useless. Fernet (AES-128-CBC +
HMAC) under a key that lives only in the systemd EnvironmentFile means a dump
of the users table no longer hands out every second factor in the estate.
"""
import secrets
import time

import pyotp
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.core.security import constant_time_eq, sha256

TOTP_STEP_SECONDS = 30
# One step either side: phone clocks drift and people are slow to type.
TOTP_WINDOW = 1

RECOVERY_CODE_COUNT = 10
# 10 chars of a 32-symbol alphabet = 50 bits, which is why a plain SHA-256 is
# enough here where a password would need argon2. The alphabet drops the
# characters people misread from a printout (0/O, 1/I/L).
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_RECOVERY_LENGTH = 10

_fernet = Fernet(settings.mfa_encryption_key.encode())


def encrypt_secret(secret: str) -> str:
    return _fernet.encrypt(secret.encode()).decode()


def decrypt_secret(stored: str) -> str:
    try:
        return _fernet.decrypt(stored.encode()).decode()
    except InvalidToken as exc:
        # Wrong HYNT_MFA_ENCRYPTION_KEY, most likely — every MFA user would be
        # locked out, so fail loudly rather than as "code did not match".
        raise RuntimeError("stored MFA secret does not decrypt under HYNT_MFA_ENCRYPTION_KEY") from exc


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="Hynt")


def current_step(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // TOTP_STEP_SECONDS)


def match_totp(secret: str, code: str, last_used_step: int | None, now: float | None = None) -> int | None:
    """Returns the time step the code was minted for, or None if it does not
    match — or if it matches a step that has already been spent.

    A valid TOTP is good for up to 90 seconds with our window; without the
    step check, anyone who shoulder-surfs one code can replay it inside that
    window. Strictly increasing steps close that gap at no cost to the user
    (the next code is always a later step)."""
    code = code.strip().replace(" ", "")
    if not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    step = current_step(now)
    for candidate in range(step - TOTP_WINDOW, step + TOTP_WINDOW + 1):
        if constant_time_eq(totp.at(candidate * TOTP_STEP_SECONDS), code):
            if last_used_step is not None and candidate <= last_used_step:
                return None
            return candidate
    return None


def generate_recovery_codes() -> list[str]:
    """Plain codes, shown to the user exactly once. Store only hash_recovery_code()."""
    out = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_LENGTH))
        out.append(f"{raw[:5]}-{raw[5:]}")
    return out


def normalise_recovery_code(code: str) -> str:
    return code.strip().lower().replace("-", "").replace(" ", "")


def hash_recovery_code(code: str) -> str:
    return sha256(normalise_recovery_code(code))


def looks_like_recovery_code(code: str) -> bool:
    return len(normalise_recovery_code(code)) == _RECOVERY_LENGTH
