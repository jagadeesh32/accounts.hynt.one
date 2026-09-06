"""Sign in, sign out, and the session list behind the security page."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import pyotp

from app.api.schemas import LoginIn
from app.core import audit, throttle
from app.core.http import parse_uuid
from app.core.authz import Actor, current_actor
from app.core.security import hash_password, needs_rehash, verify_password
from app.core.sessions import (
    clear_session_cookie,
    client_ip,
    create_session,
    resolve_session,
    revoke_all_sessions,
    revoke_session,
    set_session_cookie,
)
from app.db import get_db
from app.models.base import utcnow
from app.models.identity import Session, User
from app.services import revocation

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login")
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    email = body.email.strip().lower()
    # Throttle on both axes: the address stops credential stuffing against one
    # account, the IP stops one host working through a list of addresses.
    throttle.check(f"login:email:{email}")
    throttle.check(f"login:ip:{client_ip(request)}", limit=30)

    user = (await db.execute(select(User).where(User.email == email))).scalars().first()

    # One message and one code path for "no such user" and "wrong password" —
    # anything else turns this endpoint into an account-existence oracle.
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if user is None or not verify_password(body.password, user.password_hash):
        await audit.record(db, action="login.failed", target=email, request=request)
        raise invalid

    if user.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is suspended")

    if user.mfa_enabled:
        if not body.otp:
            return {"mfa_required": True}
        if not pyotp.TOTP(user.mfa_secret).verify(body.otp, valid_window=1):
            await audit.record(db, action="login.mfa_failed", actor_user_id=user.id, request=request)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect verification code")

    # Cost parameters may have been raised since this hash was written.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    user.last_login_at = utcnow()
    session, raw = await create_session(db, user, request)
    set_session_cookie(response, raw)
    throttle.reset(f"login:email:{email}")

    await audit.record(db, action="login.ok", actor_user_id=user.id, target=str(session.id), request=request)
    return {"ok": True, "user": {"id": str(user.id), "email": user.email, "name": user.full_name or ""}}


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Signing out here signs the user out everywhere — that is the promise the
    shared cookie makes, so the session id is published as revoked too."""
    resolved = await resolve_session(db, request)
    clear_session_cookie(response)
    if resolved is None:
        return {"ok": True}
    session, user = resolved
    await revoke_session(db, session)
    await revocation.revoke_session_id(db, session.id, reason="logout")
    await audit.record(db, action="logout", actor_user_id=user.id, target=str(session.id), request=request)
    return {"ok": True}


@router.get("/session")
async def whoami(request: Request, db: AsyncSession = Depends(get_db)):
    """Unauthenticated-safe: the login page calls this to decide whether to
    render the form or bounce straight into the launcher."""
    resolved = await resolve_session(db, request)
    if resolved is None:
        return {"authenticated": False}
    _, user = resolved
    return {
        "authenticated": True,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.full_name or "",
            "is_superadmin": user.is_superadmin,
        },
    }


@router.get("/sessions")
async def list_sessions(actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Session)
            .where(Session.user_id == actor.user.id, Session.revoked_at.is_(None))
            .order_by(Session.last_seen_at.desc())
        )
    ).scalars().all()
    now = utcnow()
    return {
        "sessions": [
            {
                "id": str(r.id),
                "current": r.id == actor.session.id,
                "user_agent": r.user_agent,
                "ip": r.ip,
                "created_at": r.created_at.isoformat(),
                "last_seen_at": r.last_seen_at.isoformat(),
                "expired": r.expires_at <= now,
            }
            for r in rows
            if r.expires_at > now
        ]
    }


@router.delete("/sessions/{session_id}")
async def kill_session(
    session_id: str,
    request: Request,
    actor: Actor = Depends(current_actor),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Session, parse_uuid(session_id, "session"))
    if row is None or row.user_id != actor.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such session")
    await revoke_session(db, row)
    await revocation.revoke_session_id(db, row.id, reason="user revoked device")
    await audit.record(db, action="session.revoked", actor_user_id=actor.user.id, target=str(row.id), request=request)
    return {"ok": True}


@router.post("/sessions/revoke-others")
async def kill_other_sessions(
    request: Request,
    actor: Actor = Depends(current_actor),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(Session).where(Session.user_id == actor.user.id, Session.revoked_at.is_(None))
        )
    ).scalars().all()
    for row in rows:
        if row.id != actor.session.id:
            await revocation.revoke_session_id(db, row.id, reason="signed out other devices", commit=False)
    count = await revoke_all_sessions(db, actor.user.id, except_id=actor.session.id)
    await audit.record(db, action="sessions.revoked_others", actor_user_id=actor.user.id, meta={"count": count}, request=request)
    return {"ok": True, "revoked": count}
