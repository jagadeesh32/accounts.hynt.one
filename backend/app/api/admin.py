"""Administration.

Two tiers of authority, deliberately distinct:

* ``@require_superadmin`` — the identity provider itself: accounts, platforms,
  signing keys, the global audit trail.
* ``@require_platform_admin`` — one platform's own users, roles and plans. The
  terminal's administrator manages the terminal and cannot see intelligence's
  user list.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from cello import Blueprint
from sqlalchemy import func, or_, select

from app.core import audit, sessions
from app.core.authz import require_platform_admin, require_superadmin
from app.core.http import bad_request, body_json, conflict, field, forbidden, not_found, query
from app.core.security import new_secret, token_digest
from app.models import (
    AuditLog,
    Membership,
    Organization,
    PasswordReset,
    Plan,
    Platform,
    Role,
    Subscription,
    SubscriptionStatus,
    User,
    UserStatus,
)
from app.schemas.serializers import (
    membership_public,
    plan_public,
    platform_public,
    role_public,
    user_public,
)
from app.services import provisioning

bp = Blueprint("/api/v1/admin")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _page(request) -> tuple[int, int]:
    limit = min(max(int(query(request, "limit", "50") or 50), 1), 200)
    offset = max(int(query(request, "offset", "0") or 0), 0)
    return limit, offset


# --------------------------------------------------------------------------- #
#  Users (superadmin)
# --------------------------------------------------------------------------- #
@bp.get("/users")
@require_superadmin
def list_users(request, db, ctx):
    limit, offset = _page(request)
    search = (query(request, "q") or "").strip().lower()

    stmt = select(User)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(or_(User.email.ilike(pattern), User.full_name.ilike(pattern)))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)).all()

    return {
        "users": [user_public(u) for u in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@bp.post("/users")
@require_superadmin
def create_user(request, db, ctx):
    """Provision an account.

    With no password the account is created PENDING and a one-time activation
    token is returned — the invitation flow, reusing the password-reset machinery
    rather than inventing a second single-use token type.
    """
    data = body_json(request)
    email = field(data, "email").strip().lower()
    if not _EMAIL_RE.match(email):
        raise bad_request("Enter a valid email address.")
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise conflict("An account with that email already exists.", code="email_taken")

    password = data.get("password") or None
    user = provisioning.create_user_account(
        db,
        email=email,
        password=password,
        full_name=(data.get("full_name") or "").strip(),
        is_superadmin=bool(data.get("is_superadmin")),
        grant_defaults=bool(data.get("grant_defaults", True)),
    )

    payload = {"user": user_public(user)}
    if password is None:
        raw = new_secret(32)
        now = datetime.now(timezone.utc)
        from datetime import timedelta

        from app import config

        db.add(
            PasswordReset(
                user_id=user.id,
                token_hash=token_digest(raw),
                expires_at=now + timedelta(seconds=max(config.PASSWORD_RESET_TTL_SEC, 7 * 86400)),
                created_at=now,
            )
        )
        payload["activation_token"] = raw

    audit.record(db, audit.USER_CREATED, actor_user_id=ctx.user.id, target_type="user",
                 target_id=user.id, ip=ctx.ip, agent=ctx.agent, email=email)
    from app.core.http import ok

    return ok(payload, status=201)


@bp.get("/users/{user_id}")
@require_superadmin
def get_user(request, db, ctx):
    user = db.get(User, request.params.get("user_id"))
    if user is None:
        raise not_found("No such user.")

    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    subs = db.scalars(select(Subscription).where(Subscription.user_id == user.id)).all()
    from app.schemas.serializers import subscription_public

    return {
        "user": user_public(user),
        "memberships": [membership_public(m) for m in memberships],
        "subscriptions": [subscription_public(s) for s in subs],
        "sessions": len(sessions.list_for_user(db, user.id)),
    }


@bp.patch("/users/{user_id}")
@require_superadmin
def update_user(request, db, ctx):
    """Edit an account.

    Suspending one ends every session and bumps ``token_version``, so access
    stops at the next request rather than whenever the current token happens to
    expire. Superadmins cannot demote or suspend themselves — locking the last
    administrator out of their own identity provider has no recovery path
    through the UI.
    """
    user = db.get(User, request.params.get("user_id"))
    if user is None:
        raise not_found("No such user.")
    data = body_json(request)
    changes: dict = {}

    if "full_name" in data:
        user.full_name = (data.get("full_name") or "").strip()[:160]
        changes["full_name"] = user.full_name

    if "email_verified" in data:
        user.email_verified = bool(data["email_verified"])
        changes["email_verified"] = user.email_verified

    if "is_superadmin" in data:
        wanted = bool(data["is_superadmin"])
        if user.id == ctx.user.id and not wanted:
            raise forbidden("You cannot remove your own superadmin role.")
        user.is_superadmin = wanted
        changes["is_superadmin"] = wanted

    if "status" in data:
        try:
            status = UserStatus(data["status"])
        except ValueError:
            raise bad_request(f"Unknown status '{data['status']}'.")
        if user.id == ctx.user.id and status != UserStatus.ACTIVE:
            raise forbidden("You cannot suspend your own account.")
        if status == UserStatus.SUSPENDED and user.status != UserStatus.SUSPENDED:
            sessions.revoke_all_for_user(db, user.id)
            user.token_version += 1
            audit.record(db, audit.USER_SUSPENDED, actor_user_id=ctx.user.id, target_type="user",
                         target_id=user.id, ip=ctx.ip, agent=ctx.agent)
        elif status == UserStatus.ACTIVE and user.status == UserStatus.SUSPENDED:
            audit.record(db, audit.USER_REINSTATED, actor_user_id=ctx.user.id, target_type="user",
                         target_id=user.id, ip=ctx.ip, agent=ctx.agent)
        user.status = status
        changes["status"] = status.value

    audit.record(db, audit.USER_UPDATED, actor_user_id=ctx.user.id, target_type="user",
                 target_id=user.id, ip=ctx.ip, agent=ctx.agent, **changes)
    return {"user": user_public(user)}


@bp.post("/users/{user_id}/revoke-sessions")
@require_superadmin
def force_signout(request, db, ctx):
    """Sign a user out everywhere, immediately."""
    user = db.get(User, request.params.get("user_id"))
    if user is None:
        raise not_found("No such user.")
    count = sessions.revoke_all_for_user(db, user.id)
    user.token_version += 1
    audit.record(db, audit.SESSIONS_REVOKED, actor_user_id=ctx.user.id, target_type="user",
                 target_id=user.id, ip=ctx.ip, agent=ctx.agent, count=count)
    return {"ok": True, "sessions_revoked": count}


# --------------------------------------------------------------------------- #
#  Platforms & roles (superadmin)
# --------------------------------------------------------------------------- #
@bp.get("/platforms")
@require_superadmin
def admin_platforms(request, db, ctx):
    rows = db.scalars(select(Platform).order_by(Platform.sort_order)).all()
    out = []
    for platform in rows:
        roles = db.scalars(
            select(Role).where(Role.platform_id == platform.id).order_by(Role.rank.desc())
        ).all()
        members = db.scalar(
            select(func.count()).select_from(Membership).where(
                Membership.platform_id == platform.id, Membership.active.is_(True)
            )
        )
        out.append(
            {
                **platform_public(platform),
                "roles": [role_public(r) for r in roles],
                "member_count": members or 0,
            }
        )
    return {"platforms": out}


@bp.post("/platforms")
@require_superadmin
def create_platform(request, db, ctx):
    """Register a fourth platform.

    Creating one also creates its admin/staff/user roles, so onboarding a new
    product is one call and not a hand-written set of INSERTs.
    """
    data = body_json(request)
    slug = field(data, "slug").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", slug):
        raise bad_request("Slug must be lowercase letters, digits and hyphens.")
    if db.scalar(select(Platform).where(Platform.slug == slug)) is not None:
        raise conflict(f"Platform '{slug}' already exists.")

    platform = Platform(
        slug=slug,
        name=field(data, "name").strip(),
        description=(data.get("description") or "").strip(),
        base_url=(data.get("base_url") or "").strip(),
        icon=(data.get("icon") or "").strip(),
        sort_order=int(data.get("sort_order") or 0),
    )
    db.add(platform)
    db.flush()

    for spec in provisioning.default_roles_for_platform(platform.id):
        db.add(Role(platform_id=platform.id, **spec))
    db.flush()

    audit.record(db, audit.PLATFORM_CREATED, actor_user_id=ctx.user.id, target_type="platform",
                 target_id=platform.id, platform_slug=slug, ip=ctx.ip, agent=ctx.agent)
    from app.core.http import ok

    return ok({"platform": platform_public(platform)}, status=201)


@bp.patch("/platforms/{slug}")
@require_platform_admin
def update_platform(request, db, ctx, platform):
    data = body_json(request)
    for attr in ("name", "description", "base_url", "icon"):
        if attr in data:
            setattr(platform, attr, (data.get(attr) or "").strip())
    if "active" in data:
        if not ctx.user.is_superadmin:
            raise forbidden("Only a superadmin can enable or disable a platform.")
        platform.active = bool(data["active"])
    if "sort_order" in data:
        platform.sort_order = int(data["sort_order"] or 0)

    audit.record(db, audit.PLATFORM_UPDATED, actor_user_id=ctx.user.id, target_type="platform",
                 target_id=platform.id, platform_slug=platform.slug, ip=ctx.ip, agent=ctx.agent)
    return {"platform": platform_public(platform)}


# --------------------------------------------------------------------------- #
#  Memberships (platform admin)
# --------------------------------------------------------------------------- #
@bp.get("/platforms/{slug}/members")
@require_platform_admin
def list_members(request, db, ctx, platform):
    limit, offset = _page(request)
    rows = db.scalars(
        select(Membership)
        .where(Membership.platform_id == platform.id)
        .order_by(Membership.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    subs = {
        s.user_id: s
        for s in db.scalars(select(Subscription).where(Subscription.platform_id == platform.id))
    }
    from app.schemas.serializers import subscription_public

    members = []
    for m in rows:
        user = db.get(User, m.user_id)
        sub = subs.get(m.user_id)
        members.append(
            {
                "membership": membership_public(m),
                "user": user_public(user) if user else None,
                "subscription": subscription_public(sub) if sub else None,
            }
        )
    total = db.scalar(
        select(func.count()).select_from(Membership).where(Membership.platform_id == platform.id)
    )
    return {"members": members, "total": total or 0, "limit": limit, "offset": offset}


@bp.post("/platforms/{slug}/members")
@require_platform_admin
def add_member(request, db, ctx, platform):
    """Grant a user access to this platform with a named role."""
    data = body_json(request)
    email = field(data, "email").strip().lower()
    role_code = (data.get("role") or "user").strip()

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        raise not_found(f"No account with the email {email}.")

    role = provisioning.role_for(db, platform, role_code)
    if role is None:
        raise bad_request(f"Unknown role '{role_code}' for {platform.name}.")
    _guard_role_escalation(db, ctx, platform, role)

    membership = provisioning.grant_membership(db, user, platform, role)

    # A member with no plan on a platform that has a default plan would be a
    # member who cannot use anything, so attach it here too.
    default_plan = db.scalar(
        select(Plan).where(
            Plan.platform_id == platform.id, Plan.is_default.is_(True), Plan.active.is_(True)
        )
    )
    if default_plan is not None:
        provisioning.assign_subscription(db, user, platform, default_plan)

    audit.record(db, audit.MEMBERSHIP_GRANTED, actor_user_id=ctx.user.id, target_type="user",
                 target_id=user.id, platform_slug=platform.slug, ip=ctx.ip, agent=ctx.agent,
                 role=role.code)
    from app.core.http import ok

    return ok({"membership": membership_public(membership)}, status=201)


@bp.patch("/platforms/{slug}/members/{user_id}")
@require_platform_admin
def update_member(request, db, ctx, platform):
    """Change a member's role, activation or extra permissions."""
    user_id = request.params.get("user_id")
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id, Membership.platform_id == platform.id
        )
    )
    if membership is None:
        raise not_found("That user is not a member of this platform.")

    data = body_json(request)

    if "role" in data:
        role = provisioning.role_for(db, platform, str(data["role"]))
        if role is None:
            raise bad_request(f"Unknown role '{data['role']}' for {platform.name}.")
        _guard_role_escalation(db, ctx, platform, role)
        membership.role_id = role.id
        audit.record(db, audit.MEMBERSHIP_ROLE_CHANGED, actor_user_id=ctx.user.id,
                     target_type="user", target_id=user_id, platform_slug=platform.slug,
                     ip=ctx.ip, agent=ctx.agent, role=role.code)

    if "active" in data:
        membership.active = bool(data["active"])

    if "extra_permissions" in data:
        perms = data["extra_permissions"]
        if not isinstance(perms, list) or not all(isinstance(p, str) for p in perms):
            raise bad_request("extra_permissions must be a list of permission codes.")
        membership.extra_permissions = perms

    return {"membership": membership_public(membership)}


@bp.delete("/platforms/{slug}/members/{user_id}")
@require_platform_admin
def remove_member(request, db, ctx, platform):
    user_id = request.params.get("user_id")
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id, Membership.platform_id == platform.id
        )
    )
    if membership is None:
        raise not_found("That user is not a member of this platform.")

    db.delete(membership)
    audit.record(db, audit.MEMBERSHIP_REVOKED, actor_user_id=ctx.user.id, target_type="user",
                 target_id=user_id, platform_slug=platform.slug, ip=ctx.ip, agent=ctx.agent)
    return {"ok": True}


def _guard_role_escalation(db, ctx, platform, role: Role) -> None:
    """A platform admin may not mint a role above their own.

    Without this, "admin of terminal" is really "superadmin, eventually", since
    they could grant themselves anything the role table can express.
    """
    if ctx.user.is_superadmin:
        return
    own = db.scalar(
        select(Membership).where(
            Membership.user_id == ctx.user.id,
            Membership.platform_id == platform.id,
            Membership.active.is_(True),
        )
    )
    if own is None or role.rank > own.role.rank:
        raise forbidden("You cannot grant a role above your own.")


# --------------------------------------------------------------------------- #
#  Plans & subscriptions (platform admin)
# --------------------------------------------------------------------------- #
@bp.get("/platforms/{slug}/plans")
@require_platform_admin
def admin_plans(request, db, ctx, platform):
    rows = db.scalars(
        select(Plan).where(Plan.platform_id == platform.id).order_by(Plan.sort_order)
    ).all()
    return {"plans": [plan_public(p) for p in rows]}


@bp.post("/platforms/{slug}/plans")
@require_platform_admin
def create_plan(request, db, ctx, platform):
    data = body_json(request)
    code = field(data, "code").strip().lower()
    if db.scalar(select(Plan).where(Plan.platform_id == platform.id, Plan.code == code)):
        raise conflict(f"Plan '{code}' already exists on {platform.name}.")

    plan = Plan(
        platform_id=platform.id,
        code=code,
        name=field(data, "name").strip(),
        description=(data.get("description") or "").strip(),
        price_cents=int(data.get("price_cents") or 0),
        currency=(data.get("currency") or "INR").upper()[:3],
        interval=data.get("interval") or "monthly",
        trial_days=int(data.get("trial_days") or 0),
        features=data.get("features") or [],
        limits=data.get("limits") or {},
        entitlements=data.get("entitlements") or [],
        is_default=bool(data.get("is_default")),
        active=bool(data.get("active", True)),
        sort_order=int(data.get("sort_order") or 0),
    )
    if plan.is_default:
        _clear_other_defaults(db, platform.id, None)
    db.add(plan)
    db.flush()

    audit.record(db, audit.PLAN_CREATED, actor_user_id=ctx.user.id, target_type="plan",
                 target_id=plan.id, platform_slug=platform.slug, ip=ctx.ip, agent=ctx.agent,
                 code=code)
    from app.core.http import ok

    return ok({"plan": plan_public(plan)}, status=201)


@bp.patch("/platforms/{slug}/plans/{plan_id}")
@require_platform_admin
def update_plan(request, db, ctx, platform):
    plan = db.scalar(
        select(Plan).where(
            Plan.id == request.params.get("plan_id"), Plan.platform_id == platform.id
        )
    )
    if plan is None:
        raise not_found("No such plan on this platform.")

    data = body_json(request)
    for attr in ("name", "description"):
        if attr in data:
            setattr(plan, attr, (data.get(attr) or "").strip())
    for attr in ("price_cents", "trial_days", "sort_order"):
        if attr in data:
            setattr(plan, attr, int(data.get(attr) or 0))
    for attr in ("features", "entitlements"):
        if attr in data:
            if not isinstance(data[attr], list):
                raise bad_request(f"{attr} must be a list.")
            setattr(plan, attr, data[attr])
    if "limits" in data:
        if not isinstance(data["limits"], dict):
            raise bad_request("limits must be an object.")
        plan.limits = data["limits"]
    if "currency" in data:
        plan.currency = str(data["currency"]).upper()[:3]
    if "interval" in data:
        plan.interval = data["interval"]
    if "active" in data:
        plan.active = bool(data["active"])
    if data.get("is_default"):
        _clear_other_defaults(db, platform.id, plan.id)
        plan.is_default = True

    audit.record(db, audit.PLAN_UPDATED, actor_user_id=ctx.user.id, target_type="plan",
                 target_id=plan.id, platform_slug=platform.slug, ip=ctx.ip, agent=ctx.agent)
    return {"plan": plan_public(plan)}


def _clear_other_defaults(db, platform_id, keep_id) -> None:
    """Exactly one default plan per platform; two would make which one a new
    signup lands on depend on row order."""
    stmt = select(Plan).where(Plan.platform_id == platform_id, Plan.is_default.is_(True))
    for existing in db.scalars(stmt):
        if keep_id is None or existing.id != keep_id:
            existing.is_default = False


@bp.put("/platforms/{slug}/members/{user_id}/subscription")
@require_platform_admin
def set_subscription(request, db, ctx, platform):
    """Move a member onto a plan, or change their subscription status."""
    user_id = request.params.get("user_id")
    user = db.get(User, user_id)
    if user is None:
        raise not_found("No such user.")

    data = body_json(request)
    plan_code = field(data, "plan").strip().lower()
    plan = db.scalar(select(Plan).where(Plan.platform_id == platform.id, Plan.code == plan_code))
    if plan is None:
        raise bad_request(f"Unknown plan '{plan_code}' on {platform.name}.")

    status = None
    if "status" in data:
        try:
            status = SubscriptionStatus(data["status"])
        except ValueError:
            raise bad_request(f"Unknown subscription status '{data['status']}'.")

    sub = provisioning.assign_subscription(db, user, platform, plan, status=status)
    audit.record(db, audit.SUBSCRIPTION_CHANGED, actor_user_id=ctx.user.id, target_type="user",
                 target_id=user.id, platform_slug=platform.slug, ip=ctx.ip, agent=ctx.agent,
                 plan=plan.code, status=sub.status.value)
    from app.schemas.serializers import subscription_public

    return {"subscription": subscription_public(sub)}


# --------------------------------------------------------------------------- #
#  Audit & keys (superadmin)
# --------------------------------------------------------------------------- #
@bp.get("/audit")
@require_superadmin
def audit_log(request, db, ctx):
    limit, offset = _page(request)
    stmt = select(AuditLog)

    action = query(request, "action")
    if action:
        stmt = stmt.where(AuditLog.action == action)
    platform_slug = query(request, "platform")
    if platform_slug:
        stmt = stmt.where(AuditLog.platform_slug == platform_slug)
    actor = query(request, "actor")
    if actor:
        stmt = stmt.where(AuditLog.actor_user_id == actor)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)).all()

    from app.core.http import jsonable

    return {
        "entries": [
            jsonable(
                {
                    "id": r.id,
                    "action": r.action,
                    "actor_user_id": r.actor_user_id,
                    "target_type": r.target_type,
                    "target_id": r.target_id,
                    "platform_slug": r.platform_slug,
                    "ip_address": r.ip_address,
                    "meta": r.meta,
                    "created_at": r.created_at,
                }
            )
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@bp.post("/signing-keys/rotate")
@require_superadmin
def rotate_signing_key(request, db, ctx):
    """Mint a new signing key.

    The previous public key stays in the JWKS so tokens already issued keep
    verifying until they expire; only new tokens use the new key.
    """
    from app.core import keys

    key = keys.rotate(db)
    audit.record(db, audit.KEY_ROTATED, actor_user_id=ctx.user.id, target_type="signing_key",
                 target_id=key.kid, ip=ctx.ip, agent=ctx.agent)
    return {"kid": key.kid, "alg": key.alg}
