"""The signed-in user's own account: profile, password, MFA, launcher."""
import io

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import PasswordChangeIn, ProfileIn
from app.config import settings
from app.core import audit
from app.core.authz import Actor, current_actor, platform_claims
from app.core.security import hash_password, password_problem, verify_password
from app.core.sessions import revoke_all_sessions
from app.db import get_db
from app.models.rbac import Platform
from app.services import revocation

router = APIRouter(prefix="/api/v1/me", tags=["me"])


@router.get("")
async def profile(actor: Actor = Depends(current_actor)):
    u = actor.user
    return {
        "id": str(u.id),
        "email": u.email,
        "full_name": u.full_name or "",
        "status": u.status,
        "is_superadmin": u.is_superadmin,
        "mfa_enabled": u.mfa_enabled,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


@router.patch("")
async def update_profile(
    body: ProfileIn,
    request: Request,
    actor: Actor = Depends(current_actor),
    db: AsyncSession = Depends(get_db),
):
    if body.full_name is not None:
        actor.user.full_name = body.full_name.strip()
    await db.commit()
    await audit.record(db, action="profile.updated", actor_user_id=actor.user.id, request=request)
    return await profile(actor)


@router.get("/platforms")
async def my_platforms(actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    """What the launcher renders: every platform, with this user's standing on
    each. Platforms they are not a member of are listed too, greyed out — a
    missing tile reads as a bug, an explicit "no access" reads as an answer."""
    platforms = (
        await db.execute(select(Platform).where(Platform.is_active.is_(True)).order_by(Platform.slug))
    ).scalars().all()

    out = []
    for platform in platforms:
        claims = await platform_claims(db, actor.user, platform)
        out.append(
            {
                "slug": platform.slug,
                "name": platform.name,
                "description": platform.description,
                "icon": platform.icon,
                "url": platform.base_url,
                "member": claims is not None,
                "role": claims["role"] if claims else None,
                "plan": claims["plan"] if claims else None,
                "plan_status": claims["plan_status"] if claims else None,
                "entitlements": claims["entitlements"] if claims else [],
            }
        )
    return {"platforms": out}


@router.post("/password")
async def change_password(
    body: PasswordChangeIn,
    request: Request,
    actor: Actor = Depends(current_actor),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, actor.user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)

    actor.user.password_hash = hash_password(body.new_password)
    # A password change is a "someone may have been in here" event: bump the
    # token version so live access tokens die, and end every other session.
    actor.user.token_version += 1
    await db.commit()

    await revoke_all_sessions(db, actor.user.id, except_id=actor.session.id)
    await revocation.revoke_user(db, actor.user.id, reason="password changed")
    await audit.record(db, action="password.changed", actor_user_id=actor.user.id, request=request)
    return {"ok": True}


@router.post("/mfa/setup")
async def mfa_setup(actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    """Issues a secret but does not enable it — enabling requires proving the
    authenticator app actually holds it (see /mfa/enable)."""
    if actor.user.mfa_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Two-factor is already on")
    secret = pyotp.random_base32()
    actor.user.mfa_secret = secret
    await db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=actor.user.email, issuer_name="Hynt")
    return {"secret": secret, "otpauth_uri": uri}


@router.get("/mfa/qr.png")
async def mfa_qr(actor: Actor = Depends(current_actor)):
    if not actor.user.mfa_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Start setup first")
    uri = pyotp.TOTP(actor.user.mfa_secret).provisioning_uri(name=actor.user.email, issuer_name="Hynt")
    buf = io.BytesIO()
    qrcode.make(uri).save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/mfa/enable")
async def mfa_enable(
    payload: dict,
    request: Request,
    actor: Actor = Depends(current_actor),
    db: AsyncSession = Depends(get_db),
):
    code = str(payload.get("otp", "")).strip()
    if not actor.user.mfa_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Start setup first")
    if not pyotp.TOTP(actor.user.mfa_secret).verify(code, valid_window=1):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That code did not match")
    actor.user.mfa_enabled = True
    await db.commit()
    await audit.record(db, action="mfa.enabled", actor_user_id=actor.user.id, request=request)
    return {"ok": True}


@router.post("/mfa/disable")
async def mfa_disable(
    payload: dict,
    request: Request,
    actor: Actor = Depends(current_actor),
    db: AsyncSession = Depends(get_db),
):
    # Turning a factor off is a credential change: require the password, not
    # just the live session.
    if not verify_password(str(payload.get("password", "")), actor.user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password is incorrect")
    actor.user.mfa_enabled = False
    actor.user.mfa_secret = None
    await db.commit()
    await audit.record(db, action="mfa.disabled", actor_user_id=actor.user.id, request=request)
    return {"ok": True}
