"""RS256 signing keys and the JWKS they are published as.

Keys live in the database so every worker signs with the same key and a
rotation is one transaction rather than a file copied around the box.
"""
import base64
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.oauth import SigningKey


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate_keypair() -> tuple[str, str, str]:
    """Returns (kid, private_pem, public_pem)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return uuid.uuid4().hex[:16], private_pem, public_pem


async def get_active_key(db: AsyncSession) -> SigningKey:
    key = (
        await db.execute(
            select(SigningKey).where(SigningKey.is_active.is_(True)).order_by(SigningKey.created_at.desc())
        )
    ).scalars().first()
    if key is None:
        kid, priv, pub = generate_keypair()
        key = SigningKey(kid=kid, private_pem=priv, public_pem=pub, is_active=True)
        db.add(key)
        await db.commit()
        await db.refresh(key)
    return key


async def rotate_key(db: AsyncSession) -> SigningKey:
    """New active key; the previous one is retired but its public half stays in
    the JWKS so tokens already in flight keep verifying until they expire."""
    now = utcnow()
    for old in (await db.execute(select(SigningKey).where(SigningKey.is_active.is_(True)))).scalars():
        old.is_active = False
        old.retired_at = now
    kid, priv, pub = generate_keypair()
    key = SigningKey(kid=kid, private_pem=priv, public_pem=pub, is_active=True)
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key


def jwk_from_public_pem(kid: str, public_pem: str) -> dict:
    pub = serialization.load_pem_public_key(public_pem.encode())
    numbers = pub.public_numbers()
    n = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
    e = numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid, "n": _b64u(n), "e": _b64u(e)}


async def jwks(db: AsyncSession) -> dict:
    """Every key that could have signed a token still alive — active first."""
    keys = (await db.execute(select(SigningKey).order_by(SigningKey.is_active.desc(), SigningKey.created_at.desc()))).scalars().all()
    if not keys:
        keys = [await get_active_key(db)]
    return {"keys": [jwk_from_public_pem(k.kid, k.public_pem) for k in keys]}
