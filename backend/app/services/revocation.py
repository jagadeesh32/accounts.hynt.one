"""The published revocation list.

Local verification means a token stays cryptographically valid until it expires.
This list is what makes "revoke now" mean now: platforms poll it every ~30s.

Entries carry their own expiry — once the last token that could have been signed
before the revocation has expired, listing the subject is pure noise, so it is
pruned. That keeps the response small enough to stay a single cached request.
"""
import uuid
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.base import utcnow
from app.models.oauth import Revocation


def _horizon():
    # Two token lifetimes: one for a token minted the instant before revocation,
    # one of slack for clock skew between this box and a platform's.
    return utcnow() + timedelta(seconds=settings.access_token_ttl_seconds * 2)


async def revoke_user(db: AsyncSession, user_id: uuid.UUID, reason: str = "", commit: bool = True) -> None:
    db.add(Revocation(subject_type="user", subject_id=str(user_id), reason=reason, expires_at=_horizon()))
    if commit:
        await db.commit()


async def revoke_session_id(db: AsyncSession, session_id: uuid.UUID, reason: str = "", commit: bool = True) -> None:
    db.add(Revocation(subject_type="session", subject_id=str(session_id), reason=reason, expires_at=_horizon()))
    if commit:
        await db.commit()


async def prune(db: AsyncSession) -> int:
    result = await db.execute(delete(Revocation).where(Revocation.expires_at <= utcnow()))
    await db.commit()
    return result.rowcount or 0


async def current(db: AsyncSession) -> dict:
    """The payload platforms cache. `poll_after` tells a client how long it may
    hold this before asking again — the polling interval lives on the server so
    it can be changed without redeploying every platform."""
    await prune(db)
    rows = (
        await db.execute(select(Revocation).order_by(Revocation.created_at.desc()).limit(5000))
    ).scalars().all()
    now = utcnow()
    return {
        "generated_at": now.isoformat(),
        "poll_after": 30,
        "users": sorted({r.subject_id for r in rows if r.subject_type == "user"}),
        "sessions": sorted({r.subject_id for r in rows if r.subject_type == "session"}),
    }
