"""SSO session lifecycle: create, resolve, touch, revoke.

This is the centre of the whole design. The cookie at ``.hynt.one`` is the fact
that the user is signed in; every platform's access derives from it through the
authorization-code flow, and revoking a row here is what makes a single logout
actually reach all three platforms.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import config
from app.core.security import new_secret, token_digest
from app.models import SsoSession, User, UserStatus


def create(db: Session, user: User, *, ip: str | None, agent: str | None) -> tuple[SsoSession, str]:
    """Return the row and the raw secret to put in the cookie.

    The raw value is returned once and never stored; only its SHA-256 lands in
    the table.
    """
    now = datetime.now(timezone.utc)
    raw = new_secret(32)
    row = SsoSession(
        user_id=user.id,
        token_hash=token_digest(raw),
        user_agent=(agent or "")[:500] or None,
        ip_address=ip,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(seconds=config.SESSION_TTL_SEC),
    )
    db.add(row)
    db.flush()
    return row, raw


def resolve(db: Session, raw: str | None) -> tuple[SsoSession, User] | None:
    """Look up a live session and its user, or None.

    Four things can make a cookie worthless and all of them are checked here:
    the row is gone, it was revoked, it aged out (absolute or idle), or the
    account behind it is no longer active.
    """
    if not raw:
        return None

    row = db.scalar(select(SsoSession).where(SsoSession.token_hash == token_digest(raw)))
    if row is None or row.revoked_at is not None:
        return None

    now = datetime.now(timezone.utc)
    if _aware(row.expires_at) <= now:
        return None
    if _aware(row.last_seen_at) + timedelta(seconds=config.SESSION_IDLE_TTL_SEC) <= now:
        return None

    user = db.get(User, row.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        return None

    return row, user


def touch(db: Session, row: SsoSession) -> None:
    """Advance the idle clock.

    Written at most once a minute: without the guard this turns every
    authenticated GET into a write, and the row is contended by definition.
    """
    now = datetime.now(timezone.utc)
    if (now - _aware(row.last_seen_at)).total_seconds() >= 60:
        row.last_seen_at = now


def revoke(db: Session, row: SsoSession) -> None:
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)


def revoke_all_for_user(db: Session, user_id, *, except_session_id=None) -> int:
    """Sign out everywhere. Returns the number of sessions ended."""
    now = datetime.now(timezone.utc)
    stmt = (
        update(SsoSession)
        .where(SsoSession.user_id == user_id, SsoSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    if except_session_id is not None:
        stmt = stmt.where(SsoSession.id != except_session_id)
    return db.execute(stmt).rowcount or 0


def list_for_user(db: Session, user_id) -> list[SsoSession]:
    now = datetime.now(timezone.utc)
    return list(
        db.scalars(
            select(SsoSession)
            .where(
                SsoSession.user_id == user_id,
                SsoSession.revoked_at.is_(None),
                SsoSession.expires_at > now,
            )
            .order_by(SsoSession.last_seen_at.desc())
        )
    )


def _aware(value: datetime) -> datetime:
    """psycopg2 returns aware datetimes for timestamptz, but a value that came
    from a naive default would compare as if it were UTC and silently skew every
    expiry check. Normalise rather than trust."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
