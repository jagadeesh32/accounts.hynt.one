import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

REDIRECT = "https://terminal.hynt.one/auth/callback"


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize(client, challenge, **extra):
    params = {
        "response_type": "code", "client_id": "terminal-web", "redirect_uri": REDIRECT,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "st", **extra,
    }
    return client.get("/oauth/authorize", params=params)


def code_from(response) -> str:
    return parse_qs(urlparse(response.headers["location"]).query)["code"][0]


def test_discovery_advertises_the_contract(client):
    doc = client.get("/.well-known/openid-configuration").json()
    assert doc["issuer"] == "https://accounts.hynt.one"
    assert doc["code_challenge_methods_supported"] == ["S256"]


def test_jwks_publishes_an_rsa_key(client):
    keys = client.get("/.well-known/jwks.json").json()["keys"]
    assert keys and keys[0]["kty"] == "RSA" and keys[0]["alg"] == "RS256"


def test_unknown_client_is_refused_without_redirecting(client):
    _, challenge = pkce()
    response = client.get("/oauth/authorize", params={
        "client_id": "not-a-client", "redirect_uri": REDIRECT,
        "code_challenge": challenge, "response_type": "code",
    })
    assert response.status_code == 400


def test_unregistered_redirect_uri_is_refused(client):
    _, challenge = pkce()
    response = authorize(client, challenge, redirect_uri="https://evil.example/cb")
    # Refused in place, never redirected — redirecting here is the open redirect.
    assert response.status_code == 400


def test_plain_pkce_is_refused(client):
    _, challenge = pkce()
    response = authorize(client, challenge, code_challenge_method="plain")
    assert "error=invalid_request" in response.headers["location"]


def test_signed_out_authorize_goes_to_the_login_page(client):
    _, challenge = pkce()
    response = authorize(client, challenge)
    assert response.status_code == 302
    assert response.headers["location"].startswith("/login?")


def test_prompt_none_never_shows_a_login_page(client):
    _, challenge = pkce()
    response = authorize(client, challenge, prompt="none")
    # The hidden renewal iframe must get an error back, not a form.
    assert "error=login_required" in response.headers["location"]


def test_full_code_exchange_yields_a_scoped_token(superadmin):
    verifier, challenge = pkce()
    code = code_from(authorize(superadmin, challenge))

    response = superadmin.post("/oauth/token", json={
        "grant_type": "authorization_code", "code": code, "client_id": "terminal-web",
        "redirect_uri": REDIRECT, "code_verifier": verifier,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 900

    payload = body["access_token"].split(".")[1]
    payload += "=" * (-len(payload) % 4)
    import json
    claims = json.loads(base64.urlsafe_b64decode(payload))
    assert claims["aud"] == "terminal"
    assert claims["iss"] == "https://accounts.hynt.one"
    assert claims["role"] == "admin"
    assert "terminal:scanner.run" in claims["perms"]
    assert claims["plan"] == "pro"
    assert "sid" in claims and "tv" in claims


def test_a_code_cannot_be_used_twice(superadmin):
    verifier, challenge = pkce()
    code = code_from(authorize(superadmin, challenge))
    body = {
        "grant_type": "authorization_code", "code": code, "client_id": "terminal-web",
        "redirect_uri": REDIRECT, "code_verifier": verifier,
    }
    assert superadmin.post("/oauth/token", json=body).status_code == 200
    assert superadmin.post("/oauth/token", json=body).status_code == 400


def test_the_wrong_verifier_is_refused(superadmin):
    _, challenge = pkce()
    code = code_from(authorize(superadmin, challenge))
    response = superadmin.post("/oauth/token", json={
        "grant_type": "authorization_code", "code": code, "client_id": "terminal-web",
        "redirect_uri": REDIRECT, "code_verifier": secrets.token_urlsafe(48),
    })
    assert response.status_code == 400


def test_redirect_uri_must_match_the_one_the_code_was_issued_for(superadmin):
    verifier, challenge = pkce()
    code = code_from(authorize(superadmin, challenge))
    response = superadmin.post("/oauth/token", json={
        "grant_type": "authorization_code", "code": code, "client_id": "terminal-web",
        "redirect_uri": "http://localhost:5173/auth/callback", "code_verifier": verifier,
    })
    assert response.status_code == 400
