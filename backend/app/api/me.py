"""The signed-in user's own account: profile, sessions, access, subscriptions."""

from __future__ import annotations

import re

from cello import Blueprint
from sqlalchemy import select

from app.core import audit, sessions
from app.core.authz import authenticated
from app.core.http import bad_request, body_json, conflict, not_found
from app.models import Membership, Subscription, User
from app.schemas.serializers import access_entry, session_public, user_public

bp = Blueprint("/api/v1/me")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.get("")
@authenticated
def profile(request, db, ctx):
    return {"user": user_public(ctx.user)}


@bp.patch("")
@authenticated
def update_profile(request, db, ctx):
    """Edit display name and avatar.

    Email is deliberately not editable here. It is the identity key across every
    platform, so changing it needs a verification round-trip rather than a PATCH.
    """
    data = body_json(request)

    if "full_name" in data:
        name = (data.get("full_name") or "").strip()
        if not name:
            raise bad_request("Your name cannot be empty.")
        ctx.user.full_name = name[:160]

    if "avatar_url" in data:
        ctx.user.avatar_url = (data.get("avatar_url") or "").strip() or None

    audit.record(db, audit.USER_UPDATED, actor_user_id=ctx.user.id, target_type="user",
                 target_id=ctx.user.id, ip=ctx.ip, agent=ctx.agent, self_service=True)
    return {"user": user_public(ctx.user)}


@bp.get("/access")
@authenticated
def my_access(request, db, ctx):
    """Every platform this account can reach, with role, permissions and plan.

    This is what the accounts dashboard renders as the app launcher, and what a
    platform can call to decide whether to offer a link to its siblings.
    """
    memberships = db.scalars(
        select(Membership).where(Membership.user_id == ctx.user.id, Membership.active.is_(True))
    ).all()
    subs = {
        s.platform_id: s
        for s in db.scalars(select(Subscription).where(Subscription.user_id == ctx.user.id))
    }
    entries = [access_entry(m, subs.get(m.platform_id)) for m in memberships]
    entries.sort(key=lambda e: e["platform"]["sort_order"])
    return {"access": entries, "is_superadmin": ctx.user.is_superadmin}


@bp.get("/sessions")
@authenticated
def my_sessions(request, db, ctx):
    """Live sessions, so a user can see and end a login they do not recognise."""
    rows = sessions.list_for_user(db, ctx.user.id)
    return {"sessions": [session_public(r, current_id=ctx.session.id) for r in rows]}


@bp.delete("/sessions/{session_id}")
@authenticated
def end_session(request, db, ctx):
    """End one other session. The current one is refused — that is what logout
    is for, and ending it here would leave the SPA holding a dead cookie with no
    Set-Cookie to clear it."""
    target_id = request.params.get("session_id")

    if str(ctx.session.id) == target_id:
        raise bad_request("Use sign out to end the session you are using.",
                          code="cannot_end_current")

    for row in sessions.list_for_user(db, ctx.user.id):
        if str(row.id) == target_id:
            sessions.revoke(db, row)
            audit.record(db, audit.SESSIONS_REVOKED, actor_user_id=ctx.user.id,
                         target_type="session", target_id=row.id, ip=ctx.ip, agent=ctx.agent)
            return {"ok": True}

    raise not_found("That session no longer exists.")


@bp.post("/sessions/revoke-all")
@authenticated
def revoke_all(request, db, ctx):
    """Sign out everywhere else, and invalidate every access token already issued
    by bumping ``token_version``."""
    revoked = sessions.revoke_all_for_user(db, ctx.user.id, except_session_id=ctx.session.id)
    ctx.user.token_version += 1
    audit.record(db, audit.SESSIONS_REVOKED, actor_user_id=ctx.user.id, ip=ctx.ip,
                 agent=ctx.agent, count=revoked, all_devices=True)
    return {"ok": True, "sessions_revoked": revoked}
