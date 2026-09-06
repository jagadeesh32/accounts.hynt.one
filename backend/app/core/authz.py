"""Who is calling, and may they do this.

``@authenticated`` resolves the SSO cookie; the ``require_*`` variants add a
floor on top. Handlers written with these receive ``(request, db, ctx)`` and can
assume ctx.user is a live, active account.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.core import sessions
from app.core.http import client_ip, endpoint, forbidden, get_cookie, unauthorized, user_agent
from app.models import ROLE_RANK, Membership, Platform, SsoSession, User


@dataclass(slots=True)
class AuthContext:
    """The authenticated caller at accounts.hynt.one itself."""

    user: User
    session: SsoSession
    ip: str | None
    agent: str | None

    @property
    def is_superadmin(self) -> bool:
        return self.user.is_superadmin


def current_context(request, db: Session) -> AuthContext | None:
    raw = get_cookie(request, config.COOKIE_NAME)
    resolved = sessions.resolve(db, raw)
    if resolved is None:
        return None
    row, user = resolved
    sessions.touch(db, row)
    return AuthContext(user=user, session=row, ip=client_ip(request), agent=user_agent(request))


def authenticated(func: Callable) -> Callable:
    """Handler signature becomes ``func(request, db, ctx)``."""

    @endpoint
    @wraps(func)
    def wrapper(request, db):
        ctx = current_context(request, db)
        if ctx is None:
            raise unauthorized("Your session has expired. Sign in again.")
        return func(request, db, ctx)

    return wrapper


def require_superadmin(func: Callable) -> Callable:
    """For routes that administer the identity provider itself."""

    @endpoint
    @wraps(func)
    def wrapper(request, db):
        ctx = current_context(request, db)
        if ctx is None:
            raise unauthorized("Your session has expired. Sign in again.")
        if not ctx.user.is_superadmin:
            raise forbidden("This action requires a superadmin.")
        return func(request, db, ctx)

    return wrapper


def require_platform_admin(func: Callable) -> Callable:
    """For routes scoped to one platform, identified by a ``{slug}`` path param.

    A superadmin passes everywhere. Anyone else needs an active membership on
    that specific platform ranked admin or above, so the terminal's admin cannot
    reach into intelligence's user list.
    """

    @endpoint
    @wraps(func)
    def wrapper(request, db):
        ctx = current_context(request, db)
        if ctx is None:
            raise unauthorized("Your session has expired. Sign in again.")

        slug = request.params.get("slug", "")
        platform = db.scalar(select(Platform).where(Platform.slug == slug))
        if platform is None:
            raise forbidden(f"Unknown platform '{slug}'.")

        if not ctx.user.is_superadmin:
            membership = db.scalar(
                select(Membership).where(
                    Membership.user_id == ctx.user.id,
                    Membership.platform_id == platform.id,
                    Membership.active.is_(True),
                )
            )
            if membership is None or membership.role.rank < ROLE_RANK["admin"]:
                raise forbidden(f"You are not an administrator of {platform.name}.")

        return func(request, db, ctx, platform)

    return wrapper


def has_at_least(role_code: str, minimum: str) -> bool:
    """Rank comparison, so callers ask "admin or above" rather than enumerating."""
    return ROLE_RANK.get(role_code, 0) >= ROLE_RANK.get(minimum, 999)
