"""Append-only record of everything that changes authority."""
import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sessions import client_ip
from app.models.identity import AuditLog


async def record(
    db: AsyncSession,
    *,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    target: str | None = None,
    meta: dict | None = None,
    request: Request | None = None,
    commit: bool = True,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            target=target,
            meta=meta or {},
            ip=client_ip(request) if request else None,
        )
    )
    if commit:
        await db.commit()
