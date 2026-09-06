"""The per-platform admin console.

Everything here is scoped to one platform and gated on the caller's rank on
*that* platform. A Terminal admin cannot see X-Terminal's members.
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import GrantIn, PlanIn, SubscriptionIn
from app.core import audit
from app.core.authz import (
    Actor,
    actor_rank_on,
    assert_may_grant,
    current_actor,
    membership_for,
    require_platform_rank,
)
from app.core.http import parse_uuid
from app.core.security import hash_password
from app.core.sessions import revoke_all_sessions
from app.db import get_db
from app.models.billing import Plan, Subscription
from app.models.identity import User
from app.models.rbac import Membership, Platform, Role
from app.services import provisioning, revocation

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

STAFF_RANK = 20
ADMIN_RANK = 30


async def _platform(db: AsyncSession, slug: str) -> Platform:
    platform = (await db.execute(select(Platform).where(Platform.slug == slug))).scalars().first()
    if platform is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such platform")
    return platform


async def _user_by_email(db: AsyncSession, email: str) -> User:
    user = (
        await db.execute(select(User).where(User.email == email.strip().lower()))
    ).scalars().first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user")
    return user


@router.get("/platforms")
async def my_admin_platforms(actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    """The platforms this console should offer the caller — the ones they hold
    staff or better on."""
    platforms = (await db.execute(select(Platform).order_by(Platform.slug))).scalars().all()
    out = []
    for platform in platforms:
        rank = await actor_rank_on(db, actor, platform.id)
        if rank >= STAFF_RANK:
            out.append({"slug": platform.slug, "name": platform.name, "your_rank": rank})
    return {"platforms": out}


@router.get("/{slug}/members")
async def members(
    slug: str,
    q: str = "",
    limit: int = 100,
    offset: int = 0,
    actor: Actor = Depends(current_actor),
    db: AsyncSession = Depends(get_db),
):
    platform = await _platform(db, slug)
    await require_platform_rank(db, actor, platform.id, STAFF_RANK)

    stmt = (
        select(Membership, User, Role)
        .join(User, User.id == Membership.user_id)
        .join(Role, Role.id == Membership.role_id)
        .where(Membership.platform_id == platform.id)
    )
    if q:
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(func.lower(User.email).like(needle) | func.lower(func.coalesce(User.full_name, "")).like(needle))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(Role.rank.desc(), User.email).limit(min(limit, 500)).offset(offset))).all()

    subs = {
        s.user_id: s
        for s in (
            await db.execute(select(Subscription).where(Subscription.platform_id == platform.id))
        ).scalars()
    }
    plans = {p.id: p for p in (await db.execute(select(Plan).where(Plan.platform_id == platform.id))).scalars()}

    out = []
    for membership, user, role in rows:
        sub = subs.get(user.id)
        plan = plans.get(sub.plan_id) if sub else None
        out.append(
            {
                "user_id": str(user.id),
                "email": user.email,
                "full_name": user.full_name or "",
                "status": user.status,
                "role": role.slug,
                "rank": role.rank,
                "membership_status": membership.status,
                "plan": plan.slug if plan else None,
                "plan_status": sub.status if sub else None,
                "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            }
        )
    return {"total": total, "members": out}


@router.get("/{slug}/roles")
async def roles(slug: str, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    platform = await _platform(db, slug)
    rank = await require_platform_rank(db, actor, platform.id, STAFF_RANK)
    rows = (
        await db.execute(select(Role).where(Role.platform_id == platform.id).order_by(Role.rank.desc()))
    ).scalars().all()
    return {
        "your_rank": rank,
        "roles": [
            {
                "slug": r.slug,
                "name": r.name,
                "rank": r.rank,
                "permissions": r.permissions,
                # The UI greys out what this caller may not hand out, rather
                # than offering it and failing the request.
                "grantable": r.rank < rank or rank >= 40,
            }
            for r in rows
        ],
    }


@router.post("/{slug}/members")
async def add_member(
    slug: str,
    body: GrantIn,
    request: Request,
    actor: Actor = Depends(current_actor),
    db: AsyncSession = Depends(get_db),
):
    platform = await _platform(db, slug)
    rank = await require_platform_rank(db, actor, platform.id, ADMIN_RANK)

    role = await provisioning.role_for(db, platform.id, body.role)
    if role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No such role on this platform")
    assert_may_grant(rank, role.rank)

    user = await _user_by_email(db, body.email)
    await provisioning.grant(db, user_id=user.id, platform=platform, role_slug=body.role, plan_slug=body.plan)
    await audit.record(
        db, action="member.granted", actor_user_id=actor.user.id,
        target=f"{user.email}@{platform.slug}", meta={"role": body.role, "plan": body.plan}, request=request,
    )
    return {"ok": True}


@router.patch("/{slug}/members/{user_id}/role")
async def change_role(
    slug: str,
    user_id: str,
    payload: dict,
    request: Request,
    actor: Actor = Depends(current_actor),
    db: AsyncSession = Depends(get_db),
):
    platform = await _platform(db, slug)
    rank = await require_platform_rank(db, actor, platform.id, ADMIN_RANK)

    target = await db.get(User, parse_uuid(user_id, "user"))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user")

    membership = await membership_for(db, target.id, platform.id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a member of this platform")

    current_role = await db.get(Role, membership.role_id)
    # You may not edit a peer or a superior — otherwise two admins could demote
    # each other, and the last one to click wins.
    if current_role and current_role.rank >= rank and rank < 40:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot change a member at or above your own rank")

    new_role = await provisioning.role_for(db, platform.id, str(payload.get("role", "")))
    if new_role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No such role on this platform")
    assert_may_grant(rank, new_role.rank)

    membership.role_id = new_role.id
    await db.commit()
    # The role is inside live access tokens; publish so it takes effect now.
    await revocation.revoke_user(db, target.id, reason="role changed")
    await audit.record(
        db, action="member.role_changed", actor_user_id=actor.user.id,
        target=f"{target.email}@{platform.slug}", meta={"role": new_role.slug}, request=request,
    )
    return {"ok": True}


@router.delete("/{slug}/members/{user_id}")
async def remove_member(
    slug: str,
    user_id: str,
    request: Request,
    actor: Actor = Depends(current_actor),
    db: AsyncSession = Depends(get_db),
):
    platform = await _platform(db, slug)
    rank = await require_platform_rank(db, actor, platform.id, ADMIN_RANK)

    target = await db.get(User, parse_uuid(user_id, "user"))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user")

    membership = await membership_for(db, target.id, platform.id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a member of this platform")
    role = await db.get(Role, membership.role_id)
    if role and role.rank >= rank and rank < 40:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot remove a member at or above your own rank")

    await provisioning.revoke_membership(db, user_id=target.id, platform_id=platform.id)
    await revocation.revoke_user(db, target.id, reason="membership removed")
    await audit.record(
        db, action="member.removed", actor_user_id=actor.user.id,
        target=f"{target.email}@{platform.slug}", request=request,
    )
    return {"ok": True}


@router.get("/{slug}/plans")
async def list_plans(slug: str, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    platform = await _platform(db, slug)
    await require_platform_rank(db, actor, platform.id, STAFF_RANK)
    rows = (
        await db.execute(select(Plan).where(Plan.platform_id == platform.id).order_by(Plan.sort_order, Plan.price_inr))
    ).scalars().all()
    return {
        "plans": [
            {
                "slug": p.slug, "name": p.name, "price_inr": p.price_inr, "interval": p.interval,
                "entitlements": p.entitlements, "limits": p.limits, "is_default": p.is_default,
            }
            for p in rows
        ]
    }


@router.put("/{slug}/plans/{plan_slug}")
async def upsert_plan(
    slug: str,
    plan_slug: str,
    body: PlanIn,
    request: Request,
    actor: Actor = Depends(current_actor),
    db: AsyncSession = Depends(get_db),
):
    platform = await _platform(db, slug)
    await require_platform_rank(db, actor, platform.id, ADMIN_RANK)

    plan = (
        await db.execute(select(Plan).where(Plan.platform_id == platform.id, Plan.slug == plan_slug))
    ).scalars().first()
    if plan is None:
        plan = Plan(platform_id=platform.id, slug=plan_slug)
        db.add(plan)

    plan.name = body.name
    plan.price_inr = body.price_inr
    plan.interval = body.interval
    plan.entitlements = body.entitlements
    plan.limits = body.limits

    if body.is_default:
        # Exactly one default per platform, or provisioning would pick arbitrarily.
        for other in (await db.execute(select(Plan).where(Plan.platform_id == platform.id))).scalars():
            other.is_default = other.slug == plan_slug
    await db.commit()
    await audit.record(db, action="plan.saved", actor_user_id=actor.user.id, target=f"{plan_slug}@{slug}", request=request)
    return {"ok": True}


@router.post("/{slug}/subscriptions")
async def set_subscription(
    slug: str,
    body: SubscriptionIn,
    request: Request,
    actor: Actor = Depends(current_actor),
    db: AsyncSession = Depends(get_db),
):
    platform = await _platform(db, slug)
    await require_platform_rank(db, actor, platform.id, ADMIN_RANK)

    user = await _user_by_email(db, body.email)
    plan = (
        await db.execute(select(Plan).where(Plan.platform_id == platform.id, Plan.slug == body.plan))
    ).scalars().first()
    if plan is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No such plan on this platform")

    sub = (
        await db.execute(
            select(Subscription).where(
                Subscription.user_id == user.id, Subscription.platform_id == platform.id
            )
        )
    ).scalars().first()
    if sub is None:
        sub = Subscription(user_id=user.id, platform_id=platform.id, plan_id=plan.id)
        db.add(sub)
    sub.plan_id = plan.id
    sub.status = body.status
    await db.commit()

    # Entitlements ride inside the token; a downgrade has to bite immediately.
    await revocation.revoke_user(db, user.id, reason="subscription changed")
    await audit.record(
        db, action="subscription.set", actor_user_id=actor.user.id,
        target=f"{user.email}@{platform.slug}", meta={"plan": body.plan, "status": body.status}, request=request,
    )
    return {"ok": True}


@router.post("/{slug}/invite")
async def invite(
    slug: str,
    body: GrantIn,
    request: Request,
    actor: Actor = Depends(current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Create the account if it does not exist, then grant. Returns a temporary
    password — there is no mail transport on this box, so the admin passes it
    on out of band and the user changes it on first sign-in."""
    platform = await _platform(db, slug)
    rank = await require_platform_rank(db, actor, platform.id, ADMIN_RANK)

    role = await provisioning.role_for(db, platform.id, body.role)
    if role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No such role on this platform")
    assert_may_grant(rank, role.rank)

    email = body.email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalars().first()
    temp_password = None
    if user is None:
        temp_password = secrets.token_urlsafe(12)
        user = User(email=email, password_hash=hash_password(temp_password), status="active")
        db.add(user)
        await db.commit()
        await db.refresh(user)

    await provisioning.grant(db, user_id=user.id, platform=platform, role_slug=body.role, plan_slug=body.plan)
    await audit.record(
        db, action="member.invited", actor_user_id=actor.user.id,
        target=f"{email}@{platform.slug}", meta={"role": body.role}, request=request,
    )
    return {"ok": True, "created": temp_password is not None, "temp_password": temp_password}
