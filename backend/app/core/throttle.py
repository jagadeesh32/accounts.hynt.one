"""Login brute-force throttle, backed by a table.

Keyed on ``email|ip`` so that hammering one address from somewhere else cannot
lock the real owner out from their own machine — a per-email-only counter turns
into a denial-of-service against any address an attacker knows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.models import LoginAttempt


def _key(email: str | None, ip: str | None) -> str:
    return f"{(email or '-').strip().lower()}|{ip or '-'}"


def check(db: Session, email: str | None, ip: str | None) -> int:
    """Seconds the caller must wait; 0 when they may try now."""
    row = db.scalar(select(LoginAttempt).where(LoginAttempt.scope_key == _key(email, ip)))
    if row is None or row.locked_until is None:
        return 0
    remaining = (_aware(row.locked_until) - datetime.now(timezone.utc)).total_seconds()
    return max(0, int(remaining))


def record_failure(db: Session, email: str | None, ip: str | None) -> None:
    now = datetime.now(timezone.utc)
    key = _key(email, ip)
    row = db.scalar(select(LoginAttempt).where(LoginAttempt.scope_key == key))

    if row is None:
        db.add(
            LoginAttempt(scope_key=key, failures=1, first_failure_at=now, last_failure_at=now)
        )
        return

    # A quiet window clears the count, so an honest user who mistyped their
    # password twice last week starts from zero today.
    if (now - _aware(row.first_failure_at)).total_seconds() > config.LOGIN_WINDOW_SEC:
        row.failures = 1
        row.first_failure_at = now
        row.locked_until = None
    else:
        row.failures += 1

    row.last_failure_at = now
    if row.failures >= config.LOGIN_MAX_ATTEMPTS:
        # Back off exponentially past the threshold rather than unlocking into
        # the same fixed window over and over.
        over = row.failures - config.LOGIN_MAX_ATTEMPTS
        penalty = min(config.LOGIN_LOCKOUT_SEC * (2**over), 24 * 3600)
        row.locked_until = now + timedelta(seconds=penalty)


def clear(db: Session, email: str | None, ip: str | None) -> None:
    row = db.scalar(select(LoginAttempt).where(LoginAttempt.scope_key == _key(email, ip)))
    if row is not None:
        db.delete(row)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
