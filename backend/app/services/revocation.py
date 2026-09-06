"""Publishing revocations so they take effect in seconds, not in fifteen minutes.

Every path that takes access away — suspending an account, removing it from a
platform, ending a device, deleting a user — writes a record here. The platforms
poll for these and refuse matching tokens locally, which keeps the fast path
fast while making "revoke now" mean now.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import config
from app.models import RefreshToken, Revocation, User

#: How long a record stays published. A revoked token cannot outlive its own
#: expiry, so anything older than one access-token lifetime (plus slack for
#: clock skew and poll interval) can no longer match anything.
RETENTION_SEC = 3600


def publish(
    db: Session,
    user: User,
    *,
    platform_slug: str | None = None,
    reason: str = "",
    bump_version: bool = True,
) -> Revocation:
    """Invalidate the tokens this user currently holds.

    ``platform_slug=None`` revokes everywhere. Naming one platform revokes only
    that audience, so removing someone from x-terminal does not sign them out of
    the terminal they are actively trading on.
    """
    now = datetime.now(timezone.utc)

    if bump_version:
        # Every token already minted carries the old value and is now stale.
        user.token_version += 1
        db.flush()

    row = Revocation(
        user_id=user.id,
        platform_slug=platform_slug,
        min_token_version=user.token_version,
        reason=reason[:80],
        created_at=now,
        expires_at=now + timedelta(seconds=config.ACCESS_TOKEN_TTL_SEC + 120),
    )
    db.add(row)

    # Refresh tokens are stateful, so they can be withdrawn properly rather than
    # merely out-waited.
    stmt = select(RefreshToken).where(
        RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
    )
    for token in db.scalars(stmt):
        token.revoked_at = now

    db.flush()
    return row


def current(db: Session) -> list[dict]:
    """The live revocation list, for platforms to poll."""
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(Revocation).where(Revocation.expires_at > now).order_by(Revocation.created_at)
    ).all()

    # Collapse to the strongest entry per (user, platform): two revocations for
    # the same user differ only in how much they invalidate, and the newer one
    # always subsumes the older.
    best: dict[tuple[str, str | None], dict] = {}
    for row in rows:
        key = (str(row.user_id), row.platform_slug)
        entry = {
            "sub": str(row.user_id),
            "platform": row.platform_slug,
            "min_tv": row.min_token_version,
            "at": row.created_at.isoformat(),
        }
        existing = best.get(key)
        if existing is None or entry["min_tv"] >= existing["min_tv"]:
            best[key] = entry
    return list(best.values())


def prune(db: Session) -> int:
    """Drop records that can no longer match a live token."""
    now = datetime.now(timezone.utc)
    return db.execute(delete(Revocation).where(Revocation.expires_at <= now)).rowcount or 0
