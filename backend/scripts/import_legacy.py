"""One-shot import of the pre-SSO accounts into accounts.hynt.one.

Reads the three places identity used to live:
  * terminal      — MariaDB  gap_scanner.users        (pbkdf2 hashes)
  * xterminal     — SQLite   var/x_terminal.db users  (scrypt hashes)
  * intelligence  — Postgres market_intel.users       (scrypt hashes)

Password hashes are NOT carried across. They are in three different formats,
none of them argon2id, and re-hashing is impossible without the plaintext — so
each imported account gets a fresh generated password, printed once. That is
also the honest outcome: consolidating identity is exactly the moment to stop
three separately-aged credentials from continuing to exist.

Roles are mapped onto the central vocabulary; "owner" becomes admin, since the
estate's top authority is the superadmin flag, not a per-platform role.

Idempotent: an account that already exists is granted, not recreated.
"""
import asyncio
import secrets
import sqlite3
import subprocess
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db import SessionLocal
from app.models.identity import User
from app.models.rbac import Platform
from app.services import provisioning

ROLE_MAP = {"owner": "admin", "admin": "admin", "staff": "staff", "user": "user", "member": "user"}


def from_mariadb() -> list[dict]:
    try:
        out = subprocess.run(
            ["mysql", "-N", "-B", "-e", "select email, name, role from users", "gap_scanner"],
            capture_output=True, text=True, check=True,
        ).stdout
    except Exception as exc:
        print(f"  terminal: skipped ({exc})")
        return []
    rows = []
    for line in out.strip().splitlines():
        email, name, role = (line.split("\t") + ["", ""])[:3]
        rows.append({"email": email, "name": None if name == "NULL" else name, "role": role, "platform": "terminal"})
    return rows


def from_sqlite(path: str) -> list[dict]:
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return [
            {"email": r["email"], "name": r["name"], "role": r["role"], "platform": "xterminal"}
            for r in conn.execute("select email, name, role from users")
        ]
    except Exception as exc:
        print(f"  xterminal: skipped ({exc})")
        return []


def from_postgres() -> list[dict]:
    try:
        out = subprocess.run(
            ["sudo", "-u", "postgres", "psql", "-d", "market_intel", "-t", "-A", "-F", "\t",
             "-c", "select email, display_name, role from users where active"],
            capture_output=True, text=True, check=True,
        ).stdout
    except Exception as exc:
        print(f"  intelligence: skipped ({exc})")
        return []
    rows = []
    for line in out.strip().splitlines():
        if not line.strip():
            continue
        email, name, role = (line.split("\t") + ["", ""])[:3]
        rows.append({"email": email, "name": name, "role": role, "platform": "intelligence"})
    return rows


async def main(dry_run: bool, skip_local: bool):
    legacy = from_mariadb() + from_sqlite("/opt/xterminal.hynt.one/backend/var/x_terminal.db") + from_postgres()

    if skip_local:
        # ".local" addresses are placeholder desk logins, not people. Importing
        # one creates an account nobody can receive a password for.
        legacy = [r for r in legacy if not r["email"].endswith(".local")]

    # One person may exist in several databases; merge into one account and keep
    # every membership.
    merged: dict[str, dict] = {}
    for row in legacy:
        entry = merged.setdefault(row["email"].strip().lower(), {"name": None, "grants": []})
        entry["name"] = entry["name"] or row["name"]
        entry["grants"].append((row["platform"], ROLE_MAP.get((row["role"] or "user").lower(), "user")))

    print(f"\n{len(merged)} account(s) to import:")
    for email, entry in merged.items():
        grants = ", ".join(f"{p}:{r}" for p, r in entry["grants"])
        print(f"  {email:34s} {entry['name'] or '':22s} {grants}")

    if dry_run:
        print("\n--dry-run: nothing written.")
        return

    async with SessionLocal() as db:
        platforms = {p.slug: p for p in (await db.execute(select(Platform))).scalars()}
        print()
        for email, entry in merged.items():
            user = (await db.execute(select(User).where(User.email == email))).scalars().first()
            password = None
            if user is None:
                password = secrets.token_urlsafe(15)
                user = User(email=email, full_name=entry["name"], password_hash=hash_password(password))
                db.add(user)
                await db.commit()
                await db.refresh(user)

            for platform_slug, role in entry["grants"]:
                platform = platforms.get(platform_slug)
                if platform is None:
                    continue
                # Admins get the top plan; everyone else the platform default.
                await provisioning.grant(
                    db, user_id=user.id, platform=platform, role_slug=role,
                    plan_slug="pro" if role == "admin" else None,
                )

            print(f"{email}")
            print(f"  password: {password if password else '(unchanged — account already existed)'}")


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv, "--include-local" not in sys.argv))
