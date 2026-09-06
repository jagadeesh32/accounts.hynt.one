"""Operational CLI for accounts.hynt.one.

    python -m scripts.manage bootstrap          # platforms, roles, plans, clients, superadmin
    python -m scripts.manage create-user  --email a@b.c --role admin --platform terminal
    python -m scripts.manage grant        --email a@b.c --platform terminal --role staff
    python -m scripts.manage passwd       --email a@b.c
    python -m scripts.manage list-clients
    python -m scripts.manage rotate-key
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app import config  # noqa: E402
from app.core import keys  # noqa: E402
from app.core.security import hash_password, new_secret  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import (  # noqa: E402
    Membership,
    OAuthClient,
    Permission,
    Plan,
    Platform,
    Role,
    RolePermission,
    User,
    UserStatus,
)
from app.services import provisioning  # noqa: E402

# --------------------------------------------------------------------------- #
#  Seed definitions
# --------------------------------------------------------------------------- #
# The three existing platforms. Redirect URIs list both the production origin and
# the Vite dev server, because a developer who has to edit the database to run
# the app locally will eventually edit production instead.
PLATFORMS = [
    {
        "slug": "terminal",
        "name": "Hynt Terminal",
        "description": "Equity screening, scanners and the trading desk.",
        "base_url": "https://terminal.hynt.one",
        "icon": "terminal",
        "sort_order": 10,
        "origins": ["https://terminal.hynt.one", "http://localhost:5174"],
        "permissions": [
            ("terminal:scanner.run", "Run scanners and screeners"),
            ("terminal:scanner.configure", "Change scanner parameters and presets"),
            ("terminal:positions.read", "View positions and P&L"),
            ("terminal:positions.write", "Sync and edit positions"),
            ("terminal:broker.manage", "Connect and control broker sessions"),
            ("terminal:users.manage", "Manage terminal users and roles"),
            ("terminal:mcp.keys", "Issue and revoke MCP API keys"),
        ],
        "roles": {
            "admin": ["terminal:scanner.run", "terminal:scanner.configure",
                      "terminal:positions.read", "terminal:positions.write",
                      "terminal:broker.manage", "terminal:users.manage", "terminal:mcp.keys"],
            "staff": ["terminal:scanner.run", "terminal:scanner.configure",
                      "terminal:positions.read", "terminal:positions.write"],
            "user": ["terminal:scanner.run", "terminal:positions.read"],
        },
        "plans": [
            {"code": "free", "name": "Free", "price_cents": 0, "is_default": True,
             "sort_order": 10,
             "description": "Daily scans on a delayed feed.",
             "features": ["End-of-day scans", "3 saved screeners", "Community support"],
             "limits": {"scans_per_day": 25, "saved_screeners": 3, "history_days": 90},
             "entitlements": []},
            {"code": "pro", "name": "Pro", "price_cents": 199000, "sort_order": 20,
             "trial_days": 14,
             "description": "Intraday scanning and the full screener suite.",
             "features": ["Intraday scans", "Unlimited screeners", "SMC + Lorentz engines",
                          "Position sync", "Email support"],
             "limits": {"scans_per_day": 1000, "saved_screeners": 100, "history_days": 1825},
             "entitlements": ["terminal.intraday", "terminal.smc", "terminal.lorentz",
                              "terminal.position_sync"]},
            {"code": "desk", "name": "Desk", "price_cents": 599000, "sort_order": 30,
             "description": "Multi-seat desk with broker automation and MCP access.",
             "features": ["Everything in Pro", "Broker automation", "MCP API keys",
                          "Priority support"],
             "limits": {"scans_per_day": 10000, "saved_screeners": 1000, "history_days": 3650},
             "entitlements": ["terminal.intraday", "terminal.smc", "terminal.lorentz",
                              "terminal.position_sync", "terminal.broker_automation",
                              "terminal.mcp"]},
        ],
    },
    {
        "slug": "xterminal",
        "name": "Hynt X-Terminal",
        "description": "Index derivatives desk — option chain, OI velocity and alerts.",
        "base_url": "https://xterminal.hynt.one",
        "icon": "activity",
        "sort_order": 20,
        "origins": ["https://xterminal.hynt.one", "http://localhost:5175"],
        "permissions": [
            ("xterminal:board.read", "View option boards and the live feed"),
            ("xterminal:alerts.manage", "Create and edit alerts"),
            ("xterminal:feed.control", "Start and stop the broker feed"),
            ("xterminal:users.manage", "Manage x-terminal users and roles"),
        ],
        "roles": {
            "admin": ["xterminal:board.read", "xterminal:alerts.manage",
                      "xterminal:feed.control", "xterminal:users.manage"],
            "staff": ["xterminal:board.read", "xterminal:alerts.manage"],
            "user": ["xterminal:board.read"],
        },
        "plans": [
            {"code": "free", "name": "Free", "price_cents": 0, "is_default": True,
             "sort_order": 10,
             "description": "Delayed option chain, one index.",
             "features": ["Delayed chain", "1 index", "5 alerts"],
             "limits": {"indices": 1, "alerts": 5, "refresh_seconds": 60},
             "entitlements": []},
            {"code": "pro", "name": "Pro", "price_cents": 299000, "sort_order": 20,
             "trial_days": 7,
             "description": "Live feed across every index, with OI velocity.",
             "features": ["Live tick feed", "All indices", "OI velocity", "Unlimited alerts"],
             "limits": {"indices": 10, "alerts": 500, "refresh_seconds": 1},
             "entitlements": ["xterminal.live_feed", "xterminal.oi_velocity",
                              "xterminal.all_indices"]},
        ],
    },
    {
        "slug": "intelligence",
        "name": "Hynt Intelligence",
        "description": "Market intelligence — documents, entities and analytics.",
        "base_url": "https://intelligence.hynt.one",
        "icon": "brain",
        "sort_order": 30,
        "origins": ["https://intelligence.hynt.one", "http://localhost:5176"],
        "permissions": [
            ("intelligence:documents.read", "Read ingested documents"),
            ("intelligence:documents.write", "Upload and edit documents"),
            ("intelligence:connectors.manage", "Configure and backfill connectors"),
            ("intelligence:entities.merge", "Merge and remap entities"),
            ("intelligence:analytics.read", "View analytics dashboards"),
            ("intelligence:users.manage", "Manage intelligence users and roles"),
        ],
        "roles": {
            "admin": ["intelligence:documents.read", "intelligence:documents.write",
                      "intelligence:connectors.manage", "intelligence:entities.merge",
                      "intelligence:analytics.read", "intelligence:users.manage"],
            "staff": ["intelligence:documents.read", "intelligence:documents.write",
                      "intelligence:analytics.read"],
            "user": ["intelligence:documents.read", "intelligence:analytics.read"],
        },
        "plans": [
            {"code": "free", "name": "Free", "price_cents": 0, "is_default": True,
             "sort_order": 10,
             "description": "Read-only access to the shared corpus.",
             "features": ["Read documents", "Basic analytics", "100 queries a day"],
             "limits": {"queries_per_day": 100, "documents": 500, "connectors": 0},
             "entitlements": []},
            {"code": "team", "name": "Team", "price_cents": 499000, "sort_order": 20,
             "trial_days": 14,
             "description": "Your own connectors, entity graph and LLM summarisation.",
             "features": ["Private connectors", "Entity graph", "LLM summaries",
                          "Unlimited queries"],
             "limits": {"queries_per_day": 100000, "documents": 100000, "connectors": 25},
             "entitlements": ["intelligence.connectors", "intelligence.entity_graph",
                              "intelligence.llm"]},
        ],
    },
]


def _seed_platform(db, spec: dict) -> Platform:
    platform = db.scalar(select(Platform).where(Platform.slug == spec["slug"]))
    if platform is None:
        platform = Platform(slug=spec["slug"])
        db.add(platform)
    platform.name = spec["name"]
    platform.description = spec["description"]
    platform.base_url = spec["base_url"]
    platform.icon = spec["icon"]
    platform.sort_order = spec["sort_order"]
    platform.active = True
    db.flush()

    # Permissions
    perms: dict[str, Permission] = {}
    for code, description in spec["permissions"]:
        perm = db.scalar(select(Permission).where(Permission.code == code))
        if perm is None:
            perm = Permission(code=code, description=description)
            db.add(perm)
            db.flush()
        else:
            perm.description = description
        perms[code] = perm

    # Roles, and the permission bundle behind each. Re-seeding is idempotent:
    # role permissions are recomputed so tightening a role in this file actually
    # takes effect on the next bootstrap.
    for role_spec in provisioning.default_roles_for_platform(platform.id):
        role = db.scalar(
            select(Role).where(Role.platform_id == platform.id, Role.code == role_spec["code"])
        )
        if role is None:
            role = Role(platform_id=platform.id, **role_spec)
            db.add(role)
            db.flush()
        else:
            role.name = role_spec["name"]
            role.rank = role_spec["rank"]
            role.is_default = role_spec["is_default"]
            role.description = role_spec["description"]

        wanted = set(spec["roles"].get(role.code, []))
        current = {rp.permission.code: rp for rp in role.permissions}
        for code in wanted - set(current):
            db.add(RolePermission(role_id=role.id, permission_id=perms[code].id))
        for code in set(current) - wanted:
            db.delete(current[code])
        db.flush()

    # Plans
    for plan_spec in spec["plans"]:
        plan = db.scalar(
            select(Plan).where(Plan.platform_id == platform.id, Plan.code == plan_spec["code"])
        )
        if plan is None:
            plan = Plan(platform_id=platform.id, code=plan_spec["code"])
            db.add(plan)
        plan.name = plan_spec["name"]
        plan.description = plan_spec.get("description", "")
        plan.price_cents = plan_spec["price_cents"]
        plan.currency = plan_spec.get("currency", "INR")
        plan.interval = plan_spec.get("interval", "monthly")
        plan.trial_days = plan_spec.get("trial_days", 0)
        plan.features = plan_spec.get("features", [])
        plan.limits = plan_spec.get("limits", {})
        plan.entitlements = plan_spec.get("entitlements", [])
        plan.is_default = plan_spec.get("is_default", False)
        plan.sort_order = plan_spec.get("sort_order", 0)
        plan.active = True
        db.flush()

    # The SPA's OAuth client. Public (no secret) — a secret shipped in a browser
    # bundle is not a secret — so PKCE is what actually authenticates it.
    client_id = f"{spec['slug']}-web"
    client = db.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))
    if client is None:
        client = OAuthClient(client_id=client_id, platform_id=platform.id)
        db.add(client)
    client.name = f"{spec['name']} (web)"
    client.platform_id = platform.id
    client.is_public = True
    client.client_secret_hash = None
    client.redirect_uris = [f"{origin}/auth/callback" for origin in spec["origins"]]
    client.post_logout_redirect_uris = [f"{origin}/" for origin in spec["origins"]]
    client.scopes = ["openid", "profile", "email"]
    client.trusted = True
    client.active = True
    db.flush()

    return platform


def cmd_bootstrap(args) -> int:
    """Seed platforms, roles, permissions, plans, clients — and the superadmin."""
    from app import config

    with session_scope() as db:
        keys.ensure_key(db)

        for spec in PLATFORMS:
            platform = _seed_platform(db, spec)
            print(f"  platform  {platform.slug:<14} roles+plans+client seeded")

        email = (args.email or config.BOOTSTRAP_EMAIL).strip().lower()
        user = db.scalar(select(User).where(User.email == email))

        if user is None:
            password = args.password or config.BOOTSTRAP_PASSWORD or new_secret(12)
            generated = not (args.password or config.BOOTSTRAP_PASSWORD)
            user = provisioning.create_user_account(
                db, email=email, password=password, full_name=args.name or "Superadmin",
                is_superadmin=True,
            )
            # Give the superadmin the top role on every platform explicitly, so
            # the admin console reflects reality rather than relying on the
            # is_superadmin bypass alone.
            for spec in PLATFORMS:
                platform = db.scalar(select(Platform).where(Platform.slug == spec["slug"]))
                role = provisioning.role_for(db, platform, "admin")
                provisioning.grant_membership(db, user, platform, role)

            print(f"\n  superadmin {email}")
            if generated:
                print(f"  password   {password}")
                print("  ^ shown once — change it after signing in.")
        else:
            if not user.is_superadmin:
                user.is_superadmin = True
                print(f"  superadmin {email} (promoted)")
            else:
                print(f"  superadmin {email} (already present)")

    print("\nbootstrap complete")
    return 0


def cmd_create_user(args) -> int:
    from datetime import datetime, timedelta, timezone

    from app.core.security import token_digest
    from app.models import PasswordReset

    with session_scope() as db:
        email = args.email.strip().lower()
        if db.scalar(select(User).where(User.email == email)) is not None:
            print(f"error: {email} already exists", file=sys.stderr)
            return 1

        # --invite creates the account with no usable password and issues a
        # single-use activation link. That is the right way to onboard someone
        # during the cutover: an administrator typing a password and sending it
        # over chat is a worse secret than no secret at all.
        if args.invite:
            password = None
        else:
            password = args.password or getpass.getpass("password: ")

        user = provisioning.create_user_account(
            db, email=email, password=password, full_name=args.name or "",
            is_superadmin=args.superadmin,
        )

        if args.invite:
            raw = new_secret(32)
            now = datetime.now(timezone.utc)
            db.add(
                PasswordReset(
                    user_id=user.id,
                    token_hash=token_digest(raw),
                    # Longer than a self-service reset: an invitation may sit in
                    # an inbox over a weekend before anyone opens it.
                    expires_at=now + timedelta(days=7),
                    created_at=now,
                )
            )
            print(f"created {email} (pending activation)")
            print(f"\n  activation link (valid 7 days, single use):")
            print(f"  {config.ACCOUNT_APP_URL.rstrip('/')}/reset-password?token={raw}\n")

        if args.platform:
            platform = db.scalar(select(Platform).where(Platform.slug == args.platform))
            if platform is None:
                print(f"error: unknown platform {args.platform}", file=sys.stderr)
                return 1
            role = provisioning.role_for(db, platform, args.role or "user")
            if role is None:
                print(f"error: unknown role {args.role}", file=sys.stderr)
                return 1
            provisioning.grant_membership(db, user, platform, role)

        if not args.invite:
            print(f"created {email} ({'superadmin' if args.superadmin else 'user'})")
    return 0


def cmd_grant(args) -> int:
    with session_scope() as db:
        user = db.scalar(select(User).where(User.email == args.email.strip().lower()))
        if user is None:
            print(f"error: no user {args.email}", file=sys.stderr)
            return 1
        platform = db.scalar(select(Platform).where(Platform.slug == args.platform))
        if platform is None:
            print(f"error: unknown platform {args.platform}", file=sys.stderr)
            return 1
        role = provisioning.role_for(db, platform, args.role)
        if role is None:
            print(f"error: unknown role {args.role} on {args.platform}", file=sys.stderr)
            return 1
        provisioning.grant_membership(db, user, platform, role)
        print(f"{args.email} is now {args.role} on {args.platform}")
    return 0


def cmd_passwd(args) -> int:
    with session_scope() as db:
        user = db.scalar(select(User).where(User.email == args.email.strip().lower()))
        if user is None:
            print(f"error: no user {args.email}", file=sys.stderr)
            return 1
        password = args.password or getpass.getpass("new password: ")
        if len(password) < 10:
            print("error: password must be at least 10 characters", file=sys.stderr)
            return 1
        user.password_hash = hash_password(password)
        # Every token and session minted under the old password stops working.
        user.token_version += 1
        from app.core import sessions

        revoked = sessions.revoke_all_for_user(db, user.id)

        # An invited account is PENDING until it has a password. Setting one for
        # it here is exactly the activation it was waiting for, so leaving it
        # PENDING would mean the operator sets a password and the user still
        # cannot sign in.
        activated = False
        if user.status == UserStatus.PENDING:
            user.status = UserStatus.ACTIVE
            activated = True

        print(f"password updated for {args.email} ({revoked} session(s) ended)")
        if activated:
            print("account activated (was pending)")
    return 0


def cmd_list_clients(args) -> int:
    with session_scope() as db:
        for client in db.scalars(select(OAuthClient).order_by(OAuthClient.client_id)):
            print(f"{client.client_id:<20} {client.platform.slug:<14} "
                  f"{'public' if client.is_public else 'confidential':<13} "
                  f"{'active' if client.active else 'disabled'}")
            for uri in client.redirect_uris:
                print(f"    → {uri}")
    return 0


def cmd_rotate_key(args) -> int:
    with session_scope() as db:
        key = keys.rotate(db)
        print(f"new signing key {key.kid}")
        print("previous public keys stay published until their tokens expire")
    return 0


def cmd_show_jwks(args) -> int:
    with session_scope() as db:
        print(json.dumps(keys.jwks(db), indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="manage", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("bootstrap", help="seed platforms, roles, plans, clients, superadmin")
    p.add_argument("--email")
    p.add_argument("--password")
    p.add_argument("--name")
    p.set_defaults(func=cmd_bootstrap)

    p = sub.add_parser("create-user")
    p.add_argument("--email", required=True)
    p.add_argument("--password")
    p.add_argument("--name")
    p.add_argument("--superadmin", action="store_true")
    p.add_argument("--invite", action="store_true",
                   help="create without a password and print a 7-day activation link")
    p.add_argument("--platform")
    p.add_argument("--role")
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("grant", help="grant a role on a platform")
    p.add_argument("--email", required=True)
    p.add_argument("--platform", required=True)
    p.add_argument("--role", required=True)
    p.set_defaults(func=cmd_grant)

    p = sub.add_parser("passwd")
    p.add_argument("--email", required=True)
    p.add_argument("--password")
    p.set_defaults(func=cmd_passwd)

    sub.add_parser("list-clients").set_defaults(func=cmd_list_clients)
    sub.add_parser("rotate-key").set_defaults(func=cmd_rotate_key)
    sub.add_parser("jwks").set_defaults(func=cmd_show_jwks)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
