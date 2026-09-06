"""Append-only audit trail."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.http import jsonable
from app.models import AuditLog

# Authentication
LOGIN_SUCCESS = "auth.login.success"
LOGIN_FAILED = "auth.login.failed"
LOGIN_THROTTLED = "auth.login.throttled"
LOGOUT = "auth.logout"
PASSWORD_CHANGED = "auth.password.changed"
PASSWORD_RESET_REQUESTED = "auth.password.reset_requested"
PASSWORD_RESET_COMPLETED = "auth.password.reset_completed"
SESSIONS_REVOKED = "auth.sessions.revoked"

# OAuth
AUTHORIZE_GRANTED = "oauth.authorize.granted"
AUTHORIZE_DENIED = "oauth.authorize.denied"
TOKEN_ISSUED = "oauth.token.issued"
TOKEN_REUSE_DETECTED = "oauth.token.reuse_detected"

# Administration
USER_CREATED = "admin.user.created"
USER_UPDATED = "admin.user.updated"
USER_SUSPENDED = "admin.user.suspended"
USER_REINSTATED = "admin.user.reinstated"
USER_DELETED = "admin.user.deleted"
MEMBERSHIP_GRANTED = "admin.membership.granted"
MEMBERSHIP_REVOKED = "admin.membership.revoked"
MEMBERSHIP_ROLE_CHANGED = "admin.membership.role_changed"
SUBSCRIPTION_CHANGED = "admin.subscription.changed"
PLAN_CREATED = "admin.plan.created"
PLAN_UPDATED = "admin.plan.updated"
PLATFORM_CREATED = "admin.platform.created"
PLATFORM_UPDATED = "admin.platform.updated"
KEY_ROTATED = "admin.signing_key.rotated"


def record(
    db: Session,
    action: str,
    *,
    actor_user_id=None,
    target_type: str | None = None,
    target_id=None,
    platform_slug: str | None = None,
    ip: str | None = None,
    agent: str | None = None,
    **meta,
) -> None:
    """Never raises. An audit write that fails must not take the operation with
    it — losing one log line is bad, refusing a legitimate login because the log
    table is full is worse."""
    try:
        db.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action,
                target_type=target_type,
                target_id=str(target_id) if target_id is not None else None,
                platform_slug=platform_slug,
                ip_address=ip,
                user_agent=(agent or "")[:500] or None,
                meta=jsonable(meta) if meta else {},
                created_at=datetime.now(timezone.utc),
            )
        )
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("hynt.audit").exception("failed to write audit entry %s", action)
