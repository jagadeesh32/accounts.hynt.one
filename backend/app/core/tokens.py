"""Minting and verifying the RS256 tokens the platforms consume.

An access token is audience-scoped to exactly one platform and carries
everything that platform needs to authorise a request: role, permissions, plan,
entitlements and quota limits. That is the trade being made — a slightly fatter
token in exchange for zero network calls on the authorisation path, and at most
``ACCESS_TOKEN_TTL_SEC`` of staleness after a role change.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy.orm import Session

from app import config
from app.core import keys
from app.core.security import new_secret
from app.models import Membership, Subscription, User

TYPE_ACCESS = "access"
TYPE_ID = "id"


@dataclass(slots=True)
class TokenGrant:
    """Everything resolved about one (user, platform) pair at mint time."""

    user: User
    platform_slug: str
    role: str = "user"
    rank: int = 10
    permissions: list[str] = field(default_factory=list)
    plan: str | None = None
    entitlements: list[str] = field(default_factory=list)
    limits: dict = field(default_factory=dict)
    subscription_status: str | None = None


def build_grant(
    user: User,
    platform_slug: str,
    membership: Membership | None,
    subscription: Subscription | None,
) -> TokenGrant:
    """Collapse membership + subscription into the claim set.

    A superadmin is granted the top role on every platform regardless of
    membership — otherwise locking yourself out of a platform you own would be
    one bad UPDATE away, with no path back in.
    """
    grant = TokenGrant(user=user, platform_slug=platform_slug)

    if user.is_superadmin:
        grant.role = "superadmin"
        grant.rank = 40
        grant.permissions = ["*"]
    elif membership is not None and membership.active:
        grant.role = membership.role.code
        grant.rank = membership.role.rank
        codes = {rp.permission.code for rp in membership.role.permissions}
        codes.update(membership.extra_permissions or [])
        grant.permissions = sorted(codes)

    if subscription is not None:
        grant.plan = subscription.plan.code
        grant.subscription_status = subscription.status.value
        # Entitlements only count while the subscription is actually current. A
        # canceled plan that kept handing out its features would make cancelling
        # a no-op.
        if subscription.is_current:
            grant.entitlements = list(subscription.plan.entitlements or [])
            grant.limits = dict(subscription.plan.limits or {})

    return grant


def _base_claims(user: User, audience: str, ttl: int, token_type: str) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "iss": config.ISSUER,
        "sub": str(user.id),
        "aud": audience,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "jti": new_secret(16),
        "typ": token_type,
    }


def issue_access_token(
    session: Session,
    grant: TokenGrant,
    *,
    sso_session_id: uuid.UUID | None = None,
    scope: str = "openid profile email",
) -> tuple[str, int]:
    """Return ``(jwt, expires_in_seconds)``."""
    user = grant.user
    claims = _base_claims(user, grant.platform_slug, config.ACCESS_TOKEN_TTL_SEC, TYPE_ACCESS)
    claims.update(
        {
            "email": user.email,
            "email_verified": user.email_verified,
            "name": user.full_name,
            "org": str(user.org_id),
            "role": grant.role,
            "rank": grant.rank,
            "perms": grant.permissions,
            "plan": grant.plan,
            "plan_status": grant.subscription_status,
            "ent": grant.entitlements,
            "lim": grant.limits,
            # Bumped on password change, sign-out-everywhere and suspension. The
            # platforms cannot see this table, so it travels in the token and is
            # what makes a 15-minute window the worst case rather than forever.
            "tv": user.token_version,
            "sid": str(sso_session_id) if sso_session_id else None,
            "scope": scope,
        }
    )
    kid, private_pem = keys.active_key(session)
    encoded = jwt.encode(claims, private_pem, algorithm=config.JWT_ALG, headers={"kid": kid})
    return encoded, config.ACCESS_TOKEN_TTL_SEC


def issue_id_token(
    session: Session,
    user: User,
    audience: str,
    *,
    nonce: str | None = None,
    sso_session_id: uuid.UUID | None = None,
) -> str:
    """OIDC identity token: who the user is, not what they may do."""
    claims = _base_claims(user, audience, config.ID_TOKEN_TTL_SEC, TYPE_ID)
    claims.update(
        {
            "email": user.email,
            "email_verified": user.email_verified,
            "name": user.full_name,
            "picture": user.avatar_url,
            "org": str(user.org_id),
            "sid": str(sso_session_id) if sso_session_id else None,
        }
    )
    if nonce:
        claims["nonce"] = nonce
    kid, private_pem = keys.active_key(session)
    return jwt.encode(claims, private_pem, algorithm=config.JWT_ALG, headers={"kid": kid})


def decode(session: Session, token: str, *, audience: str | None = None) -> dict | None:
    """Verify a token this service issued. Returns None on any failure.

    Used by the introspection endpoint; the platforms do this themselves against
    the JWKS rather than calling here.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        return None

    key_jwk = next(
        (k for k in keys.jwks(session)["keys"] if k.get("kid") == header.get("kid")), None
    )
    if key_jwk is None:
        return None

    try:
        public_key = jwt.PyJWK.from_dict(key_jwk).key
        return jwt.decode(
            token,
            public_key,
            algorithms=[config.JWT_ALG],
            issuer=config.ISSUER,
            audience=audience,
            options={"verify_aud": audience is not None},
        )
    except jwt.PyJWTError:
        return None
