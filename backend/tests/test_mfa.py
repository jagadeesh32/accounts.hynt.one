"""Second factor: enrolment, login, replay, recovery codes, reset."""
import subprocess
import sys
import time

import httpx
import pyotp
import pytest

from tests.conftest import BACKEND

ADMIN = "admin@hynt.one"
PW = "test-superadmin-pw-123"


def _client(server):
    url, _ = server
    return httpx.Client(base_url=url, follow_redirects=False, timeout=10)


def _login(c, otp=None):
    return c.post("/api/v1/auth/login", json={"email": ADMIN, "password": PW, "otp": otp})


def _code(secret, offset_steps=0):
    return pyotp.TOTP(secret).at(int(time.time()) + 30 * offset_steps)


@pytest.fixture
def enrolled(server, superadmin):
    """A signed-in superadmin with two-factor on. Yields (client, secret,
    recovery_codes) and clears MFA afterwards so other suites are unaffected."""
    _, env = server
    setup = superadmin.post("/api/v1/me/mfa/setup").json()
    secret = setup["secret"]
    assert setup["otpauth_uri"].startswith("otpauth://totp/Hynt:")
    enabled = superadmin.post("/api/v1/me/mfa/enable", json={"otp": _code(secret)})
    assert enabled.status_code == 200, enabled.text
    codes = enabled.json()["recovery_codes"]
    assert len(codes) == 10 and all(len(c) == 11 and c[5] == "-" for c in codes)
    try:
        yield superadmin, secret, codes
    finally:
        subprocess.run(
            [sys.executable, "-m", "scripts.manage", "mfa-reset", "--email", ADMIN],
            cwd=BACKEND, env=env, check=True, capture_output=True,
        )


def test_qr_renders_a_png_during_setup(superadmin):
    superadmin.post("/api/v1/me/mfa/setup")
    png = superadmin.get("/api/v1/me/mfa/qr.png")
    assert png.status_code == 200, png.text
    assert png.headers["content-type"] == "image/png"
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_enable_needs_a_matching_code(superadmin):
    superadmin.post("/api/v1/me/mfa/setup")
    assert superadmin.post("/api/v1/me/mfa/enable", json={"otp": "000000"}).status_code == 400
    assert superadmin.get("/api/v1/me").json()["mfa_enabled"] is False


def test_secret_is_not_stored_in_the_clear(server, enrolled):
    _, secret, _ = enrolled
    from sqlalchemy import create_engine, text

    _, env = server
    engine = create_engine(env["HYNT_DATABASE_URL"].replace("+asyncpg", "+psycopg2"))
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT mfa_secret FROM users WHERE email = :e"), {"e": ADMIN}).scalar()
    engine.dispose()
    assert stored and secret not in stored
    assert stored.startswith("gAAAA")  # Fernet token prefix


def test_login_asks_for_a_code_then_accepts_it(server, enrolled):
    _, secret, _ = enrolled
    with _client(server) as c:
        first = _login(c)
        assert first.status_code == 200 and first.json() == {"mfa_required": True}
        assert c.get("/api/v1/me").status_code == 401, "no session before the second factor"

        assert _login(c, "123456").status_code == 401
        ok = _login(c, _code(secret, offset_steps=1))  # drift within the window
        assert ok.status_code == 200, ok.text
        assert c.get("/api/v1/me").json()["recovery_codes_remaining"] == 10


def test_a_code_cannot_be_replayed(server, enrolled):
    _, secret, _ = enrolled
    # Enrolment already spent the current step, so take the next one.
    code = _code(secret, offset_steps=1)
    with _client(server) as a, _client(server) as b:
        assert _login(a, code).status_code == 200
        replay = _login(b, code)
        assert replay.status_code == 401
        assert replay.json()["detail"] == "Incorrect verification code"


def test_recovery_code_works_exactly_once(server, enrolled):
    _, _, codes = enrolled
    with _client(server) as a, _client(server) as b:
        assert _login(a, codes[0].upper().replace("-", " ")).status_code == 200  # forgiving input
        assert a.get("/api/v1/me").json()["recovery_codes_remaining"] == 9
        assert _login(b, codes[0]).status_code == 401
        assert _login(b, codes[1]).status_code == 200


def test_regenerating_codes_invalidates_the_old_set(server, enrolled):
    me, _, old = enrolled
    assert me.post("/api/v1/me/mfa/recovery-codes", json={"password": "wrong"}).status_code == 400
    new = me.post("/api/v1/me/mfa/recovery-codes", json={"password": PW}).json()["recovery_codes"]
    assert not set(new) & set(old)
    with _client(server) as c:
        assert _login(c, old[0]).status_code == 401
        assert _login(c, new[0]).status_code == 200


def test_disable_requires_the_password_and_clears_everything(server, enrolled):
    me, _, codes = enrolled
    assert me.post("/api/v1/me/mfa/disable", json={"password": "wrong"}).status_code == 400
    assert me.post("/api/v1/me/mfa/disable", json={"password": PW}).status_code == 200
    profile = me.get("/api/v1/me").json()
    assert profile["mfa_enabled"] is False and profile["recovery_codes_remaining"] == 0
    with _client(server) as c:
        assert _login(c).json()["ok"] is True
        # A stale recovery code must not survive as a password-only backdoor.
        assert _login(c, codes[0]).json()["ok"] is True  # ignored, not honoured: MFA is off


def test_superadmin_can_reset_a_locked_out_user(server, enrolled):
    me, _, _ = enrolled
    uid = me.get("/api/v1/me").json()["id"]
    assert me.post(f"/api/v1/superadmin/users/{uid}/mfa/reset").status_code == 200
    with _client(server) as c:
        assert _login(c).json()["ok"] is True


def test_missing_encryption_key_is_a_boot_failure():
    from app.config import Settings

    with pytest.raises(ValueError):
        Settings(mfa_encryption_key="", _env_file=None)
    with pytest.raises(ValueError):
        Settings(mfa_encryption_key="not-a-key", _env_file=None)
