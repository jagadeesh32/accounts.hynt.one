"""Who may do what, here in the identity provider itself.

Two separate questions live in this file:
  * what a *platform* should be told about a user (claims), and
  * what a user may do *in this console* (guards).
"""
import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.billing import Plan, Subscription
from app.models.identity import Session, User
from app.models.rbac import Membership, Platform, Role

SUPERADMIN_RANK = 40


class Actor:
    """The signed-in console user plus the session they are using."""

    def __init__(self, user: User, session: Session):
        self.user = user
        self.session = session

    @property
    def is_superadmin(self) -> bool:
        return self.user.is_superadmin


async def current_actor(request: Request, db: AsyncSession = Depends(get_db)) -> Actor:
    from app.core.sessions import resolve_session

    resolved = await resolve_session(db, request)
    if resolved is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    session, user = resolved
    return Actor(user, session)


async def require_superadmin(actor: Actor = Depends(current_actor)) -> Actor:
    if not actor.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Superadmin only")
    return actor


async def membership_for(db: AsyncSession, user_id: uuid.UUID, platform_id: uuid.UUID) -> Membership | None:
    return (
        await db.execute(
            select(Membership).where(
                Membership.user_id == user_id, Membership.platform_id == platform_id
            )
        )
    ).scalars().first()


async def actor_rank_on(db: AsyncSession, actor: Actor, platform_id: uuid.UUID) -> int:
    """A superadmin outranks every platform; everyone else is ranked by their
    membership on that specific platform."""
    if actor.is_superadmin:
        return SUPERADMIN_RANK
    membership = await membership_for(db, actor.user.id, platform_id)
    if membership is None or membership.status != "active":
        return 0
    role = await db.get(Role, membership.role_id)
    return role.rank if role else 0


async def require_platform_rank(db: AsyncSession, actor: Actor, platform_id: uuid.UUID, minimum: int) -> int:
    rank = await actor_rank_on(db, actor, platform_id)
    if rank < minimum:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient rank on this platform")
    return rank


def assert_may_grant(actor_rank: int, target_role_rank: int) -> None:
    """A platform admin may not grant a role at or above their own — otherwise
    "admin of Terminal" would really mean "superadmin, eventually"."""
    if target_role_rank >= actor_rank and actor_rank < SUPERADMIN_RANK:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You cannot grant a role at or above your own rank",
        )


async def platform_claims(db: AsyncSession, user: User, platform: Platform) -> dict | None:
    """Everything a platform needs to authorise, or None if the user has no
    membership there. Role gives permissions; the plan gives entitlements and
    limits; the platform gets the intersection and decides."""
    membership = await membership_for(db, user.id, platform.id)
    if membership is None or membership.status != "active":
        return None

    role = await db.get(Role, membership.role_id)
    if role is None:
        return None

    subscription = (
        await db.execute(
            select(Subscription).where(
                Subscription.user_id == user.id, Subscription.platform_id == platform.id
            )
        )
    ).scalars().first()

    plan: Plan | None = None
    if subscription is not None:
        plan = await db.get(Plan, subscription.plan_id)

    # A cancelled or past-due subscription keeps the row but grants nothing:
    # the platform sees plan_status and can degrade rather than lock out.
    entitled = subscription is not None and subscription.status == "active" and plan is not None

    return {
        "role": role.slug,
        "rank": role.rank,
        "permissions": list(role.permissions or []),
        "plan": plan.slug if plan else None,
        "plan_status": subscription.status if subscription else None,
        "entitlements": list(plan.entitlements or []) if entitled else [],
        "limits": dict(plan.limits or {}) if entitled else {},
    }
