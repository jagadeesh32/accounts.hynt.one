"""Verify Hynt access tokens locally.

The point of this SDK is that it does *not* call accounts.hynt.one on the
request path. It fetches the JWKS once, caches it, and verifies signatures in
process. The only recurring call is the revocation list — one small cached
request every ~30 seconds for the whole process, not one per user request.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from jwt import PyJWK


class TokenError(Exception):
    """Raised for every reason a token is not acceptable. Deliberately one
    class: a caller that branches on *why* a token failed tends to leak that
    reason to the client, which is an oracle."""


@dataclass
class Principal:
    """The caller, as the identity provider describes them for this platform."""

    user_id: str
    email: str
    name: str
    role: str
    rank: int
    permissions: list[str] = field(default_factory=list)
    plan: str | None = None
    plan_status: str | None = None
    entitlements: list[str] = field(default_factory=list)
    limits: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    token_version: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    #: Central ranks. A check is "at least this role", never string equality —
    #: an admin passes has_role("staff") without every call site listing both.
    RANKS = {"user": 10, "staff": 20, "admin": 30, "superadmin": 40}

    def has_role(self, role: str) -> bool:
        return self.rank >= self.RANKS.get(role, 10**6)

    def has_permission(self, code: str) -> bool:
        return code in self.permissions

    def has_entitlement(self, code: str) -> bool:
        return code in self.entitlements

    def limit(self, key: str, default: Any = None) -> Any:
        return self.limits.get(key, default)

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> "Principal":
        return cls(
            user_id=claims.get("sub", ""),
            email=claims.get("email", ""),
            name=claims.get("name", ""),
            role=claims.get("role", "user"),
            rank=int(claims.get("rank", 0)),
            permissions=list(claims.get("perms", [])),
            plan=claims.get("plan"),
            plan_status=claims.get("plan_status"),
            entitlements=list(claims.get("ent", [])),
            limits=dict(claims.get("lim", {})),
            session_id=claims.get("sid", ""),
            token_version=int(claims.get("tv", 0)),
            raw=claims,
        )


class _Jwks:
    """Cached public keys.

    PyJWT's own PyJWKClient fetches with urllib, whose default user-agent
    Cloudflare answers with 403 in front of accounts.hynt.one — the symptom is
    every token being rejected for "Fail to fetch data from the url". httpx is
    used instead (it gets through, and it is already a dependency here).

    A miss on an unknown `kid` refetches once, ignoring the TTL: that is what
    makes a key rotation take effect immediately rather than an hour later.
    """

    def __init__(self, url: str, ttl: int, timeout: float, headers: dict[str, str]):
        self._url = url
        self._ttl = ttl
        self._timeout = timeout
        self._headers = headers
        self._lock = threading.Lock()
        self._keys: dict[str, Any] = {}
        self._fetched_at = 0.0

    def _fetch(self) -> None:
        data = httpx.get(self._url, timeout=self._timeout, headers=self._headers).raise_for_status().json()
        keys = {}
        for entry in data.get("keys", []):
            try:
                keys[entry["kid"]] = PyJWK(entry).key
            except Exception:
                continue  # one unusable key must not break the rest
        if keys:
            self._keys = keys
            self._fetched_at = time.monotonic()

    def key_for(self, kid: str) -> Any:
        with self._lock:
            stale = time.monotonic() - self._fetched_at > self._ttl
            if not self._keys or stale:
                self._fetch()
            if kid not in self._keys:
                # Unknown kid: the provider may have just rotated.
                self._fetch()
            key = self._keys.get(kid)
        if key is None:
            raise TokenError(f"unknown signing key {kid}")
        return key


class _Revocations:
    """Polled cache of the published revocation list."""

    def __init__(self, url: str, timeout: float = 3.0, headers: dict[str, str] | None = None):
        self._url = url
        self._timeout = timeout
        self._headers = headers or {}
        self._lock = threading.Lock()
        self._users: set[str] = set()
        self._sessions: set[str] = set()
        self._fetched_at = 0.0
        self._interval = 30.0

    def _refresh_if_due(self) -> None:
        now = time.monotonic()
        if now - self._fetched_at < self._interval:
            return
        with self._lock:
            if now - self._fetched_at < self._interval:
                return
            try:
                data = httpx.get(self._url, timeout=self._timeout, headers=self._headers).json()
            except Exception:
                # Fail *open* on a fetch error, and retry soon. The alternative —
                # refusing every token because the IdP blinked — turns a brief
                # outage there into a total outage across the estate. The window
                # is bounded by the 15-minute token lifetime either way.
                self._fetched_at = now - self._interval + 5
                return
            self._users = set(data.get("users", []))
            self._sessions = set(data.get("sessions", []))
            self._interval = float(data.get("poll_after", 30))
            self._fetched_at = now

    def blocked(self, user_id: str, session_id: str) -> bool:
        self._refresh_if_due()
        return user_id in self._users or session_id in self._sessions


class HyntSSO:
    def __init__(
        self,
        issuer: str,
        audience: str,
        *,
        jwks_ttl: int = 3600,
        check_revocations: bool = True,
        leeway: int = 30,
        timeout: float = 3.0,
        origin: str | None = None,
    ):
        """`origin` overrides where the JWKS and revocation list are *fetched*
        from, without changing the `iss` this validates against.

        On a box that also runs accounts.hynt.one, pass
        ``origin="http://127.0.0.1:8103"``: server-to-server calls then skip
        the CDN entirely — no egress, no edge rules, and nothing to go wrong at
        3am because a WAF rule changed."""
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.leeway = leeway
        base = (origin or self.issuer).rstrip("/")
        headers = {"User-Agent": f"hynt-sso/1.0 (+{self.issuer})"}
        self._jwks = _Jwks(f"{base}/.well-known/jwks.json", jwks_ttl, timeout, headers)
        self._revocations = (
            _Revocations(f"{base}/api/v1/revocations", timeout, headers) if check_revocations else None
        )

    def verify(self, token: str) -> dict[str, Any]:
        """Signature, issuer, audience, expiry, revocation. Raises TokenError."""
        if not token:
            raise TokenError("no token")
        try:
            kid = jwt.get_unverified_header(token).get("kid", "")
            signing_key = self._jwks.key_for(kid)
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                # audience is the whole point: a token minted for another
                # platform must not verify here, however valid its signature.
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise TokenError(str(exc)) from exc

        if self._revocations and self._revocations.blocked(claims.get("sub", ""), claims.get("sid", "")):
            raise TokenError("revoked")
        return claims

    def principal(self, token: str) -> Principal:
        return Principal.from_claims(self.verify(token))

    def reject_reason(self, token: str | None) -> str:
        """For logs only. Never return this to a client."""
        try:
            self.verify(token or "")
            return "ok"
        except TokenError as exc:
            return str(exc)

    # -- FastAPI convenience -------------------------------------------------

    def bearer(self, authorization: str | None) -> Principal:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise TokenError("missing bearer token")
        return self.principal(authorization.split(" ", 1)[1].strip())
