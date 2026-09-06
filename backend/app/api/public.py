"""The endpoints platforms and browsers read without a session.

These three are the entire request-path contract with the rest of the estate:
discovery, the JWKS, and the revocation list.
"""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.keys import jwks as build_jwks
from app.db import get_db
from app.services import revocation

router = APIRouter(tags=["public"])


@router.get("/.well-known/openid-configuration")
async def discovery():
    issuer = settings.issuer
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "end_session_endpoint": f"{issuer}/oauth/logout",
        "jwks_uri": f"{issuer}/.well-known/jwks.json",
        "revocation_list_endpoint": f"{issuer}/api/v1/revocations",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["openid", "profile", "email"],
    }


@router.get("/.well-known/jwks.json")
async def jwks(response: Response, db: AsyncSession = Depends(get_db)):
    # Cached hard: every platform fetches this once and holds it. The TTL is
    # what bounds how long a rotation takes to reach the estate.
    response.headers["Cache-Control"] = "public, max-age=3600"
    return await build_jwks(db)


@router.get("/api/v1/revocations")
async def revocations(response: Response, db: AsyncSession = Depends(get_db)):
    # Polled every ~30s per platform. Short cache, never stale enough to matter.
    response.headers["Cache-Control"] = "public, max-age=15"
    return await revocation.current(db)


@router.get("/api/v1/health")
async def health(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import text

    await db.execute(text("SELECT 1"))
    return {"status": "ok", "issuer": settings.issuer}
