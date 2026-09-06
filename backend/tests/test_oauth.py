"""The authorization-code + PKCE flow, and the guarantees it has to hold."""

from __future__ import annotations

from tests.helpers import REDIRECTS, authorize, claims_of, exchange, get_token, redirect_params


def test_discovery_document_advertises_the_flow(anon):
    body = anon.get("/.well-known/openid-configuration").json()
    assert body["response_types_supported"] == ["code"]
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert body["id_token_signing_alg_values_supported"] == ["RS256"]


def test_jwks_publishes_a_public_key(anon):
    keys = anon.get("/.well-known/jwks.json").json()["keys"]
    assert keys and keys[0]["kty"] == "RSA" and keys[0]["alg"] == "RS256"
    # A private exponent in a public document would be a catastrophe; assert it
    # is not there rather than assuming.
    assert not any(field in keys[0] for field in ("d", "p", "q"))


def test_a_live_session_signs_in_without_a_password(admin):
    """The single sign-on itself: an existing SSO cookie yields a code with no
    credential prompt."""
    _, response = authorize(admin, "terminal-web")
    assert response.status_code in (302, 307)
    assert "code" in redirect_params(response)


def test_no_session_is_sent_to_the_login_page(anon):
    _, response = authorize(anon, "terminal-web")
    location = response.headers["location"]
    assert location.startswith("http://localhost:5173/login")
    # The original authorize request has to survive the round trip, or signing
    # in would strand the user on the accounts dashboard.
    assert "next=" in location
    assert "{" not in location, "a Python repr leaked into the redirect"


def test_tokens_are_scoped_to_one_platform(admin):
    for client_id, expected in [
        ("terminal-web", "terminal"),
        ("xterminal-web", "xterminal"),
        ("intelligence-web", "intelligence"),
    ]:
        claims = claims_of(get_token(admin, client_id))
        assert claims["aud"] == expected
        assert claims["typ"] == "access"


def test_the_token_carries_role_plan_and_permissions(admin):
    claims = claims_of(get_token(admin, "terminal-web"))
    assert claims["role"] == "superadmin"
    assert claims["rank"] == 40
    assert claims["perms"] == ["*"]
    assert claims["plan"] == "free"
    # The quota travels with the token so a platform can enforce it without
    # calling back here.
    assert claims["lim"]["scans_per_day"] == 25


def test_an_authorization_code_can_only_be_used_once(admin):
    verifier, response = authorize(admin, "terminal-web")
    code = redirect_params(response)["code"]

    assert exchange(admin, "terminal-web", code, verifier).status_code == 200

    replay = exchange(admin, "terminal-web", code, verifier)
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"


def test_the_wrong_pkce_verifier_is_refused(admin):
    """What stops a stolen code being redeemed by whoever stole it."""
    _, response = authorize(admin, "terminal-web")
    code = redirect_params(response)["code"]

    result = exchange(admin, "terminal-web", code, "a-completely-different-verifier")
    assert result.status_code == 400
    assert "PKCE" in result.json()["error_description"]


def test_pkce_is_mandatory(admin):
    response = admin.get(
        "/oauth/authorize",
        params={
            "client_id": "terminal-web",
            "redirect_uri": REDIRECTS["terminal-web"],
            "response_type": "code",
        },
    )
    assert redirect_params(response)["error"] == "invalid_request"


def test_an_unregistered_redirect_uri_is_refused(admin):
    """Exact-match only. Prefix matching here is how an open redirect becomes a
    stolen authorization code."""
    response = admin.get(
        "/oauth/authorize",
        params={
            "client_id": "terminal-web",
            "redirect_uri": "https://evil.example/steal",
            "response_type": "code",
            "code_challenge": "x" * 43,
            "code_challenge_method": "S256",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"
    # Crucially, it must not have bounced the browser to the unverified URI.
    assert "location" not in response.headers


def test_a_code_cannot_be_redeemed_by_another_client(admin):
    verifier, response = authorize(admin, "terminal-web")
    code = redirect_params(response)["code"]

    result = exchange(admin, "xterminal-web", code, verifier)
    assert result.status_code == 400
    assert result.json()["error"] == "invalid_grant"


def test_prompt_none_renews_silently_with_a_session(admin):
    _, response = authorize(admin, "terminal-web", prompt="none")
    assert "code" in redirect_params(response)


def test_prompt_none_fails_cleanly_without_a_session(anon):
    """The SPA's hidden frame needs `login_required`, not a login page it cannot
    render."""
    _, response = authorize(anon, "terminal-web", prompt="none")
    assert redirect_params(response)["error"] == "login_required"


def test_userinfo_accepts_the_access_token(admin):
    token = get_token(admin, "terminal-web")
    body = admin.get("/oauth/userinfo", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["role"] == "superadmin"


def test_userinfo_refuses_a_garbage_token(anon):
    response = anon.get("/oauth/userinfo", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_single_logout_ends_silent_renewal_everywhere(admin):
    """Signing out at the provider is what makes every platform fall back to the
    login screen on its next renewal."""
    assert "code" in redirect_params(authorize(admin, "terminal-web", prompt="none")[1])

    admin.post("/api/v1/auth/logout")

    for client_id in ("terminal-web", "xterminal-web", "intelligence-web"):
        _, response = authorize(admin, client_id, prompt="none")
        assert redirect_params(response)["error"] == "login_required"


def test_the_seeded_redirect_uris_match_what_the_tests_use(admin):
    """Guards against port drift.

    Redirect URIs are compared by exact string, so moving a dev server's port in
    `scripts/manage.py` without updating `tests/helpers.py` fails every OAuth
    test with `invalid_redirect_uri` — which reads like a bug in the flow rather
    than a stale constant. This says which it is.
    """
    registered = {
        row["slug"]: row for row in admin.get("/api/v1/admin/platforms").json()["platforms"]
    }
    assert set(registered) == {"terminal", "xterminal", "intelligence"}

    for client_id, redirect in REDIRECTS.items():
        _, response = authorize(admin, client_id)
        assert response.status_code in (302, 307), (
            f"{client_id} rejected {redirect} — is it still registered in scripts/manage.py?"
        )
        assert "code" in redirect_params(response)
