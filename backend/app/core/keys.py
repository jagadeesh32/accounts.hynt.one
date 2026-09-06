"""RSA signing keys and the published JWKS.

Every platform verifies tokens locally against these public keys. That is the
whole reason the estate scales: a request on terminal.hynt.one is authorised
with a signature check, not a network call back to this service.
"""

from __future__ import annotations

import base64
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.core.security import new_secret
from app.models import SigningKey

log = logging.getLogger("hynt.keys")

# Cached because minting a token would otherwise be a database read per request.
# Guarded by a lock: Cello runs sync handlers on a threadpool, so two requests
# can reach a cold cache at the same moment.
_lock = threading.Lock()
_cached_active: tuple[str, str] | None = None    # (kid, private_pem)
_cached_jwks: dict | None = None


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _public_jwk(private_key: rsa.RSAPrivateKey, kid: str) -> dict:
    numbers = private_key.public_key().public_numbers()
    byte_len = (numbers.n.bit_length() + 7) // 8
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": config.JWT_ALG,
        "kid": kid,
        "n": _b64u(numbers.n.to_bytes(byte_len, "big")),
        "e": _b64u(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
    }


def generate_keypair() -> tuple[str, str, dict]:
    """Return ``(kid, private_pem, public_jwk)`` for a fresh RSA-2048 key."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = new_secret(12)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return kid, private_pem, _public_jwk(private_key, kid)


def ensure_key(session: Session) -> SigningKey:
    """Return the active key, creating one on first boot.

    In production a key is expected to be provisioned already (via
    ``HYNT_SIGNING_KEY_PATH`` or ``scripts/manage.py keygen``); generating one
    silently there would mean a redeploy onto an empty database invalidates every
    live session across all three platforms. It is loud about that.
    """
    key = session.scalar(
        select(SigningKey).where(SigningKey.active.is_(True)).order_by(SigningKey.created_at.desc())
    )
    if key is not None:
        return key

    if config.SIGNING_KEY_PATH:
        pem = Path(config.SIGNING_KEY_PATH).read_text()
        private_key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise RuntimeError(f"{config.SIGNING_KEY_PATH} is not an RSA private key")
        kid = new_secret(12)
        jwk = _public_jwk(private_key, kid)
    else:
        if config.IS_PROD:
            log.error(
                "no signing key in the database and HYNT_SIGNING_KEY_PATH is unset — "
                "generating one, which invalidates every token issued by the previous key"
            )
        kid, pem, jwk = generate_keypair()

    key = SigningKey(
        kid=kid, alg=config.JWT_ALG, private_pem=pem, public_jwk=jwk,
        active=True, created_at=datetime.now(timezone.utc),
    )
    session.add(key)
    session.flush()
    log.info("signing key %s created", kid)
    return key


def active_key(session: Session) -> tuple[str, str]:
    """``(kid, private_pem)`` of the key new tokens are signed with."""
    global _cached_active
    if _cached_active is not None:
        return _cached_active
    with _lock:
        if _cached_active is None:
            key = ensure_key(session)
            _cached_active = (key.kid, key.private_pem)
    return _cached_active


def jwks(session: Session) -> dict:
    """Every public key still worth trusting — the active one plus retired keys
    whose tokens have not all expired yet."""
    global _cached_jwks
    if _cached_jwks is not None:
        return _cached_jwks
    with _lock:
        if _cached_jwks is None:
            ensure_key(session)
            keys = session.scalars(
                select(SigningKey).where(SigningKey.retired_at.is_(None)).order_by(
                    SigningKey.active.desc(), SigningKey.created_at.desc()
                )
            ).all()
            _cached_jwks = {"keys": [k.public_jwk for k in keys]}
    return _cached_jwks


def rotate(session: Session) -> SigningKey:
    """Mint a new active key and demote the current one.

    The old key stays published (``retired_at`` is left NULL) so tokens already
    in flight keep verifying until they expire on their own.
    """
    for old in session.scalars(select(SigningKey).where(SigningKey.active.is_(True))):
        old.active = False
    kid, pem, jwk = generate_keypair()
    key = SigningKey(
        kid=kid, alg=config.JWT_ALG, private_pem=pem, public_jwk=jwk,
        active=True, created_at=datetime.now(timezone.utc),
    )
    session.add(key)
    session.flush()
    invalidate_cache()
    log.warning("signing key rotated to %s", kid)
    return key


def invalidate_cache() -> None:
    global _cached_active, _cached_jwks
    with _lock:
        _cached_active = None
        _cached_jwks = None
