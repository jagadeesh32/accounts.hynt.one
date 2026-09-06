"""Shared helpers for driving the OAuth flow from tests."""

from __future__ import annotations

import base64
import hashlib
import secrets
import urllib.parse

import httpx

#: Must match the URIs seeded in scripts/manage.py exactly — redirect URIs are
#: compared by exact string, so a stale port here fails as "invalid_redirect_uri"
#: rather than as an obviously wrong test constant.
REDIRECTS = {
    "terminal-web": "http://localhost:5174/auth/callback",
    "xterminal-web": "http://localhost:5175/auth/callback",
    "intelligence-web": "http://localhost:5176/auth/callback",
}


def pkce_pair() -> tuple[str, str]:
    """A verifier and its S256 challenge."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def authorize(client: httpx.Client, client_id: str, **extra) -> tuple[str, httpx.Response]:
    """Start an authorization request. Returns the verifier and the response."""
    verifier, challenge = pkce_pair()
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECTS[client_id],
        "response_type": "code",
        "scope": "openid profile email",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **extra,
    }
    return verifier, client.get("/oauth/authorize", params=params)


def redirect_params(response: httpx.Response) -> dict[str, str]:
    """The query parameters the authorize endpoint redirected with."""
    location = response.headers.get("location", "")
    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    return {key: values[0] for key, values in parsed.items()}


def exchange(client: httpx.Client, client_id: str, code: str, verifier: str) -> httpx.Response:
    return client.post(
        "/oauth/token",
        json={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": REDIRECTS[client_id],
        },
    )


def get_token(client: httpx.Client, client_id: str) -> str:
    """Complete the whole flow and return an access token."""
    verifier, response = authorize(client, client_id)
    params = redirect_params(response)
    assert "code" in params, f"authorize did not return a code: {params}"
    token_response = exchange(client, client_id, params["code"], verifier)
    assert token_response.status_code == 200, token_response.text
    return token_response.json()["access_token"]


def claims_of(token: str) -> dict:
    """Decode a JWT payload without verifying — for asserting on claims only."""
    import json

    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
