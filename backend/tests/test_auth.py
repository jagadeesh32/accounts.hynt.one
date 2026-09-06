"""Sign-in, sessions and passwords."""

from __future__ import annotations

from tests.conftest import SUPERADMIN_EMAIL, SUPERADMIN_PASSWORD


def test_health_reports_ok(anon):
    assert anon.get("/api/v1/health").json()["status"] == "ok"


def test_login_sets_an_httponly_cookie(anon):
    response = anon.post(
        "/api/v1/auth/login",
        json={"email": SUPERADMIN_EMAIL, "password": SUPERADMIN_PASSWORD},
    )
    assert response.status_code == 200

    cookie = response.headers.get("set-cookie", "")
    assert "hynt_sso=" in cookie
    # HttpOnly is the whole point: a session token JavaScript can read is a
    # session token XSS can steal.
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_login_returns_platform_access_not_a_token(anon):
    """The login response is useful to the accounts UI and useless as a shortcut
    past the OAuth flow — tokens are minted per platform, not here."""
    body = anon.post(
        "/api/v1/auth/login",
        json={"email": SUPERADMIN_EMAIL, "password": SUPERADMIN_PASSWORD},
    ).json()

    assert body["user"]["email"] == SUPERADMIN_EMAIL
    assert body["user"]["is_superadmin"] is True
    assert {entry["platform"]["slug"] for entry in body["access"]} == {
        "terminal", "xterminal", "intelligence",
    }
    assert "access_token" not in body and "token" not in body


def test_wrong_password_is_rejected(anon):
    response = anon.post(
        "/api/v1/auth/login", json={"email": SUPERADMIN_EMAIL, "password": "not-the-password"}
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_credentials"


def test_unknown_account_is_indistinguishable_from_a_wrong_password(anon):
    """Same status and same message, so the login form is not an account
    enumerator."""
    unknown = anon.post(
        "/api/v1/auth/login", json={"email": "nobody@hynt.one", "password": "whatever12345"}
    )
    known = anon.post(
        "/api/v1/auth/login", json={"email": SUPERADMIN_EMAIL, "password": "wrong-password"}
    )
    assert unknown.status_code == known.status_code == 401
    assert unknown.json()["message"] == known.json()["message"]


def test_session_endpoint_answers_200_when_signed_out(anon):
    """Not being signed in is the expected answer here, not an error — a 401
    would make the SPA treat a first visit as a failure."""
    body = anon.get("/api/v1/auth/session").json()
    assert body == {"authenticated": False}


def test_session_endpoint_describes_the_signed_in_user(admin):
    body = admin.get("/api/v1/auth/session").json()
    assert body["authenticated"] is True
    assert body["user"]["email"] == SUPERADMIN_EMAIL
    assert body["session"]["current"] is True


def test_logout_clears_the_cookie_and_ends_the_session(admin):
    response = admin.post("/api/v1/auth/logout")
    assert response.status_code == 200
    assert "Max-Age=0" in response.headers.get("set-cookie", "")
    assert admin.get("/api/v1/auth/session").json()["authenticated"] is False


def test_logout_succeeds_without_a_session(anon):
    """A sign-out button that can fail is one that sometimes leaves people
    signed in."""
    assert anon.post("/api/v1/auth/logout").status_code == 200


def test_self_registration_is_disabled_by_default(anon):
    response = anon.post(
        "/api/v1/auth/register",
        json={"email": "walkup@hynt.one", "password": "LongEnoughPass1"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "registration_disabled"


def test_forgot_password_answers_the_same_for_unknown_addresses(anon):
    known = anon.post("/api/v1/auth/password/forgot", json={"email": SUPERADMIN_EMAIL})
    unknown = anon.post("/api/v1/auth/password/forgot", json={"email": "nobody@hynt.one"})
    assert known.status_code == unknown.status_code == 200
    assert known.json()["message"] == unknown.json()["message"]


def test_short_passwords_are_refused(admin):
    response = admin.post(
        "/api/v1/auth/password/change",
        json={"current_password": SUPERADMIN_PASSWORD, "new_password": "short"},
    )
    assert response.status_code == 400


def test_password_change_requires_the_current_password(admin):
    response = admin.post(
        "/api/v1/auth/password/change",
        json={"current_password": "definitely-wrong", "new_password": "AnotherLongPass1"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "wrong_password"


def test_repeated_failures_lock_the_account_out(anon, server):
    """The lockout has to survive the failed request that triggers it.

    Regression test for a real bug: the throttle counter and the audit entry
    were written inside the request's transaction, which rolls back when the
    handler rejects the login — so the counter never advanced, the lockout never
    fired, and passwords could be guessed without limit.
    """
    import httpx

    email = "throttle-target@hynt.one"
    with httpx.Client(base_url=server, timeout=10) as client:
        # A distinct forwarded address so this test cannot lock out another one:
        # the throttle is keyed on email *and* IP.
        headers = {"X-Forwarded-For": "198.51.100.77"}
        statuses = [
            client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": f"wrong-{attempt}"},
                headers=headers,
            ).status_code
            for attempt in range(7)
        ]

    assert statuses[:5] == [401] * 5, statuses
    assert statuses[5:] == [429, 429], statuses
