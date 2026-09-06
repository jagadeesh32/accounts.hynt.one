"""Runtime configuration, read once at import.

Everything is environment-driven with development-safe defaults. The two values
that MUST be set in production are ``HYNT_DATABASE_URL`` and
``HYNT_COOKIE_DOMAIN``; the service refuses to start in production without a
usable signing key (see :mod:`app.core.keys`).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [item.strip() for item in _str(name, default).split(",") if item.strip()]


# --------------------------------------------------------------------------- #
#  Environment
# --------------------------------------------------------------------------- #
ENV = _str("HYNT_ENV", "development")
IS_PROD = ENV == "production"
DEBUG = _bool("HYNT_DEBUG", not IS_PROD)

HOST = _str("HYNT_HOST", "127.0.0.1")
PORT = _int("HYNT_PORT", 9000)
WORKERS = _int("HYNT_WORKERS", 1)

# Public origin of this service. Used to build the OIDC issuer, so it must match
# what the platforms have configured or every signature check will reject on
# `iss`.
ISSUER = _str("HYNT_ISSUER", "http://127.0.0.1:9000")

# --------------------------------------------------------------------------- #
#  Database
# --------------------------------------------------------------------------- #
DATABASE_URL = _str(
    "HYNT_DATABASE_URL",
    "postgresql+psycopg2://postgres@localhost:5432/hynt_accounts",
)
DB_POOL_SIZE = _int("HYNT_DB_POOL_SIZE", 10)
DB_MAX_OVERFLOW = _int("HYNT_DB_MAX_OVERFLOW", 20)
DB_ECHO = _bool("HYNT_DB_ECHO", False)

# --------------------------------------------------------------------------- #
#  SSO session cookie
# --------------------------------------------------------------------------- #
# One cookie, on the parent domain, holding an opaque session id. Deliberately
# *not* a JWT: this is the thing that must be revocable the instant a superadmin
# suspends an account, and an opaque id backed by a row is revocable by
# definition.
#
# Cello's Response stores headers in a HashMap, so a response can carry exactly
# one Set-Cookie. That constraint is why the design uses a single cookie and
# returns access tokens in the body rather than the usual access+refresh pair.
COOKIE_NAME = _str("HYNT_COOKIE_NAME", "hynt_sso")
COOKIE_DOMAIN = _str("HYNT_COOKIE_DOMAIN", "")  # e.g. ".hynt.one"; empty = host-only
COOKIE_SECURE = _bool("HYNT_COOKIE_SECURE", IS_PROD)
COOKIE_SAMESITE = _str("HYNT_COOKIE_SAMESITE", "Lax")

SESSION_TTL_SEC = _int("HYNT_SESSION_TTL_SEC", 30 * 24 * 3600)      # 30 days
SESSION_IDLE_TTL_SEC = _int("HYNT_SESSION_IDLE_TTL_SEC", 14 * 24 * 3600)

# --------------------------------------------------------------------------- #
#  Tokens
# --------------------------------------------------------------------------- #
# Short-lived by design. A platform that has been revoked keeps working for at
# most this long, which is the price of never calling back to verify.
ACCESS_TOKEN_TTL_SEC = _int("HYNT_ACCESS_TOKEN_TTL_SEC", 15 * 60)
ID_TOKEN_TTL_SEC = _int("HYNT_ID_TOKEN_TTL_SEC", 15 * 60)
REFRESH_TOKEN_TTL_SEC = _int("HYNT_REFRESH_TOKEN_TTL_SEC", 30 * 24 * 3600)
AUTH_CODE_TTL_SEC = _int("HYNT_AUTH_CODE_TTL_SEC", 60)
PASSWORD_RESET_TTL_SEC = _int("HYNT_PASSWORD_RESET_TTL_SEC", 30 * 60)

JWT_ALG = "RS256"

# --------------------------------------------------------------------------- #
#  CORS
# --------------------------------------------------------------------------- #
# Cello's CORS middleware cannot advertise Allow-Credentials from Python, which
# is fine and in fact enforces the design: no cross-origin request ever carries
# the SSO cookie. The token endpoint is authenticated by PKCE, not by cookie.
CORS_ORIGINS = _list(
    "HYNT_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,"
    "https://terminal.hynt.one,https://xterminal.hynt.one,https://intelligence.hynt.one",
)

# --------------------------------------------------------------------------- #
#  Registration & bootstrap
# --------------------------------------------------------------------------- #
ALLOW_SELF_REGISTRATION = _bool("HYNT_ALLOW_SELF_REGISTRATION", False)
BOOTSTRAP_EMAIL = _str("HYNT_BOOTSTRAP_EMAIL", "admin@hynt.one")
BOOTSTRAP_PASSWORD = _str("HYNT_BOOTSTRAP_PASSWORD", "")

# --------------------------------------------------------------------------- #
#  Login throttle
# --------------------------------------------------------------------------- #
# Backed by a table, not a dict: the counter has to hold across workers, and a
# per-process dict silently multiplies the real limit by the worker count.
LOGIN_MAX_ATTEMPTS = _int("HYNT_LOGIN_MAX_ATTEMPTS", 5)
LOGIN_WINDOW_SEC = _int("HYNT_LOGIN_WINDOW_SEC", 900)
LOGIN_LOCKOUT_SEC = _int("HYNT_LOGIN_LOCKOUT_SEC", 900)

# Where the login page sends a user who arrives without an OAuth request.
ACCOUNT_APP_URL = _str("HYNT_ACCOUNT_APP_URL", "http://localhost:5173")

# Signing key material. A PEM path keeps the key out of the database; when unset
# in development a key is generated and stored in the DB so a fresh clone runs.
SIGNING_KEY_PATH = _str("HYNT_SIGNING_KEY_PATH", "")
