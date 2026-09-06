"""Tests run against a real server on a throwaway database.

Anything that bypassed the HTTP layer would be exercising a different code path
from the one that actually serves traffic — including the cookie handling and
the redirect behaviour, which is where most of the risk in this service lives.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parent.parent
TEST_DB = "hynt_accounts_test"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _admin_url() -> str:
    """Reuse the app's credentials, pointed at the throwaway database."""
    url = os.environ["HYNT_DATABASE_URL"]
    return url.rsplit("/", 1)[0] + "/" + TEST_DB


@pytest.fixture(scope="session")
def server():
    for line in (BACKEND / ".env").read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

    base_url = os.environ["HYNT_DATABASE_URL"]
    admin = base_url.replace("+asyncpg", "+psycopg2")
    from sqlalchemy import create_engine, text

    engine = create_engine(admin.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB}"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    engine.dispose()

    env = {
        **os.environ,
        "HYNT_DATABASE_URL": _admin_url(),
        # No parent domain and no TLS in the test harness, so the cookie must be
        # host-only and insecure or httpx would never send it back.
        "HYNT_COOKIE_DOMAIN": "",
        "HYNT_COOKIE_SECURE": "false",
        "PYTHONPATH": str(BACKEND),
    }
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True,
                   capture_output=True)
    subprocess.run([sys.executable, "-m", "scripts.manage", "bootstrap"], cwd=BACKEND, env=env, check=True,
                   capture_output=True)

    port = _free_port()
    proc = subprocess.Popen(
        [str(BACKEND / ".venv/bin/uvicorn"), "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            if httpx.get(f"{url}/api/v1/health", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.25)
    else:
        proc.terminate()
        raise RuntimeError("test server did not start")

    yield url, env
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def client(server):
    url, _ = server
    with httpx.Client(base_url=url, follow_redirects=False, timeout=10) as c:
        yield c


@pytest.fixture
def superadmin(server):
    """A signed-in superadmin client, plus its password."""
    url, env = server
    password = "test-superadmin-pw-123"
    subprocess.run(
        [sys.executable, "-m", "scripts.manage", "passwd", "--email", "admin@hynt.one", "--password", password],
        cwd=BACKEND, env=env, check=True, capture_output=True,
    )
    with httpx.Client(base_url=url, follow_redirects=False, timeout=10) as c:
        response = c.post("/api/v1/auth/login", json={"email": "admin@hynt.one", "password": password})
        assert response.status_code == 200, response.text
        yield c
