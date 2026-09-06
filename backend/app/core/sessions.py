"""The SSO session: one row, one cookie, revocable by definition."""
import uuid
from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import new_opaque_token, sha256
from app.models.base import utcnow
from app.models.identity import Session, User


async def create_session(db: AsyncSession, user: User, request: Request) -> tuple[Session, str]:
    """Returns (row, raw_cookie_value). The raw value is never stored."""
    raw = new_opaque_token(32)
    row = Session(
        user_id=user.id,
        token_hash=sha256(raw),
        user_agent=(request.headers.get("user-agent") or "")[:400],
        ip=client_ip(request),
        expires_at=utcnow() + timedelta(days=settings.session_ttl_days),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, raw


async def resolve_session(db: AsyncSession, request: Request) -> tuple[Session, User] | None:
    """Cookie → (session, user), or None if anything about it is not current."""
    raw = request.cookies.get(settings.cookie_name)
    if not raw:
        return None

    row = (
        await db.execute(select(Session).where(Session.token_hash == sha256(raw)))
    ).scalars().first()
    if row is None or row.revoked_at is not None:
        return None

    now = utcnow()
    if row.expires_at <= now:
        return None
    # Idle expiry is separate from absolute expiry: a session left alone for a
    # week dies even though its 30-day window is still open.
    if row.last_seen_at + timedelta(days=settings.session_idle_days) <= now:
        return None

    user = await db.get(User, row.user_id)
    if user is None or user.status != "active":
        return None

    # Cheap heartbeat — one write a minute per session at most.
    if (now - row.last_seen_at).total_seconds() > 60:
        row.last_seen_at = now
        await db.commit()

    return row, user


async def revoke_session(db: AsyncSession, row: Session) -> None:
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        await db.commit()


async def revoke_all_sessions(db: AsyncSession, user_id: uuid.UUID, *, except_id: uuid.UUID | None = None) -> int:
    rows = (
        await db.execute(
            select(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None))
        )
    ).scalars().all()
    now = utcnow()
    count = 0
    for row in rows:
        if except_id and row.id == except_id:
            continue
        row.revoked_at = now
        count += 1
    if count:
        await db.commit()
    return count


def set_session_cookie(response: Response, raw: str) -> None:
    """Cello stored response headers in a HashMap, so a response could carry only
    one Set-Cookie — the reason this design has exactly one cookie and returns
    access tokens in the body. The constraint is kept: do not add a second."""
    response.set_cookie(
        key=settings.cookie_name,
        value=raw,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain or None,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.cookie_name,
        domain=settings.cookie_domain or None,
        path="/",
    )


def client_ip(request: Request) -> str:
    """Behind nginx, so X-Forwarded-For's first hop is the real client."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]
