"""Minting the audience-scoped access token.

The token is the whole point of the design: it carries enough for a platform to
authorise a request on its own, so nothing calls back here on the request path.
"""
import uuid
from datetime import timedelta

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.keys import get_active_key
from app.models.base import utcnow
from app.models.identity import User


async def mint_access_token(
    db: AsyncSession,
    *,
    user: User,
    platform_slug: str,
    session_id: uuid.UUID,
    role_slug: str,
    rank: int,
    permissions: list[str],
    plan_slug: str | None,
    plan_status: str | None,
    entitlements: list[str],
    limits: dict,
) -> tuple[str, int]:
    """Returns (jwt, expires_in_seconds)."""
    key = await get_active_key(db)
    now = utcnow()
    exp = now + timedelta(seconds=settings.access_token_ttl_seconds)

    claims = {
        "iss": settings.issuer,
        "sub": str(user.id),
        # Audience is one platform, never a list: a token minted for terminal
        # must be refused by X-Terminal, so a leak cannot travel sideways.
        "aud": platform_slug,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": uuid.uuid4().hex,
        "email": user.email,
        "name": user.full_name or "",
        "role": role_slug,
        "rank": rank,
        "perms": permissions,
        "plan": plan_slug,
        "plan_status": plan_status,
        "ent": entitlements,
        "lim": limits,
        # Token version and session id: the two handles a revocation can pull.
        "tv": user.token_version,
        "sid": str(session_id),
    }
    token = jwt.encode(claims, key.private_pem, algorithm="RS256", headers={"kid": key.kid})
    return token, settings.access_token_ttl_seconds


def decode_unverified(token: str) -> dict:
    """For diagnostics only — never for an authorisation decision."""
    return jwt.decode(token, options={"verify_signature": False})
