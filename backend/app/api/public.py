"""Unauthenticated reads: the platform list and public pricing.

Separated from the admin surface so the marketing site can render pricing without
any credential at all, and so it is obvious which reads are public.
"""

from __future__ import annotations

from cello import Blueprint
from sqlalchemy import select

from app.core.http import endpoint, not_found
from app.models import Plan, Platform
from app.schemas.serializers import plan_public, platform_public

bp = Blueprint("/api/v1")


@bp.get("/platforms")
@endpoint
def list_platforms(request, db):
    rows = db.scalars(
        select(Platform).where(Platform.active.is_(True)).order_by(Platform.sort_order)
    ).all()
    return {"platforms": [platform_public(p) for p in rows]}


@bp.get("/platforms/{slug}/plans")
@endpoint
def list_plans(request, db):
    """Public pricing for one platform."""
    slug = request.params.get("slug")
    platform = db.scalar(select(Platform).where(Platform.slug == slug))
    if platform is None or not platform.active:
        raise not_found(f"Unknown platform '{slug}'.")

    rows = db.scalars(
        select(Plan)
        .where(Plan.platform_id == platform.id, Plan.active.is_(True))
        .order_by(Plan.sort_order, Plan.price_cents)
    ).all()
    return {"platform": platform_public(platform), "plans": [plan_public(p) for p in rows]}


@bp.get("/health")
@endpoint
def health(request, db):
    """Liveness plus a real database round-trip — a health check that does not
    touch the database will happily report green while every request 500s."""
    from sqlalchemy import text

    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "accounts.hynt.one"}
