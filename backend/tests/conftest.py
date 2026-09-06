"""Test fixtures.

The suite runs against a live server rather than an in-process client: Cello's
HTTP engine, routing and JSON serialisation are all Rust, so anything that
bypassed the server would be testing a different code path from the one that
serves production traffic.

A dedicated database is created and migrated per session, so running the tests
never touches development data.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parent.parent
TEST_DB = os.getenv("HYNT_TEST_DB", "hynt_accounts_test")
TEST_PORT = int(os.getenv("HYNT_TEST_PORT", "9111"))
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"

SUPERADMIN_EMAIL = "test-admin@hynt.one"
SUPERADMIN_PASSWORD = "TestSuperadmin!2026"


def _admin_dsn() -> str:
    return os.getenv("HYNT_TEST_ADMIN_DSN", "postgresql://postgres:postgres@localhost:5432/postgres")


def _database_url() -> str:
    base = os.getenv("HYNT_TEST_DATABASE_URL")
    if base:
        return base
    return f"postgresql+psycopg2://postgres:postgres@localhost:5432/{TEST_DB}"


@pytest.fixture(scope="session")
def server_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        HYNT_ENV="development",
        HYNT_DEBUG="false",
        HYNT_PORT=str(TEST_PORT),
        HYNT_ISSUER=BASE_URL,
        HYNT_DATABASE_URL=_database_url(),
        HYNT_COOKIE_DOMAIN="",
        HYNT_COOKIE_SECURE="false",
        HYNT_ACCOUNT_APP_URL="http://localhost:5173",
        HYNT_ALLOW_SELF_REGISTRATION="false",
        # A short access-token lifetime keeps the expiry test from sleeping for
        # fifteen minutes.
        HYNT_ACCESS_TOKEN_TTL_SEC="900",
    )
    return env


@pytest.fixture(scope="session", autouse=True)
def database(server_env):
    """A fresh database, migrated to head and seeded."""
    import psycopg2

    conn = psycopg2.connect(_admin_dsn())
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        cur.execute(f'CREATE DATABASE "{TEST_DB}"')
    conn.close()

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND, env=server_env, check=True, capture_output=True,
    )
    subprocess.run(
        [sys.executable, "-m", "scripts.manage", "bootstrap",
         "--email", SUPERADMIN_EMAIL, "--password", SUPERADMIN_PASSWORD, "--name", "Test Admin"],
        cwd=BACKEND, env=server_env, check=True, capture_output=True,
    )
    yield


@pytest.fixture(scope="session")
def server(database, server_env):
    """The running identity provider."""
    process = subprocess.Popen(
        [sys.executable, "-m", "app.main"],
        cwd=BACKEND, env=server_env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )

    deadline = time.time() + 30
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited early:\n{process.stdout.read().decode()}")
        try:
            if httpx.get(f"{BASE_URL}/api/v1/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        process.kill()
        raise RuntimeError("server did not become ready")

    yield BASE_URL

    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


@pytest.fixture
def anon(server) -> httpx.Client:
    """A client with no session. Redirects are never followed: the tests care
    about the Location header, which is where the OAuth result actually lives."""
    with httpx.Client(base_url=server, follow_redirects=False, timeout=10) as client:
        yield client


@pytest.fixture
def admin(server) -> httpx.Client:
    """A signed-in superadmin."""
    with httpx.Client(base_url=server, follow_redirects=False, timeout=10) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": SUPERADMIN_EMAIL, "password": SUPERADMIN_PASSWORD},
        )
        assert response.status_code == 200, response.text
        yield client
