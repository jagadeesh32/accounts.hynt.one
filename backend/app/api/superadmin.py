"""Total control over an account, for a superadmin.

Everything a superadmin needs to answer "who is this person, what can they
reach, where are they signed in, and what have they been doing" — and to take
any of it away immediately.

Revocation here is not advisory. Each action writes to the revocation list that
the platforms poll, so access stops within seconds rather than whenever the
current access token happens to expire.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cello import Blueprint
from sqlalchemy import delete, func, or_, select

from app.core import audit, sessions
from app.core.authz import require_superadmin
from app.core.http import bad_request, body_json, conflict, field, forbidden, not_found, ok, query
from app.models import (
    AuditLog,
    AuthorizationCode,
    Membership,
    Organization,
    PasswordReset,
    Platform,
    RefreshToken,
    Revocation,
    SsoSession,
    Subscription,
    User,
    UserStatus,
)
from app.schemas.serializers import (
    membership_public,
    platform_public,
    session_public,
    subscription_public,
    user_public,
)
from app.services import provisioning, revocation

bp = Blueprint("/api/v1/admin")


def _user_or_404(db, user_id: str) -> User:
    try:
        user = db.get(User, user_id)
    except Exception:  # a malformed UUID is a 404, not a 500
        user = None
    if user is None:
        raise not_found("No such user.")
    return user


def _page(request) -> tuple[int, int]:
    limit = min(max(int(query(request, "limit", "50") or 50), 1), 200)
    offset = max(int(query(request, "offset", "0") or 0), 0)
    return limit, offset


# --------------------------------------------------------------------------- #
#  The complete picture of one account
# --------------------------------------------------------------------------- #
@bp.get("/users/{user_id}/overview")
@require_superadmin
def user_overview(request, db, ctx):
    """Identity, access, devices and recent activity in one call.

    One round-trip rather than five, because the console renders all of it on a
    single screen and five separate loading states is a worse answer to "what is
    going on with this account".
    """
    user = _user_or_404(db, request.params.get("user_id"))

    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    subs = {
        s.platform_id: s
        for s in db.scalars(select(Subscription).where(Subscription.user_id == user.id))
    }
    live_sessions = sessions.list_for_user(db, user.id)

    recent = db.scalars(
        select(AuditLog)
        .where(or_(AuditLog.actor_user_id == user.id, AuditLog.target_id == str(user.id)))
        .order_by(AuditLog.created_at.desc())
        .limit(20)
    ).all()

    active_refresh = db.scalar(
        select(func.count()).select_from(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    org = db.get(Organization, user.org_id)

    return {
        "user": user_public(user),
        "organization": {"id": str(org.id), "name": org.name, "slug": org.slug} if org else None,
        "access": [
            {
                "membership": membership_public(m),
                "subscription": subscription_public(subs[m.platform_id])
                if m.platform_id in subs
                else None,
            }
            for m in memberships
        ],
        "sessions": [session_public(s) for s in live_sessions],
        "active_refresh_tokens": active_refresh or 0,
        "token_version": user.token_version,
        "recent_activity": [_audit_row(entry) for entry in recent],
    }


def _audit_row(entry: AuditLog) -> dict:
    from app.core.http import jsonable

    return jsonable(
        {
            "id": entry.id,
            "action": entry.action,
            "actor_user_id": entry.actor_user_id,
            "target_type": entry.target_type,
            "target_id": entry.target_id,
            "platform_slug": entry.platform_slug,
            "ip_address": entry.ip_address,
            "user_agent": entry.user_agent,
            "meta": entry.meta,
            "created_at": entry.created_at,
        }
    )


# --------------------------------------------------------------------------- #
#  Activity
# --------------------------------------------------------------------------- #
@bp.get("/users/{user_id}/activity")
@require_superadmin
def user_activity(request, db, ctx):
    """Everything this account has done, and everything done to it.

    Both directions matter: ``actor_user_id`` covers their own sign-ins and
    actions, ``target_id`` covers an administrator suspending them or changing
    their role. Showing only the first would hide exactly the entries someone
    investigating an account most needs.
    """
    user = _user_or_404(db, request.params.get("user_id"))
    limit, offset = _page(request)

    stmt = select(AuditLog).where(
        or_(AuditLog.actor_user_id == user.id, AuditLog.target_id == str(user.id))
    )
    action = query(request, "action")
    if action:
        stmt = stmt.where(AuditLog.action == action)
    platform_slug = query(request, "platform")
    if platform_slug:
        stmt = stmt.where(AuditLog.platform_slug == platform_slug)
    since_days = query(request, "days")
    if since_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(since_days))
        stmt = stmt.where(AuditLog.created_at >= cutoff)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)).all()

    return {
        "user": user_public(user),
        "entries": [_audit_row(entry) for entry in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@bp.get("/users/{user_id}/logins")
@require_superadmin
def user_logins(request, db, ctx):
    """Sign-in history: when, from where, on what, and whether it succeeded.

    Failures are included deliberately — a run of them from an address the user
    does not recognise is the whole reason to look at this screen.
    """
    user = _user_or_404(db, request.params.get("user_id"))
    limit, offset = _page(request)

    actions = [
        audit.LOGIN_SUCCESS,
        audit.LOGIN_FAILED,
        audit.LOGIN_THROTTLED,
        audit.LOGOUT,
    ]
    stmt = select(AuditLog).where(
        AuditLog.actor_user_id == user.id, AuditLog.action.in_(actions)
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)).all()

    return {
        "logins": [
            {
                **_audit_row(entry),
                "outcome": "success" if entry.action == audit.LOGIN_SUCCESS
                else "logout" if entry.action == audit.LOGOUT
                else "failed",
            }
            for entry in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# --------------------------------------------------------------------------- #
#  Devices
# --------------------------------------------------------------------------- #
@bp.get("/users/{user_id}/sessions")
@require_superadmin
def user_sessions(request, db, ctx):
    """Every device currently holding a live SSO session."""
    user = _user_or_404(db, request.params.get("user_id"))
    return {
        "sessions": [session_public(row) for row in sessions.list_for_user(db, user.id)],
        "token_version": user.token_version,
    }


@bp.delete("/users/{user_id}/sessions/{session_id}")
@require_superadmin
def end_user_session(request, db, ctx):
    """Sign one device out.

    Ends the SSO session and revokes the refresh tokens that came from it, but
    leaves the user's other devices alone — the point of this endpoint over
    "revoke everything" is that a lost laptop should not log the owner out of
    their desk mid-session.
    """
    user = _user_or_404(db, request.params.get("user_id"))
    target_id = request.params.get("session_id")

    for row in sessions.list_for_user(db, user.id):
        if str(row.id) == target_id:
            sessions.revoke(db, row)
            now = datetime.now(timezone.utc)
            db.execute(
                RefreshToken.__table__.update()
                .where(RefreshToken.session_id == row.id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            audit.record(db, audit.SESSIONS_REVOKED, actor_user_id=ctx.user.id,
                         target_type="session", target_id=row.id, ip=ctx.ip, agent=ctx.agent,
                         subject_user=str(user.id), device=row.user_agent)
            return {"ok": True, "ended": str(row.id)}

    raise not_found("That session is not active.")


@bp.post("/users/{user_id}/revoke")
@require_superadmin
def revoke_everything(request, db, ctx):
    """Cut this account off everywhere, immediately.

    Ends every session, withdraws every refresh token, and publishes a
    revocation so the platforms stop honouring the access tokens already in the
    user's browser — without waiting for them to expire.
    """
    user = _user_or_404(db, request.params.get("user_id"))
    if user.id == ctx.user.id:
        raise forbidden("Use sign out rather than revoking your own access.")

    data = body_json(request) if request.is_json() else {}
    reason = (data.get("reason") or "manual_revocation")[:80]

    ended = sessions.revoke_all_for_user(db, user.id)
    revocation.publish(db, user, platform_slug=None, reason=reason)

    audit.record(db, audit.SESSIONS_REVOKED, actor_user_id=ctx.user.id, target_type="user",
                 target_id=user.id, ip=ctx.ip, agent=ctx.agent, sessions_ended=ended,
                 reason=reason, scope="all_platforms")
    return {
        "ok": True,
        "sessions_ended": ended,
        "token_version": user.token_version,
        "note": "Platforms polling /api/v1/revocations stop accepting the old tokens within seconds.",
    }


@bp.post("/users/{user_id}/platforms/{slug}/revoke")
@require_superadmin
def revoke_platform_access(request, db, ctx):
    """Take one platform away without touching the others.

    Deactivates the membership so /oauth/authorize refuses that platform from
    now on, and publishes a platform-scoped revocation so the token the user is
    holding for it stops working straight away.
    """
    user = _user_or_404(db, request.params.get("user_id"))
    slug = request.params.get("slug")
    platform = db.scalar(select(Platform).where(Platform.slug == slug))
    if platform is None:
        raise not_found(f"Unknown platform '{slug}'.")

    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id, Membership.platform_id == platform.id
        )
    )
    if membership is not None:
        membership.active = False

    revocation.publish(db, user, platform_slug=slug, reason="platform_access_revoked")

    audit.record(db, audit.MEMBERSHIP_REVOKED, actor_user_id=ctx.user.id, target_type="user",
                 target_id=user.id, platform_slug=slug, ip=ctx.ip, agent=ctx.agent,
                 revoked_tokens=True)
    return {"ok": True, "platform": slug, "membership_active": False}


@bp.post("/users/{user_id}/platforms/{slug}/grant")
@require_superadmin
def grant_platform_access(request, db, ctx):
    """Give this account a platform, at a named role, with an optional plan."""
    user = _user_or_404(db, request.params.get("user_id"))
    slug = request.params.get("slug")
    platform = db.scalar(select(Platform).where(Platform.slug == slug))
    if platform is None:
        raise not_found(f"Unknown platform '{slug}'.")

    data = body_json(request)
    role_code = (data.get("role") or "user").strip()
    role = provisioning.role_for(db, platform, role_code)
    if role is None:
        raise bad_request(f"Unknown role '{role_code}' for {platform.name}.")

    membership = provisioning.grant_membership(db, user, platform, role)

    plan_code = data.get("plan")
    from app.models import Plan

    plan = None
    if plan_code:
        plan = db.scalar(select(Plan).where(Plan.platform_id == platform.id, Plan.code == plan_code))
        if plan is None:
            raise bad_request(f"Unknown plan '{plan_code}' on {platform.name}.")
    else:
        plan = db.scalar(
            select(Plan).where(
                Plan.platform_id == platform.id, Plan.is_default.is_(True), Plan.active.is_(True)
            )
        )
    if plan is not None:
        provisioning.assign_subscription(db, user, platform, plan)

    audit.record(db, audit.MEMBERSHIP_GRANTED, actor_user_id=ctx.user.id, target_type="user",
                 target_id=user.id, platform_slug=slug, ip=ctx.ip, agent=ctx.agent,
                 role=role.code, plan=plan.code if plan else None)
    return {"ok": True, "membership": membership_public(membership)}


# --------------------------------------------------------------------------- #
#  Deletion
# --------------------------------------------------------------------------- #
@bp.delete("/users/{user_id}")
@require_superadmin
def delete_user(request, db, ctx):
    """Delete an account permanently.

    Guarded three ways, because this is the one action with no undo: you cannot
    delete yourself, you cannot delete the last remaining superadmin, and the
    request must name the account's own email as confirmation. The email check
    is not ceremony — it is what stops a mis-aimed click on a list row from
    deleting the wrong person.

    Audit entries survive: ``actor_user_id`` is ON DELETE SET NULL, so the record
    of what happened outlives the account it happened to.
    """
    user = _user_or_404(db, request.params.get("user_id"))

    if user.id == ctx.user.id:
        raise forbidden("You cannot delete your own account.")

    if user.is_superadmin:
        remaining = db.scalar(
            select(func.count()).select_from(User).where(
                User.is_superadmin.is_(True), User.id != user.id
            )
        )
        if not remaining:
            raise forbidden("This is the last superadmin — promote someone else first.")

    data = body_json(request) if request.is_json() else {}
    confirm = (data.get("confirm_email") or query(request, "confirm_email") or "").strip().lower()
    if confirm != user.email:
        raise bad_request(
            "Confirm the deletion by supplying the account's email address.",
            code="confirmation_required",
            expected=user.email,
        )

    email, user_id, org_id = user.email, user.id, user.org_id

    # Cut access first. If the delete were to fail partway, the account is
    # already locked out rather than left half-removed and still usable.
    sessions.revoke_all_for_user(db, user_id)
    revocation.publish(db, user, platform_slug=None, reason="account_deleted")

    db.delete(user)
    db.flush()

    # An organization that existed only to hold this user is now an empty shell.
    remaining_members = db.scalar(
        select(func.count()).select_from(User).where(User.org_id == org_id)
    )
    if not remaining_members:
        org = db.get(Organization, org_id)
        if org is not None:
            db.delete(org)

    audit.record(db, audit.USER_DELETED, actor_user_id=ctx.user.id, target_type="user",
                 target_id=user_id, ip=ctx.ip, agent=ctx.agent, email=email)
    return {"ok": True, "deleted": email}


# --------------------------------------------------------------------------- #
#  Estate-wide view
# --------------------------------------------------------------------------- #
@bp.get("/overview")
@require_superadmin
def estate_overview(request, db, ctx):
    """Headline numbers for the whole estate."""
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    total_users = db.scalar(select(func.count()).select_from(User)) or 0
    suspended = db.scalar(
        select(func.count()).select_from(User).where(User.status == UserStatus.SUSPENDED)
    ) or 0
    live_sessions = db.scalar(
        select(func.count()).select_from(SsoSession).where(
            SsoSession.revoked_at.is_(None), SsoSession.expires_at > now
        )
    ) or 0
    logins_24h = db.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == audit.LOGIN_SUCCESS, AuditLog.created_at >= day_ago
        )
    ) or 0
    failures_24h = db.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == audit.LOGIN_FAILED, AuditLog.created_at >= day_ago
        )
    ) or 0

    per_platform = []
    for platform in db.scalars(select(Platform).order_by(Platform.sort_order)):
        members = db.scalar(
            select(func.count()).select_from(Membership).where(
                Membership.platform_id == platform.id, Membership.active.is_(True)
            )
        ) or 0
        paying = db.scalar(
            select(func.count()).select_from(Subscription).where(
                Subscription.platform_id == platform.id,
                Subscription.status.in_(["active", "trialing"]),
            )
        ) or 0
        per_platform.append(
            {**platform_public(platform), "member_count": members, "subscription_count": paying}
        )

    return {
        "users": {"total": total_users, "suspended": suspended},
        "sessions": {"live": live_sessions},
        "logins_24h": {"success": logins_24h, "failed": failures_24h},
        "platforms": per_platform,
        "revocations_live": len(revocation.current(db)),
    }


# --------------------------------------------------------------------------- #
#  Revocation list (consumed by the platforms)
# --------------------------------------------------------------------------- #
public_bp = Blueprint("/api/v1")


@public_bp.get("/revocations")
def revocation_list(request):
    """The live revocation list, polled by every platform.

    Deliberately low-value to an attacker: opaque user ids and a version number,
    with no email, name or role. It has to be readable without a credential
    because a platform whose credential expired would otherwise silently stop
    enforcing revocations — failing open on exactly the wrong thing.
    """
    from cello import Response

    from app.core.http import jsonable
    from app.db import session_scope

    with session_scope() as db:
        entries = revocation.current(db)

    response = Response.json(
        jsonable(
            {
                "revocations": entries,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                # Tells a client how stale its cache may be, so the poll interval
                # is the server's decision rather than each platform's guess.
                "poll_after_seconds": 30,
            }
        )
    )
    response.set_header("Cache-Control", "no-store")
    return response
