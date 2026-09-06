"""Output shapes.

One place that decides what leaves the service, so a password hash cannot be
exposed by a handler that returned an ORM object by accident.
"""

from __future__ import annotations

from app.core.http import jsonable
from app.models import Membership, Plan, Platform, Role, SsoSession, Subscription, User


def user_public(user: User) -> dict:
    return jsonable(
        {
            "id": user.id,
            "email": user.email,
            "email_verified": user.email_verified,
            "full_name": user.full_name,
            "avatar_url": user.avatar_url,
            "status": user.status,
            "is_superadmin": user.is_superadmin,
            "mfa_enabled": user.mfa_enabled,
            "org_id": user.org_id,
            "last_login_at": user.last_login_at,
            "created_at": user.created_at,
        }
    )


def role_public(role: Role) -> dict:
    return jsonable(
        {
            "id": role.id,
            "code": role.code,
            "name": role.name,
            "description": role.description,
            "rank": role.rank,
            "is_default": role.is_default,
            "permissions": sorted(rp.permission.code for rp in role.permissions),
        }
    )


def platform_public(platform: Platform) -> dict:
    return jsonable(
        {
            "id": platform.id,
            "slug": platform.slug,
            "name": platform.name,
            "description": platform.description,
            "base_url": platform.base_url,
            "icon": platform.icon,
            "active": platform.active,
            "sort_order": platform.sort_order,
        }
    )


def plan_public(plan: Plan) -> dict:
    return jsonable(
        {
            "id": plan.id,
            "platform_id": plan.platform_id,
            "code": plan.code,
            "name": plan.name,
            "description": plan.description,
            "price_cents": plan.price_cents,
            "currency": plan.currency,
            "interval": plan.interval,
            "trial_days": plan.trial_days,
            "features": plan.features,
            "limits": plan.limits,
            "entitlements": plan.entitlements,
            "is_default": plan.is_default,
            "active": plan.active,
            "sort_order": plan.sort_order,
        }
    )


def subscription_public(sub: Subscription) -> dict:
    return jsonable(
        {
            "id": sub.id,
            "platform_id": sub.platform_id,
            "plan": plan_public(sub.plan),
            "status": sub.status,
            "started_at": sub.started_at,
            "current_period_end": sub.current_period_end,
            "canceled_at": sub.canceled_at,
        }
    )


def membership_public(membership: Membership) -> dict:
    return jsonable(
        {
            "id": membership.id,
            "user_id": membership.user_id,
            "platform": platform_public(membership.platform),
            "role": role_public(membership.role),
            "active": membership.active,
            "extra_permissions": membership.extra_permissions or [],
            "created_at": membership.created_at,
        }
    )


def session_public(row: SsoSession, *, current_id=None) -> dict:
    return jsonable(
        {
            "id": row.id,
            "user_agent": row.user_agent,
            "ip_address": row.ip_address,
            "created_at": row.created_at,
            "last_seen_at": row.last_seen_at,
            "expires_at": row.expires_at,
            "current": current_id is not None and row.id == current_id,
        }
    )


def access_entry(membership: Membership, subscription: Subscription | None) -> dict:
    """One row of "what can I reach" — what the account dashboard renders and
    what each platform's launcher uses to decide whether to show a tile."""
    return jsonable(
        {
            "platform": platform_public(membership.platform),
            "role": membership.role.code,
            "rank": membership.role.rank,
            "permissions": sorted(
                {rp.permission.code for rp in membership.role.permissions}
                | set(membership.extra_permissions or [])
            ),
            "active": membership.active,
            "subscription": subscription_public(subscription) if subscription else None,
        }
    )
