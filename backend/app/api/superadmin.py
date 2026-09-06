"""Running the identity provider itself. Superadmin only, without exception."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ClientIn, CreateUserIn, PlatformIn
from app.core import audit
from app.core.authz import Actor, require_superadmin
from app.core.http import parse_uuid
from app.core.keys import rotate_key
from app.core.security import hash_password, password_problem
from app.core.sessions import revoke_all_sessions
from app.db import get_db
from app.models.billing import Plan, Subscription
from app.models.identity import AuditLog, Session, User
from app.models.oauth import OAuthClient, SigningKey
from app.models.rbac import Membership, Platform, Role
from app.services import provisioning, revocation

router = APIRouter(prefix="/api/v1/superadmin", tags=["superadmin"], dependencies=[Depends(require_superadmin)])


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    async def count(model, *where):
        return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar_one()

    return {
        "users": await count(User),
        "suspended": await count(User, User.status != "active"),
        "active_sessions": await count(Session, Session.revoked_at.is_(None)),
        "platforms": await count(Platform),
        "memberships": await count(Membership),
        "clients": await count(OAuthClient),
    }


@router.get("/users")
async def list_users(
    q: str = "",
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User)
    if q:
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(func.lower(User.email).like(needle) | func.lower(func.coalesce(User.full_name, "")).like(needle))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(User.created_at.desc()).limit(min(limit, 500)).offset(offset))).scalars().all()

    return {
        "total": total,
        "users": [
            {
                "id": str(u.id),
                "email": u.email,
                "full_name": u.full_name or "",
                "status": u.status,
                "is_superadmin": u.is_superadmin,
                "mfa_enabled": u.mfa_enabled,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
                "memberships": [
                    {"platform": m.platform.slug, "role": m.role.slug} for m in u.memberships
                ],
            }
            for u in rows
        ],
    }


@router.post("/users")
async def create_user(body: CreateUserIn, request: Request, actor: Actor = Depends(require_superadmin), db: AsyncSession = Depends(get_db)):
    email = body.email.strip().lower()
    if (await db.execute(select(User).where(User.email == email))).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, "That email already has an account")

    password = body.password or secrets.token_urlsafe(12)
    problem = password_problem(password)
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)

    user = User(email=email, full_name=body.full_name, password_hash=hash_password(password))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    if body.platform:
        platform = (await db.execute(select(Platform).where(Platform.slug == body.platform))).scalars().first()
        if platform is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No such platform")
        await provisioning.grant(db, user_id=user.id, platform=platform, role_slug=body.role, plan_slug=body.plan)

    await audit.record(db, action="user.created", actor_user_id=actor.user.id, target=email, request=request)
    return {"ok": True, "id": str(user.id), "password": None if body.password else password}


@router.post("/users/{user_id}/suspend")
async def suspend(user_id: str, request: Request, actor: Actor = Depends(require_superadmin), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, parse_uuid(user_id, "user"))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user")
    if user.id == actor.user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot suspend yourself")

    user.status = "suspended"
    user.token_version += 1
    await db.commit()

    # Suspension is the case the revocation list exists for: end the sessions,
    # then publish so the platforms stop honouring live tokens within seconds.
    await revoke_all_sessions(db, user.id)
    await revocation.revoke_user(db, user.id, reason="account suspended")
    await audit.record(db, action="user.suspended", actor_user_id=actor.user.id, target=user.email, request=request)
    return {"ok": True}


@router.post("/users/{user_id}/reinstate")
async def reinstate(user_id: str, request: Request, actor: Actor = Depends(require_superadmin), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, parse_uuid(user_id, "user"))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user")
    user.status = "active"
    await db.commit()
    await audit.record(db, action="user.reinstated", actor_user_id=actor.user.id, target=user.email, request=request)
    return {"ok": True}


@router.post("/users/{user_id}/password")
async def reset_password(user_id: str, payload: dict, request: Request, actor: Actor = Depends(require_superadmin), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, parse_uuid(user_id, "user"))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user")

    password = str(payload.get("password") or secrets.token_urlsafe(12))
    problem = password_problem(password)
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)

    user.password_hash = hash_password(password)
    user.token_version += 1
    await db.commit()
    await revoke_all_sessions(db, user.id)
    await revocation.revoke_user(db, user.id, reason="password reset by superadmin")
    await audit.record(db, action="user.password_reset", actor_user_id=actor.user.id, target=user.email, request=request)
    return {"ok": True, "password": password if not payload.get("password") else None}


@router.post("/users/{user_id}/superadmin")
async def set_superadmin(user_id: str, payload: dict, request: Request, actor: Actor = Depends(require_superadmin), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, parse_uuid(user_id, "user"))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user")
    enable = bool(payload.get("enabled"))
    if not enable and user.id == actor.user.id:
        # Removing your own last superadmin is how an estate locks itself out.
        remaining = (
            await db.execute(select(func.count()).select_from(User).where(User.is_superadmin.is_(True), User.id != user.id))
        ).scalar_one()
        if remaining == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "You are the only superadmin")
    user.is_superadmin = enable
    await db.commit()
    await revocation.revoke_user(db, user.id, reason="superadmin flag changed")
    await audit.record(db, action="user.superadmin_set", actor_user_id=actor.user.id, target=user.email, meta={"enabled": enable}, request=request)
    return {"ok": True}


@router.get("/platforms")
async def list_platforms(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Platform).order_by(Platform.slug))).scalars().all()
    out = []
    for p in rows:
        members = (await db.execute(select(func.count()).select_from(Membership).where(Membership.platform_id == p.id))).scalar_one()
        out.append({
            "id": str(p.id), "slug": p.slug, "name": p.name, "base_url": p.base_url,
            "description": p.description, "icon": p.icon, "is_active": p.is_active, "members": members,
        })
    return {"platforms": out}


@router.put("/platforms/{slug}")
async def upsert_platform(slug: str, body: PlatformIn, request: Request, actor: Actor = Depends(require_superadmin), db: AsyncSession = Depends(get_db)):
    platform = (await db.execute(select(Platform).where(Platform.slug == slug))).scalars().first()
    if platform is None:
        platform = Platform(slug=slug)
        db.add(platform)
    platform.name = body.name
    platform.base_url = body.base_url
    platform.description = body.description
    platform.icon = body.icon
    await db.commit()
    await audit.record(db, action="platform.saved", actor_user_id=actor.user.id, target=slug, request=request)
    return {"ok": True}


@router.get("/clients")
async def list_clients(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(OAuthClient).order_by(OAuthClient.client_id))).scalars().all()
    platforms = {p.id: p.slug for p in (await db.execute(select(Platform))).scalars()}
    return {
        "clients": [
            {
                "client_id": c.client_id, "name": c.name, "platform": platforms.get(c.platform_id),
                "redirect_uris": c.redirect_uris, "is_public": c.is_public, "is_active": c.is_active,
            }
            for c in rows
        ]
    }


@router.put("/clients/{client_id}")
async def upsert_client(client_id: str, body: ClientIn, request: Request, actor: Actor = Depends(require_superadmin), db: AsyncSession = Depends(get_db)):
    platform = (await db.execute(select(Platform).where(Platform.slug == body.platform))).scalars().first()
    if platform is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No such platform")

    client = (await db.execute(select(OAuthClient).where(OAuthClient.client_id == client_id))).scalars().first()
    if client is None:
        client = OAuthClient(client_id=client_id)
        db.add(client)
    client.name = body.name
    client.platform_id = platform.id
    client.redirect_uris = body.redirect_uris
    client.is_public = body.is_public

    secret = None
    if not body.is_public and not client.secret_hash:
        secret = secrets.token_urlsafe(32)
        client.secret_hash = hash_password(secret)

    await db.commit()
    await audit.record(db, action="client.saved", actor_user_id=actor.user.id, target=client_id, request=request)
    return {"ok": True, "client_secret": secret}


@router.get("/keys")
async def list_keys(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(SigningKey).order_by(SigningKey.created_at.desc()))).scalars().all()
    return {
        "keys": [
            {
                "kid": k.kid, "is_active": k.is_active,
                "created_at": k.created_at.isoformat(),
                "retired_at": k.retired_at.isoformat() if k.retired_at else None,
            }
            for k in rows
        ]
    }


@router.post("/keys/rotate")
async def rotate(request: Request, actor: Actor = Depends(require_superadmin), db: AsyncSession = Depends(get_db)):
    key = await rotate_key(db)
    await audit.record(db, action="key.rotated", actor_user_id=actor.user.id, target=key.kid, request=request)
    # Platforms cache the JWKS for an hour; until it refreshes they hold only
    # the old key, so the new one cannot verify anywhere yet.
    return {"ok": True, "kid": key.kid, "note": "Platforms pick this up on their next JWKS refresh (<= 1h)."}


@router.get("/audit")
async def audit_log(limit: int = 100, offset: int = 0, action: str = "", db: AsyncSession = Depends(get_db)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = (await db.execute(stmt.order_by(AuditLog.created_at.desc()).limit(min(limit, 500)).offset(offset))).scalars().all()
    actors = {u.id: u.email for u in (await db.execute(select(User))).scalars()}
    return {
        "events": [
            {
                "at": r.created_at.isoformat(), "action": r.action,
                "actor": actors.get(r.actor_user_id) if r.actor_user_id else None,
                "target": r.target, "meta": r.meta, "ip": r.ip,
            }
            for r in rows
        ]
    }
