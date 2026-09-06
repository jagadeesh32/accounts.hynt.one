"""Retire the local password credentials now that accounts.hynt.one owns identity.

WHAT THIS REMOVES: password hashes and password-reset tokens, in all three
legacy stores.

WHAT THIS KEEPS, deliberately: the row, its id, and its email.
  * The id is referenced by real data — terminal's positions, alerts, screener
    presets and mcp_keys, and intelligence's notes.author_id. Deleting the row
    orphans all of it.
  * The email is how the SSO layer finds the existing row on first sign-in
    (see terminal's app/auth/sso.py: link_user matches on email before it
    creates anything). Clear the email and every returning user silently gets a
    brand-new local row with none of their history attached.

The hash is replaced with the sentinel "!sso" rather than emptied: it is not a
valid pbkdf2/scrypt/argon2 string, so every verifier refuses it, and it reads
unambiguously in a dump as "this account authenticates elsewhere" instead of
looking like corruption.
"""
import os
import re
import pathlib
import sqlite3
import subprocess
import sys

SENTINEL = "!sso"


def run(argv: list[str], **kw) -> str:
    return subprocess.run(argv, capture_output=True, text=True, check=True, **kw).stdout


def strip_terminal(dry: bool) -> None:
    before = run(["mysql", "-N", "-B", "-e",
                  f"select count(*) from users where password_hash <> '{SENTINEL}'", "gap_scanner"]).strip()
    print(f"terminal (mariadb gap_scanner.users): {before} row(s) with a local password")
    if dry:
        return
    run(["mysql", "-e",
         f"update users set password_hash='{SENTINEL}', reset_token_hash=NULL, reset_expires=NULL", "gap_scanner"])
    print("  -> hashes and reset tokens cleared")


def xterminal_db_path() -> str:
    """Resolve the SQLite file X-Terminal actually opens.

    Not the copy sitting in the checkout: XT_STATE_DIR in its .env points the
    live database somewhere else entirely (/opt/x_terminal/backend/var), and the
    file in the repo tree is a stale leftover. Writing to the wrong one succeeds
    silently and changes nothing that runs.
    """
    env = pathlib.Path("/opt/xterminal.hynt.one/backend/.env")
    state_dir = ""
    if env.exists():
        for line in env.read_text().splitlines():
            match = re.match(r"\s*XT_SQLITE_PATH\s*=\s*(\S+)", line)
            if match:
                return match.group(1)
            match = re.match(r"\s*XT_STATE_DIR\s*=\s*(\S+)", line)
            if match:
                state_dir = match.group(1)
    if state_dir:
        return os.path.join(state_dir, "x_terminal.db")
    return "/opt/xterminal.hynt.one/backend/var/x_terminal.db"


def strip_xterminal(dry: bool, path: str) -> None:
    conn = sqlite3.connect(path)
    n = conn.execute("select count(*) from users where password_hash <> ?", (SENTINEL,)).fetchone()[0]
    print(f"xterminal (sqlite {path}): {n} row(s) with a local password")
    if dry:
        conn.close()
        return
    # token_version is bumped so anything this app issued locally stops verifying.
    conn.execute("update users set password_hash=?, token_version=token_version+1", (SENTINEL,))
    conn.commit()
    conn.close()
    print("  -> hashes cleared, token_version bumped")


def strip_intelligence(dry: bool) -> None:
    out = run(["sudo", "-u", "postgres", "psql", "-d", "market_intel", "-t", "-A", "-c",
               f"select count(*) from users where password_hash <> '{SENTINEL}'"]).strip()
    print(f"intelligence (postgres market_intel.users): {out} row(s) with a local password")
    if dry:
        return
    run(["sudo", "-u", "postgres", "psql", "-d", "market_intel", "-c",
         f"update users set password_hash='{SENTINEL}', updated_at=now()"])
    print("  -> hashes cleared")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    print("DRY RUN — nothing will be written.\n" if dry else "")
    strip_terminal(dry)
    strip_xterminal(dry, xterminal_db_path())
    strip_intelligence(dry)
    if not dry:
        print("\nLocal password login is now impossible in all three. "
              "Sign-in goes through accounts.hynt.one.")
