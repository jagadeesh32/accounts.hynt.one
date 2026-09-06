"""The OAuth 2.1 surface: authorization code + PKCE, no refresh tokens.

Shape of the flow (README, "How it works"):
  1. platform SPA redirects here with a PKCE challenge
  2. the hynt_sso cookie decides whether a password is needed
  3. we redirect back with a 60-second, single-use code
  4. the SPA exchanges it for a 15-minute RS256 token scoped to that platform
"""
import base64
import hashlib
from datetime import timedelta
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import TokenIn
from app.config import settings
from app.core import audit
from app.core.authz import platform_claims
from app.core.security import constant_time_eq, new_opaque_token, sha256
from app.core.sessions import clear_session_cookie, resolve_session, revoke_session
from app.core.tokens import mint_access_token
from app.db import get_db
from app.models.base import utcnow
from app.models.oauth import AuthorizationCode, OAuthClient
from app.models.rbac import Platform
from app.services import revocation

router = APIRouter(tags=["oauth"])


def _redirect_with(redirect_uri: str, params: dict) -> RedirectResponse:
    joiner = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{joiner}{urlencode(params)}", status_code=302)


def _uri_registered(client: OAuthClient, redirect_uri: str) -> bool:
    """Exact match against the registered list, plus a host suffix check.

    Exact match is what stops an open redirector; the suffix check is a second
    fence so a mis-registered URI cannot point the estate's codes off-domain.
    """
    if redirect_uri not in (client.redirect_uris or []):
        return False
    host = (urlparse(redirect_uri).hostname or "").lower()
    return any(host == s or host.endswith("." + s) for s in settings.redirect_host_suffixes) or host in {
        "localhost",
        "127.0.0.1",
    }


@router.get("/oauth/authorize")
async def authorize(
    request: Request,
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    scope: str = "",
    state: str = "",
    prompt: str = "",
    db: AsyncSession = Depends(get_db),
):
    client = (
        await db.execute(select(OAuthClient).where(OAuthClient.client_id == client_id))
    ).scalars().first()

    # Errors about the client or the redirect_uri itself must be rendered here,
    # never redirected — bouncing to an unvalidated URI is the open redirect.
    if client is None or not client.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown client")
    if not _uri_registered(client, redirect_uri):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "redirect_uri is not registered for this client")

    if response_type != "code":
        return _redirect_with(redirect_uri, {"error": "unsupported_response_type", "state": state})
    if code_challenge_method != "S256" or not code_challenge:
        return _redirect_with(redirect_uri, {"error": "invalid_request", "error_description": "PKCE S256 required", "state": state})

    resolved = await resolve_session(db, request)

    if resolved is None:
        # prompt=none is the hidden renewal iframe. It must never show a login
        # page: the iframe would render an unusable form the user cannot see.
        if prompt == "none":
            return _redirect_with(redirect_uri, {"error": "login_required", "state": state})
        # Bounce to the SPA's login route, carrying the whole authorize request
        # so the browser lands back here once the cookie exists.
        nxt = f"/oauth/authorize?{urlencode(dict(request.query_params))}"
        return RedirectResponse(f"/login?{urlencode({'next': nxt})}", status_code=302)

    session, user = resolved

    platform = await db.get(Platform, client.platform_id)
    if platform is None or not platform.is_active:
        return _redirect_with(redirect_uri, {"error": "temporarily_unavailable", "state": state})

    claims = await platform_claims(db, user, platform)
    if claims is None:
        # Signed in, but not a member of this platform. This is not a login
        # failure; the SPA shows "request access" rather than a password form.
        return _redirect_with(redirect_uri, {"error": "access_denied", "error_description": "no_membership", "state": state})

    raw_code = new_opaque_token(32)
    db.add(
        AuthorizationCode(
            code_hash=sha256(raw_code),
            client_id=client.client_id,
            user_id=user.id,
            session_id=session.id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope,
            expires_at=utcnow() + timedelta(seconds=settings.auth_code_ttl_seconds),
        )
    )
    await db.commit()

    return _redirect_with(redirect_uri, {"code": raw_code, "state": state})


@router.post("/oauth/token")
async def token(request: Request, db: AsyncSession = Depends(get_db)):
    """Exchange the code for an access token. Accepts JSON or form encoding —
    the browser SDK sends JSON, curl and the spec send a form."""
    if request.headers.get("content-type", "").startswith("application/json"):
        payload = await request.json()
    else:
        payload = dict(await request.form())

    try:
        body = TokenIn(**payload)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_request")

    if body.grant_type != "authorization_code":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unsupported_grant_type")

    row = (
        await db.execute(select(AuthorizationCode).where(AuthorizationCode.code_hash == sha256(body.code)))
    ).scalars().first()
    invalid = HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_grant")
    if row is None:
        raise invalid

    now = utcnow()
    if row.used_at is not None:
        # A replayed code means the first exchange leaked. Kill the session it
        # was minted from rather than just refusing this request.
        await revocation.revoke_session_id(db, row.session_id, reason="authorization code replay")
        await audit.record(db, action="oauth.code_replay", actor_user_id=row.user_id, target=row.client_id, request=request)
        raise invalid
    if row.expires_at <= now or row.client_id != body.client_id or row.redirect_uri != body.redirect_uri:
        raise invalid

    # PKCE: the verifier the SPA kept is hashed and compared to the challenge it
    # sent at /authorize. An intercepted code is useless without the verifier.
    digest = base64.urlsafe_b64encode(hashlib.sha256(body.code_verifier.encode()).digest()).rstrip(b"=").decode()
    if not constant_time_eq(digest, row.code_challenge):
        raise invalid

    row.used_at = now

    from app.models.identity import Session as SessionRow
    from app.models.identity import User

    user = await db.get(User, row.user_id)
    session = await db.get(SessionRow, row.session_id)
    if user is None or user.status != "active" or session is None or session.revoked_at is not None:
        await db.commit()
        raise invalid

    client = (
        await db.execute(select(OAuthClient).where(OAuthClient.client_id == row.client_id))
    ).scalars().first()
    platform = await db.get(Platform, client.platform_id) if client else None
    if platform is None:
        await db.commit()
        raise invalid

    claims = await platform_claims(db, user, platform)
    if claims is None:
        await db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "access_denied")

    access_token, expires_in = await mint_access_token(
        db,
        user=user,
        platform_slug=platform.slug,
        session_id=session.id,
        role_slug=claims["role"],
        rank=claims["rank"],
        permissions=claims["permissions"],
        plan_slug=claims["plan"],
        plan_status=claims["plan_status"],
        entitlements=claims["entitlements"],
        limits=claims["limits"],
    )
    await db.commit()

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "scope": row.scope,
        # Handed back so the SPA can render a name without decoding the JWT.
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.full_name or "",
            "role": claims["role"],
            "rank": claims["rank"],
            "permissions": claims["permissions"],
            "plan": claims["plan"],
            "plan_status": claims["plan_status"],
            "entitlements": claims["entitlements"],
            "limits": claims["limits"],
        },
    }


@router.get("/oauth/logout")
async def oauth_logout(
    request: Request,
    redirect_uri: str = "",
    client_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Signs out of the estate, then returns to the platform that asked.

    The redirect target is validated against the client's registered list for
    the same reason /authorize validates it."""
    resolved = await resolve_session(db, request)
    if resolved is not None:
        session, user = resolved
        await revoke_session(db, session)
        await revocation.revoke_session_id(db, session.id, reason="logout")
        await audit.record(db, action="logout", actor_user_id=user.id, target=str(session.id), request=request)

    target = "/"
    if redirect_uri and client_id:
        client = (
            await db.execute(select(OAuthClient).where(OAuthClient.client_id == client_id))
        ).scalars().first()
        if client and _uri_registered(client, redirect_uri):
            target = redirect_uri

    response = RedirectResponse(target, status_code=302)
    clear_session_cookie(response)
    return response
