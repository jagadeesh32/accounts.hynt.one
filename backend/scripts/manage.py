"""Operator CLI. `python -m scripts.manage <command>` from backend/.

bootstrap is idempotent by design: the role, permission and plan definitions
below are the source of truth, so tightening a role here and re-running is the
supported way to change it.
"""
import argparse
import asyncio
import getpass
import json
import secrets
import sys

from sqlalchemy import delete, select

from app.core.keys import get_active_key, jwks as build_jwks, rotate_key
from app.core.security import hash_password, password_problem
from app.core.sessions import revoke_all_sessions
from app.db import SessionLocal
from app.models.billing import Plan
from app.models.identity import User
from app.models.oauth import OAuthClient, Revocation
from app.models.rbac import Platform, Role
from app.services import provisioning, revocation

# --------------------------------------------------------------------------
# The estate, as seeded. Editing these and re-running `bootstrap` re-applies.
# --------------------------------------------------------------------------

PLATFORMS = [
    {
        "slug": "terminal",
        "name": "Hynt Terminal",
        "base_url": "https://terminal.hynt.one",
        "description": "Live market terminal — scanners, brokers, charting.",
        "icon": "📈",
    },
    {
        "slug": "xterminal",
        "name": "Hynt X-Terminal",
        "base_url": "https://xterminal.hynt.one",
        "description": "The execution desk.",
        "icon": "⚡",
    },
    {
        "slug": "intelligence",
        "name": "Hynt Intelligence",
        "base_url": "https://intelligence.hynt.one",
        "description": "Market intelligence, documents and research.",
        "icon": "🧠",
    },
]

# Permissions are namespaced by platform so a token's `perms` list is
# unambiguous even though a user may hold roles on several platforms.
ROLES = {
    "terminal": [
        ("admin", "Administrator", 30, [
            "terminal:scanner.run", "terminal:broker.manage", "terminal:positions.sync",
            "terminal:alerts.manage", "terminal:members.manage", "terminal:billing.manage",
        ]),
        ("staff", "Staff", 20, [
            "terminal:scanner.run", "terminal:broker.manage", "terminal:positions.sync",
            "terminal:alerts.manage",
        ]),
        ("user", "Member", 10, ["terminal:scanner.run", "terminal:alerts.manage"]),
    ],
    "xterminal": [
        ("admin", "Administrator", 30, [
            "xterminal:orders.place", "xterminal:strategies.manage",
            "xterminal:members.manage", "xterminal:billing.manage",
        ]),
        ("staff", "Staff", 20, ["xterminal:orders.place", "xterminal:strategies.manage"]),
        ("user", "Member", 10, ["xterminal:orders.place"]),
    ],
    "intelligence": [
        ("admin", "Administrator", 30, [
            "intelligence:documents.manage", "intelligence:entities.manage",
            "intelligence:members.manage", "intelligence:billing.manage",
        ]),
        ("staff", "Staff", 20, ["intelligence:documents.manage", "intelligence:entities.manage"]),
        ("user", "Member", 10, ["intelligence:documents.read"]),
    ],
}

PLANS = {
    "terminal": [
        ("free", "Free", 0, ["terminal.eod"], {"scans_per_day": 25, "alerts": 5}, True),
        ("pro", "Pro", 1499, ["terminal.eod", "terminal.intraday", "terminal.smc"],
         {"scans_per_day": 1000, "alerts": 200}, False),
    ],
    "xterminal": [
        ("free", "Free", 0, [], {"orders_per_day": 10}, True),
        ("pro", "Pro", 2499, ["xterminal.algo", "xterminal.basket"], {"orders_per_day": 1000}, False),
    ],
    "intelligence": [
        ("free", "Free", 0, ["intelligence.search"], {"queries_per_day": 50}, True),
        ("pro", "Pro", 1999, ["intelligence.search", "intelligence.llm", "intelligence.export"],
         {"queries_per_day": 2000}, False),
    ],
}

# One public SPA client per platform. Localhost URIs are registered so the dev
# servers work against production accounts without a second client per box.
CLIENTS = [
    ("terminal-web", "Hynt Terminal (web)", "terminal", [
        "https://terminal.hynt.one/auth/callback",
        "http://localhost:5173/auth/callback",
        "http://localhost:5170/auth/callback",
    ]),
    ("xterminal-web", "Hynt X-Terminal (web)", "xterminal", [
        "https://xterminal.hynt.one/auth/callback",
        "http://localhost:5174/auth/callback",
    ]),
    ("intelligence-web", "Hynt Intelligence (web)", "intelligence", [
        "https://intelligence.hynt.one/auth/callback",
        "http://localhost:5175/auth/callback",
    ]),
]


async def cmd_bootstrap(args):
    async with SessionLocal() as db:
        for spec in PLATFORMS:
            platform = (await db.execute(select(Platform).where(Platform.slug == spec["slug"]))).scalars().first()
            if platform is None:
                platform = Platform(slug=spec["slug"])
                db.add(platform)
            platform.name = spec["name"]
            platform.base_url = spec["base_url"]
            platform.description = spec["description"]
            platform.icon = spec["icon"]
            platform.is_active = True
        await db.commit()

        platforms = {p.slug: p for p in (await db.execute(select(Platform))).scalars()}

        for slug, roles in ROLES.items():
            platform = platforms[slug]
            for role_slug, name, rank, perms in roles:
                role = (
                    await db.execute(select(Role).where(Role.platform_id == platform.id, Role.slug == role_slug))
                ).scalars().first()
                if role is None:
                    role = Role(platform_id=platform.id, slug=role_slug)
                    db.add(role)
                role.name = name
                role.rank = rank
                role.permissions = perms
        await db.commit()

        for slug, plans in PLANS.items():
            platform = platforms[slug]
            for order, (plan_slug, name, price, ents, limits, is_default) in enumerate(plans):
                plan = (
                    await db.execute(select(Plan).where(Plan.platform_id == platform.id, Plan.slug == plan_slug))
                ).scalars().first()
                if plan is None:
                    plan = Plan(platform_id=platform.id, slug=plan_slug)
                    db.add(plan)
                plan.name = name
                plan.price_inr = price
                plan.entitlements = ents
                plan.limits = limits
                plan.is_default = is_default
                plan.sort_order = order
        await db.commit()

        for client_id, name, platform_slug, uris in CLIENTS:
            client = (await db.execute(select(OAuthClient).where(OAuthClient.client_id == client_id))).scalars().first()
            if client is None:
                client = OAuthClient(client_id=client_id)
                db.add(client)
            client.name = name
            client.platform_id = platforms[platform_slug].id
            client.redirect_uris = uris
            client.is_public = True
            client.is_active = True
        await db.commit()

        key = await get_active_key(db)

        email = (args.superadmin_email or "admin@hynt.one").strip().lower()
        user = (await db.execute(select(User).where(User.email == email))).scalars().first()
        password = None
        if user is None:
            password = secrets.token_urlsafe(15)
            user = User(
                email=email, full_name="Hynt Superadmin",
                password_hash=hash_password(password), is_superadmin=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        elif not user.is_superadmin:
            user.is_superadmin = True
            await db.commit()

        # The superadmin is a member of every platform on the top plan, or the
        # launcher would show the person who runs the estate no tiles at all.
        for platform in platforms.values():
            await provisioning.grant(db, user_id=user.id, platform=platform, role_slug="admin", plan_slug="pro")

        print(f"platforms   : {', '.join(sorted(platforms))}")
        print(f"clients     : {', '.join(c[0] for c in CLIENTS)}")
        print(f"signing kid : {key.kid}")
        print(f"superadmin  : {email}")
        if password:
            print(f"password    : {password}")
            print("              ^ shown once. Change it after first sign-in.")
        else:
            print("password    : (unchanged — account already existed)")


async def cmd_create_user(args):
    async with SessionLocal() as db:
        email = args.email.strip().lower()
        if (await db.execute(select(User).where(User.email == email))).scalars().first():
            sys.exit(f"{email} already exists")
        password = args.password or secrets.token_urlsafe(12)
        problem = password_problem(password)
        if problem:
            sys.exit(problem)
        user = User(email=email, full_name=args.name, password_hash=hash_password(password))
        db.add(user)
        await db.commit()
        await db.refresh(user)

        if args.platform:
            platform = (await db.execute(select(Platform).where(Platform.slug == args.platform))).scalars().first()
            if platform is None:
                sys.exit(f"no platform '{args.platform}'")
            await provisioning.grant(db, user_id=user.id, platform=platform, role_slug=args.role, plan_slug=args.plan)
        print(f"created {email}")
        if not args.password:
            print(f"password: {password}")


async def cmd_grant(args):
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == args.email.strip().lower()))).scalars().first()
        if user is None:
            sys.exit("no such user")
        platform = (await db.execute(select(Platform).where(Platform.slug == args.platform))).scalars().first()
        if platform is None:
            sys.exit("no such platform")
        await provisioning.grant(db, user_id=user.id, platform=platform, role_slug=args.role, plan_slug=args.plan)
        await revocation.revoke_user(db, user.id, reason="membership changed via CLI")
        print(f"{args.email} is now {args.role} on {args.platform}")


async def cmd_passwd(args):
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == args.email.strip().lower()))).scalars().first()
        if user is None:
            sys.exit("no such user")
        password = args.password or getpass.getpass("New password: ")
        problem = password_problem(password)
        if problem:
            sys.exit(problem)
        user.password_hash = hash_password(password)
        user.token_version += 1
        await db.commit()
        # Same rule as the console: a password change ends every session.
        count = await revoke_all_sessions(db, user.id)
        await revocation.revoke_user(db, user.id, reason="password changed via CLI")
        print(f"password changed; {count} session(s) ended")


async def cmd_suspend(args):
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == args.email.strip().lower()))).scalars().first()
        if user is None:
            sys.exit("no such user")
        user.status = "suspended" if not args.undo else "active"
        user.token_version += 1
        await db.commit()
        if not args.undo:
            await revoke_all_sessions(db, user.id)
            await revocation.revoke_user(db, user.id, reason="suspended via CLI")
        print(f"{user.email} is now {user.status}")


async def cmd_superadmin(args):
    """Grant or remove the estate-wide superadmin flag."""
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == args.email.strip().lower()))).scalars().first()
        if user is None:
            sys.exit("no such user")
        if args.remove:
            others = (
                await db.execute(select(User).where(User.is_superadmin.is_(True), User.id != user.id))
            ).scalars().all()
            if not others:
                # Removing the last one leaves nobody who can appoint another,
                # and this CLI is the only recovery path.
                sys.exit("refusing: that is the only superadmin")
        user.is_superadmin = not args.remove
        await db.commit()
        await revocation.revoke_user(db, user.id, reason="superadmin flag changed via CLI")
        print(f"{user.email} superadmin={user.is_superadmin}")


async def cmd_list_users(args):
    async with SessionLocal() as db:
        for user in (await db.execute(select(User).order_by(User.created_at))).scalars():
            tags = [f"{m.platform.slug}:{m.role.slug}" for m in user.memberships]
            flag = " [superadmin]" if user.is_superadmin else ""
            print(f"{user.email:40s} {user.status:10s} {' '.join(tags)}{flag}")


async def cmd_list_clients(args):
    async with SessionLocal() as db:
        platforms = {p.id: p.slug for p in (await db.execute(select(Platform))).scalars()}
        for client in (await db.execute(select(OAuthClient).order_by(OAuthClient.client_id))).scalars():
            print(f"{client.client_id:20s} {platforms.get(client.platform_id, '?'):14s} {', '.join(client.redirect_uris)}")


async def cmd_rotate_key(args):
    async with SessionLocal() as db:
        key = await rotate_key(db)
        print(f"new active kid: {key.kid}")
        print("the retired public key stays in the JWKS until its tokens expire")


async def cmd_jwks(args):
    async with SessionLocal() as db:
        print(json.dumps(await build_jwks(db), indent=2))


async def cmd_clear_revocations(args):
    """Lift a user-level revocation before it expires.

    `grant` and `passwd` revoke on every change so new permissions take effect
    at once, and platforms refuse anything on that list outright — newly minted
    tokens included. The account is therefore locked out of every platform for
    two token lifetimes, which is the wrong outcome when the change was meant to
    *give* someone access. This is the way back, for when the revocation was
    bookkeeping rather than a response to a compromise.
    """
    async with SessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.email == args.email.strip().lower())
        )).scalars().first()
        if user is None:
            sys.exit("no such user")
        result = await db.execute(
            delete(Revocation).where(
                Revocation.subject_type == "user",
                Revocation.subject_id == str(user.id),
            )
        )
        await db.commit()
        print(f"cleared {result.rowcount or 0} user-level revocation(s) for {args.email}")
        print("platforms pick this up on their next poll (~30s)")


async def cmd_prune(args):
    async with SessionLocal() as db:
        removed = await revocation.prune(db)
        print(f"pruned {removed} expired revocation(s)")


def main():
    parser = argparse.ArgumentParser(prog="manage", description="accounts.hynt.one operator CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("bootstrap", help="seed platforms, roles, plans, clients and the superadmin")
    p.add_argument("--superadmin-email", default="admin@hynt.one")
    p.set_defaults(fn=cmd_bootstrap)

    p = sub.add_parser("create-user")
    p.add_argument("--email", required=True)
    p.add_argument("--name")
    p.add_argument("--password")
    p.add_argument("--platform")
    p.add_argument("--role", default="user")
    p.add_argument("--plan")
    p.set_defaults(fn=cmd_create_user)

    p = sub.add_parser("grant", help="give a user a role on a platform")
    p.add_argument("--email", required=True)
    p.add_argument("--platform", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--plan")
    p.set_defaults(fn=cmd_grant)

    p = sub.add_parser("passwd", help="set a password; ends every session")
    p.add_argument("--email", required=True)
    p.add_argument("--password")
    p.set_defaults(fn=cmd_passwd)

    p = sub.add_parser("suspend")
    p.add_argument("--email", required=True)
    p.add_argument("--undo", action="store_true")
    p.set_defaults(fn=cmd_suspend)

    p = sub.add_parser("superadmin", help="grant or remove the estate-wide superadmin flag")
    p.add_argument("--email", required=True)
    p.add_argument("--remove", action="store_true")
    p.set_defaults(fn=cmd_superadmin)

    p = sub.add_parser("clear-revocations",
                       help="lift a user's revocation early (undoes grant/passwd lockout)")
    p.add_argument("--email", required=True)
    p.set_defaults(fn=cmd_clear_revocations)

    sub.add_parser("list-users").set_defaults(fn=cmd_list_users)
    sub.add_parser("list-clients").set_defaults(fn=cmd_list_clients)
    sub.add_parser("rotate-key").set_defaults(fn=cmd_rotate_key)
    sub.add_parser("jwks").set_defaults(fn=cmd_jwks)
    sub.add_parser("prune-revocations").set_defaults(fn=cmd_prune)

    args = parser.parse_args()
    asyncio.run(args.fn(args))


if __name__ == "__main__":
    main()
