"""Analytics — the aggregate read of the estate, and of one platform.

Everything here is a GROUP BY in the database, not a page of rows the browser
adds up. That matters for more than speed: a chart built from "the last 100
audit rows the table happened to load" silently lies about every window wider
than those rows, and the lie is invisible because the chart still draws.

Two surfaces, two guards:

  * /api/v1/superadmin/analytics — the whole estate. Superadmin only.
  * /api/v1/admin/{slug}/analytics — one platform, gated on the caller's rank
    on THAT platform, exactly like the rest of the per-platform console.

Series are returned dense (every day in the window present, zeros included) and
sorted. Sparse series are the classic source of a chart that draws a smooth line
straight across a five-day outage, and every consumer would otherwise have to
re-densify them itself.

Windows are half-open [start, now] on whole UTC days. `prev` covers the window of
the same length immediately before it, so "vs previous period" is a like-for-like
comparison rather than a comparison against a partially-elapsed period.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Actor, current_actor, require_platform_rank, require_superadmin
from app.db import get_db
from app.models.billing import Plan, Subscription
from app.models.identity import AuditLog, Session, User
from app.models.oauth import OAuthClient
from app.models.rbac import Membership, Platform, Role

router = APIRouter(prefix="/api/v1/superadmin", tags=["analytics"], dependencies=[Depends(require_superadmin)])
platform_router = APIRouter(prefix="/api/v1/admin", tags=["analytics"])

STAFF_RANK = 20

# Sign-in outcomes, kept in one place because three different aggregates below
# have to agree on what counts as a success and what counts as a rejection.
LOGIN_OK = "login.ok"
LOGIN_BAD = ("login.failed", "login.mfa_failed")


def _window(days: int) -> tuple[datetime, datetime, datetime]:
    """(start, previous-start, now) on whole UTC days."""
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start - timedelta(days=days), now


def _dense(rows: list[tuple], start: datetime, days: int) -> list[dict]:
    """Fill the gaps. `rows` is [(date, count)] as the database returned it."""
    got = {r[0].date().isoformat() if hasattr(r[0], "date") else str(r[0]): int(r[1]) for r in rows}
    out = []
    for i in range(days):
        d = (start + timedelta(days=i)).date().isoformat()
        out.append({"d": d, "v": got.get(d, 0)})
    return out


async def _daily(db: AsyncSession, column, *where, start: datetime, days: int) -> list[dict]:
    day = func.date_trunc("day", column).label("day")
    rows = (
        await db.execute(
            select(day, func.count()).where(column >= start, *where).group_by(day).order_by(day)
        )
    ).all()
    return _dense(rows, start, days)


async def _scalar(db: AsyncSession, stmt) -> int:
    return int((await db.execute(stmt)).scalar_one() or 0)


def _monthly_value(price_inr: int, interval: str) -> float:
    """Normalise a plan price to one month, so a yearly plan does not read as
    twelve months of revenue in a monthly figure."""
    if interval == "year":
        return price_inr / 12
    if interval == "week":
        return price_inr * 52 / 12
    return float(price_inr)


@router.get("/analytics")
async def estate_analytics(
    days: int = Query(30, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
):
    start, prev_start, now = _window(days)

    # ── headline counts ──────────────────────────────────────────────────
    users_total = await _scalar(db, select(func.count()).select_from(User))
    suspended = await _scalar(db, select(func.count()).select_from(User).where(User.status != "active"))
    mfa_on = await _scalar(db, select(func.count()).select_from(User).where(User.mfa_enabled.is_(True)))
    superadmins = await _scalar(db, select(func.count()).select_from(User).where(User.is_superadmin.is_(True)))
    # The single most useful number on this page: an account that can rotate the
    # signing keys and reach every platform, protected by a password alone.
    superadmins_no_mfa = await _scalar(
        db,
        select(func.count()).select_from(User).where(User.is_superadmin.is_(True), User.mfa_enabled.is_(False)),
    )
    live_sessions = await _scalar(
        db, select(func.count()).select_from(Session).where(Session.revoked_at.is_(None), Session.expires_at > now)
    )

    # ── daily series ─────────────────────────────────────────────────────
    signups = await _daily(db, User.created_at, start=start, days=days)
    logins = await _daily(db, AuditLog.created_at, AuditLog.action == LOGIN_OK, start=start, days=days)
    failures = await _daily(db, AuditLog.created_at, AuditLog.action.in_(LOGIN_BAD), start=start, days=days)
    admin_actions = await _daily(
        db, AuditLog.created_at,
        AuditLog.action.notin_((LOGIN_OK, *LOGIN_BAD, "logout")),
        start=start, days=days,
    )

    # Distinct people signing in per day — the honest "active" number. A single
    # user reloading forty times is one active user, not forty logins.
    day = func.date_trunc("day", AuditLog.created_at).label("day")
    active_rows = (
        await db.execute(
            select(day, func.count(func.distinct(AuditLog.actor_user_id)))
            .where(AuditLog.created_at >= start, AuditLog.action == LOGIN_OK, AuditLog.actor_user_id.isnot(None))
            .group_by(day).order_by(day)
        )
    ).all()
    active_daily = _dense(active_rows, start, days)

    # ── the same measures over the previous window, for the deltas ───────
    async def prev_count(*where) -> int:
        return await _scalar(
            db,
            select(func.count()).select_from(AuditLog).where(
                AuditLog.created_at >= prev_start, AuditLog.created_at < start, *where
            ),
        )

    previous = {
        "signups": await _scalar(
            db,
            select(func.count()).select_from(User).where(User.created_at >= prev_start, User.created_at < start),
        ),
        "logins": await prev_count(AuditLog.action == LOGIN_OK),
        "failures": await prev_count(AuditLog.action.in_(LOGIN_BAD)),
        "active_users": await _scalar(
            db,
            select(func.count(func.distinct(AuditLog.actor_user_id))).where(
                AuditLog.created_at >= prev_start, AuditLog.created_at < start,
                AuditLog.action == LOGIN_OK, AuditLog.actor_user_id.isnot(None),
            ),
        ),
        "admin_actions": await prev_count(AuditLog.action.notin_((LOGIN_OK, *LOGIN_BAD, "logout"))),
    }

    # ── when the estate is actually used: weekday × hour ────────────────
    dow = cast(func.extract("dow", AuditLog.created_at), Integer).label("dow")
    hour = cast(func.extract("hour", AuditLog.created_at), Integer).label("hour")
    heat_rows = (
        await db.execute(
            select(dow, hour, func.count()).where(AuditLog.created_at >= start).group_by(dow, hour)
        )
    ).all()
    heatmap = [{"dow": int(d), "hour": int(h), "v": int(c)} for d, h, c in heat_rows]

    # ── composition ──────────────────────────────────────────────────────
    action_rows = (
        await db.execute(
            select(AuditLog.action, func.count())
            .where(AuditLog.created_at >= start)
            .group_by(AuditLog.action).order_by(func.count().desc())
        )
    ).all()

    actor_rows = (
        await db.execute(
            select(AuditLog.actor_user_id, func.count())
            .where(AuditLog.created_at >= start, AuditLog.actor_user_id.isnot(None),
                   AuditLog.action.notin_((LOGIN_OK, *LOGIN_BAD, "logout")))
            .group_by(AuditLog.actor_user_id).order_by(func.count().desc()).limit(8)
        )
    ).all()
    emails = {u.id: u.email for u in (await db.execute(select(User))).scalars()}

    # Failed sign-ins grouped by source. Concentration is the signal: fifty
    # failures from fifty addresses is a bad week, fifty from one address is
    # someone working through a password list.
    ip_rows = (
        await db.execute(
            select(AuditLog.ip, func.count(), func.count(func.distinct(AuditLog.target)))
            .where(AuditLog.created_at >= start, AuditLog.action.in_(LOGIN_BAD), AuditLog.ip.isnot(None))
            .group_by(AuditLog.ip).order_by(func.count().desc()).limit(10)
        )
    ).all()

    # ── how recently each account was seen ───────────────────────────────
    def seen_since(delta: timedelta | None):
        stmt = select(func.count()).select_from(User)
        if delta is None:
            return stmt.where(User.last_login_at.is_(None))
        return stmt.where(User.last_login_at >= now - delta)

    recency = {
        "day": await _scalar(db, seen_since(timedelta(days=1))),
        "week": await _scalar(db, seen_since(timedelta(days=7))),
        "month": await _scalar(db, seen_since(timedelta(days=30))),
        "quarter": await _scalar(db, seen_since(timedelta(days=90))),
        "never": await _scalar(db, seen_since(None)),
        "total": users_total,
    }

    # ── per-platform rollup ──────────────────────────────────────────────
    platforms = (await db.execute(select(Platform).order_by(Platform.slug))).scalars().all()
    plans = {p.id: p for p in (await db.execute(select(Plan))).scalars()}
    subs = (await db.execute(select(Subscription))).scalars().all()
    roles = {r.id: r for r in (await db.execute(select(Role))).scalars()}
    memberships = (await db.execute(select(Membership))).scalars().all()
    last_login = {
        u_id: ts
        for u_id, ts in (await db.execute(select(User.id, User.last_login_at))).all()
    }

    per_platform = []
    plan_mix: list[dict] = []
    estate_mrr = 0.0
    for p in platforms:
        p_members = [m for m in memberships if m.platform_id == p.id]
        p_subs = [s for s in subs if s.platform_id == p.id]
        active_30 = sum(
            1 for m in p_members
            if (ts := last_login.get(m.user_id)) is not None and ts >= now - timedelta(days=30)
        )
        mrr = 0.0
        by_plan: dict[str, int] = {}
        for s in p_subs:
            plan = plans.get(s.plan_id)
            if plan is None:
                continue
            by_plan[plan.slug] = by_plan.get(plan.slug, 0) + 1
            if s.status == "active":
                mrr += _monthly_value(plan.price_inr, plan.interval)
        estate_mrr += mrr

        role_mix: dict[str, int] = {}
        for m in p_members:
            role = roles.get(m.role_id)
            role_mix[role.slug if role else "unknown"] = role_mix.get(role.slug if role else "unknown", 0) + 1

        for slug, count in sorted(by_plan.items(), key=lambda kv: -kv[1]):
            plan_mix.append({"platform": p.slug, "plan": slug, "count": count})

        per_platform.append({
            "slug": p.slug,
            "name": p.name,
            "is_active": p.is_active,
            "members": len(p_members),
            "active_30d": active_30,
            "subscriptions": len(p_subs),
            "paying": sum(1 for s in p_subs if s.status == "active" and plans.get(s.plan_id) and plans[s.plan_id].price_inr > 0),
            "mrr_inr": round(mrr),
            "roles": [{"role": k, "count": v} for k, v in sorted(role_mix.items(), key=lambda kv: -kv[1])],
            "plans": [{"plan": k, "count": v} for k, v in sorted(by_plan.items(), key=lambda kv: -kv[1])],
        })

    return {
        "window_days": days,
        "generated_at": now.isoformat(),
        "totals": {
            "users": users_total,
            "active_users": users_total - suspended,
            "suspended": suspended,
            "mfa_enabled": mfa_on,
            "superadmins": superadmins,
            "superadmins_without_mfa": superadmins_no_mfa,
            "platforms": len(platforms),
            "memberships": len(memberships),
            "subscriptions": len(subs),
            "clients": await _scalar(db, select(func.count()).select_from(OAuthClient)),
            "live_sessions": live_sessions,
            "mrr_inr": round(estate_mrr),
        },
        "series": {
            "signups": signups,
            "logins": logins,
            "failures": failures,
            "admin_actions": admin_actions,
            "active_users": active_daily,
        },
        "previous": previous,
        "heatmap": heatmap,
        "actions": [{"action": a, "count": int(c)} for a, c in action_rows],
        "top_actors": [
            {"actor": emails.get(uid, "unknown"), "count": int(c)} for uid, c in actor_rows
        ],
        "failure_sources": [
            {"ip": ip, "count": int(c), "accounts": int(t)} for ip, c, t in ip_rows
        ],
        "recency": recency,
        "mfa": {"enabled": mfa_on, "disabled": users_total - mfa_on},
        "platforms": per_platform,
        "plan_mix": plan_mix,
    }


@platform_router.get("/{slug}/analytics")
async def platform_analytics(
    slug: str,
    days: int = Query(30, ge=7, le=365),
    actor: Actor = Depends(current_actor),
    db: AsyncSession = Depends(get_db),
):
    platform = (await db.execute(select(Platform).where(Platform.slug == slug))).scalars().first()
    if platform is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such platform")
    await require_platform_rank(db, actor, platform.id, STAFF_RANK)

    start, prev_start, now = _window(days)

    joined = await _daily(db, Membership.created_at, Membership.platform_id == platform.id, start=start, days=days)
    prev_joined = await _scalar(
        db,
        select(func.count()).select_from(Membership).where(
            Membership.platform_id == platform.id,
            Membership.created_at >= prev_start, Membership.created_at < start,
        ),
    )

    members = (
        await db.execute(
            select(User, Role, Membership)
            .join(Membership, Membership.user_id == User.id)
            .join(Role, Role.id == Membership.role_id)
            .where(Membership.platform_id == platform.id)
        )
    ).all()
    plans = {p.id: p for p in (await db.execute(select(Plan).where(Plan.platform_id == platform.id))).scalars()}
    subs = {
        s.user_id: s
        for s in (await db.execute(select(Subscription).where(Subscription.platform_id == platform.id))).scalars()
    }

    role_mix: dict[str, int] = {}
    plan_counts: dict[str, int] = {}
    recency = {"day": 0, "week": 0, "month": 0, "quarter": 0, "never": 0, "total": len(members)}
    mfa_on = 0
    suspended = 0
    mrr = 0.0
    dormant: list[dict] = []

    for user, role, _membership in members:
        role_mix[role.slug] = role_mix.get(role.slug, 0) + 1
        if user.mfa_enabled:
            mfa_on += 1
        if user.status != "active":
            suspended += 1

        sub = subs.get(user.id)
        plan = plans.get(sub.plan_id) if sub else None
        plan_counts[plan.slug if plan else "none"] = plan_counts.get(plan.slug if plan else "none", 0) + 1
        if sub and plan and sub.status == "active":
            mrr += _monthly_value(plan.price_inr, plan.interval)

        seen = user.last_login_at
        if seen is None:
            recency["never"] += 1
        elif seen >= now - timedelta(days=1):
            recency["day"] += 1
        elif seen >= now - timedelta(days=7):
            recency["week"] += 1
        elif seen >= now - timedelta(days=30):
            recency["month"] += 1
        else:
            recency["quarter"] += 1

        # Paying and not showing up is the one cohort worth a name: it is the
        # renewal that is about to lapse, and it is actionable today.
        if plan and plan.price_inr > 0 and sub and sub.status == "active":
            if seen is None or seen < now - timedelta(days=30):
                dormant.append({
                    "email": user.email,
                    "plan": plan.slug,
                    "price_inr": plan.price_inr,
                    "last_login_at": seen.isoformat() if seen else None,
                })

    price_by_slug = {p.slug: p.price_inr for p in plans.values()}

    return {
        "window_days": days,
        "generated_at": now.isoformat(),
        "platform": {"slug": platform.slug, "name": platform.name},
        "totals": {
            "members": len(members),
            "suspended": suspended,
            "mfa_enabled": mfa_on,
            "paying": sum(
                1 for s in subs.values()
                if s.status == "active" and plans.get(s.plan_id) and plans[s.plan_id].price_inr > 0
            ),
            "mrr_inr": round(mrr),
            "at_risk": len(dormant),
        },
        "series": {"joined": joined},
        "previous": {"joined": prev_joined},
        "roles": [{"role": k, "count": v} for k, v in sorted(role_mix.items(), key=lambda kv: -kv[1])],
        "plans": [
            {"plan": k, "count": v, "price_inr": price_by_slug.get(k, 0)}
            for k, v in sorted(plan_counts.items(), key=lambda kv: -kv[1])
        ],
        "recency": recency,
        "at_risk": sorted(dormant, key=lambda r: -r["price_inr"])[:20],
    }
