"""Creating accounts and granting access.

Shared by self-service registration, the admin console and the CLI, so a user
created any of those three ways ends up in exactly the same state. The earlier
per-platform scripts each seeded users slightly differently, which is how the
same person ended up with three unrelated logins in the first place.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import (
    Membership,
    Organization,
    Plan,
    Platform,
    Role,
    RoleCode,
    Subscription,
    SubscriptionStatus,
    User,
    UserStatus,
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    return _SLUG_RE.sub("-", value.strip().lower()).strip("-") or "org"


def unique_org_slug(db: Session, base: str) -> str:
    slug = slugify(base)
    candidate, n = slug, 1
    while db.scalar(select(Organization.id).where(Organization.slug == candidate)) is not None:
        n += 1
        candidate = f"{slug}-{n}"
    return candidate


def create_user_account(
    db: Session,
    *,
    email: str,
    password: str | None,
    full_name: str = "",
    is_superadmin: bool = False,
    status: UserStatus = UserStatus.ACTIVE,
    org: Organization | None = None,
    grant_defaults: bool = True,
) -> User:
    """Create the account, its organization, and its default access.

    ``password=None`` creates a PENDING account with an unusable hash — the user
    activates it through the password-reset flow, which is how invitations work
    without a second token type.
    """
    email = email.strip().lower()

    if org is None:
        local_part = email.split("@", 1)[0]
        org = Organization(
            name=full_name or local_part,
            slug=unique_org_slug(db, full_name or local_part),
            billing_email=email,
        )
        db.add(org)
        db.flush()

    import secrets

    user = User(
        org_id=org.id,
        email=email,
        full_name=full_name,
        password_hash=hash_password(password if password else secrets.token_urlsafe(32)),
        status=UserStatus.PENDING if password is None else status,
        is_superadmin=is_superadmin,
    )
    db.add(user)
    db.flush()

    if grant_defaults:
        grant_default_access(db, user)

    return user


def grant_default_access(db: Session, user: User) -> list[Membership]:
    """Give a new account the default role and default plan on every active
    platform that defines them.

    A platform with no default role is opt-in: nobody reaches it until an
    administrator grants membership explicitly.
    """
    created: list[Membership] = []
    platforms = db.scalars(select(Platform).where(Platform.active.is_(True))).all()

    for platform in platforms:
        default_role = db.scalar(
            select(Role).where(Role.platform_id == platform.id, Role.is_default.is_(True))
        )
        if default_role is None:
            continue
        created.append(grant_membership(db, user, platform, default_role))

        default_plan = db.scalar(
            select(Plan).where(
                Plan.platform_id == platform.id,
                Plan.is_default.is_(True),
                Plan.active.is_(True),
            )
        )
        if default_plan is not None:
            assign_subscription(db, user, platform, default_plan)

    return created


def grant_membership(db: Session, user: User, platform: Platform, role: Role) -> Membership:
    """Idempotent: granting access a second time updates the role rather than
    failing on the unique constraint."""
    existing = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id, Membership.platform_id == platform.id
        )
    )
    if existing is not None:
        existing.role_id = role.id
        existing.active = True
        db.flush()
        return existing

    membership = Membership(
        user_id=user.id, platform_id=platform.id, role_id=role.id, active=True,
        extra_permissions=[],
    )
    db.add(membership)
    db.flush()
    return membership


def assign_subscription(
    db: Session,
    user: User,
    platform: Platform,
    plan: Plan,
    *,
    status: SubscriptionStatus | None = None,
) -> Subscription:
    """Put the user on a plan, starting a trial when the plan defines one."""
    now = datetime.now(timezone.utc)

    if status is None:
        status = SubscriptionStatus.TRIALING if plan.trial_days else SubscriptionStatus.ACTIVE

    period_end: datetime | None = None
    if plan.trial_days:
        period_end = now + timedelta(days=plan.trial_days)
    elif plan.interval.value == "monthly":
        period_end = now + timedelta(days=30)
    elif plan.interval.value == "yearly":
        period_end = now + timedelta(days=365)

    existing = db.scalar(
        select(Subscription).where(
            Subscription.user_id == user.id, Subscription.platform_id == platform.id
        )
    )
    if existing is not None:
        existing.plan_id = plan.id
        existing.status = status
        existing.current_period_end = period_end
        existing.canceled_at = None
        db.flush()
        return existing

    sub = Subscription(
        user_id=user.id,
        org_id=user.org_id,
        platform_id=platform.id,
        plan_id=plan.id,
        status=status,
        started_at=now,
        current_period_end=period_end,
    )
    db.add(sub)
    db.flush()
    return sub


def role_for(db: Session, platform: Platform, code: str) -> Role | None:
    return db.scalar(select(Role).where(Role.platform_id == platform.id, Role.code == code))


def default_roles_for_platform(platform_id) -> list[dict]:
    """The four roles every platform gets when it is created.

    ``user`` is the default so that being granted access to a platform means
    something concrete without an administrator picking a role every time.
    """
    return [
        {"code": RoleCode.ADMIN.value, "name": "Administrator", "rank": 30, "is_default": False,
         "description": "Full control of this platform, including its users and plans."},
        {"code": RoleCode.STAFF.value, "name": "Staff", "rank": 20, "is_default": False,
         "description": "Operate the platform; cannot change users, roles or billing."},
        {"code": RoleCode.USER.value, "name": "User", "rank": 10, "is_default": True,
         "description": "Standard access, limited by the subscribed plan."},
    ]
