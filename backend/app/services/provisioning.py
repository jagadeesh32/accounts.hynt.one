"""Giving a user access to a platform: one membership + one subscription."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import Plan, Subscription
from app.models.rbac import Membership, Platform, Role


async def role_for(db: AsyncSession, platform_id: uuid.UUID, slug: str) -> Role | None:
    return (
        await db.execute(
            select(Role).where(Role.platform_id == platform_id, Role.slug == slug)
        )
    ).scalars().first()


async def default_plan_for(db: AsyncSession, platform_id: uuid.UUID) -> Plan | None:
    return (
        await db.execute(
            select(Plan).where(Plan.platform_id == platform_id, Plan.is_default.is_(True))
        )
    ).scalars().first()


async def grant(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    platform: Platform,
    role_slug: str,
    plan_slug: str | None = None,
    commit: bool = True,
) -> Membership:
    """Idempotent: re-granting moves the existing membership to the new role
    rather than failing on the (user, platform) uniqueness constraint."""
    role = await role_for(db, platform.id, role_slug)
    if role is None:
        raise ValueError(f"No role '{role_slug}' on platform '{platform.slug}'")

    membership = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == user_id, Membership.platform_id == platform.id
            )
        )
    ).scalars().first()

    if membership is None:
        membership = Membership(user_id=user_id, platform_id=platform.id, role_id=role.id)
        db.add(membership)
    else:
        membership.role_id = role.id
        membership.status = "active"

    # Every member needs a plan, or the token would carry no entitlements at all
    # and the platform would see a member who can do nothing.
    plan = None
    if plan_slug:
        plan = (
            await db.execute(
                select(Plan).where(Plan.platform_id == platform.id, Plan.slug == plan_slug)
            )
        ).scalars().first()
        if plan is None:
            raise ValueError(f"No plan '{plan_slug}' on platform '{platform.slug}'")
    else:
        plan = await default_plan_for(db, platform.id)

    if plan is not None:
        subscription = (
            await db.execute(
                select(Subscription).where(
                    Subscription.user_id == user_id, Subscription.platform_id == platform.id
                )
            )
        ).scalars().first()
        if subscription is None:
            db.add(Subscription(user_id=user_id, platform_id=platform.id, plan_id=plan.id, status="active"))
        elif plan_slug:
            subscription.plan_id = plan.id
            subscription.status = "active"

    if commit:
        await db.commit()
        await db.refresh(membership)
    return membership


async def revoke_membership(db: AsyncSession, *, user_id: uuid.UUID, platform_id: uuid.UUID) -> bool:
    membership = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == user_id, Membership.platform_id == platform_id
            )
        )
    ).scalars().first()
    if membership is None:
        return False
    await db.delete(membership)
    await db.commit()
    return True
