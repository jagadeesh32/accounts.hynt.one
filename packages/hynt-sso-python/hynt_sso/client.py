"""JWKS fetching and token verification."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx
import jwt

from hynt_sso.principal import Principal

log = logging.getLogger("hynt_sso")


class TokenError(Exception):
    """The token is absent, malformed, expired, or not for this platform."""


class HyntSSO:
    """Verifies access tokens issued by accounts.hynt.one.

    Args:
        issuer: e.g. ``https://accounts.hynt.one``. Must match the ``iss`` claim
            exactly, so a token from a staging issuer is refused in production.
        audience: this platform's slug — ``terminal``, ``xterminal`` or
            ``intelligence``. A token minted for a sibling platform fails here,
            which is what keeps one platform's leaked token useless on the next.
        jwks_ttl: seconds to cache the key set. Shorter means a rotated key is
            picked up sooner; a cache miss on an unknown ``kid`` refetches
            immediately regardless, so this only bounds the *stale key* window.
        leeway: clock skew allowance, in seconds.
        check_revocations: poll the provider's revocation list so a suspended or
            revoked account stops working within seconds instead of when its
            access token expires. Costs one small cached request per
            ``revocation_ttl``, not one per user request. On by default —
            "revoked" should mean revoked.
        revocation_ttl: seconds between polls — the worst-case delay between a
            superadmin clicking revoke and this platform enforcing it. Leave it
            as None to follow the interval the provider advertises; setting it
            explicitly pins it, and an explicit value is never overridden by the
            provider's hint.
        fail_open_on_revocation_error: when the revocation list cannot be
            fetched at all, whether to keep serving. Defaults to True: an
            identity provider that is briefly unreachable must not sign every
            user out of every platform at once. Set False for a service where
            stale authorisation is worse than an outage.
    """

    def __init__(
        self,
        issuer: str,
        audience: str,
        *,
        jwks_ttl: int = 3600,
        leeway: int = 30,
        timeout: float = 5.0,
        http_client: httpx.Client | None = None,
        check_revocations: bool = True,
        revocation_ttl: int | None = None,
        fail_open_on_revocation_error: bool = True,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.jwks_uri = f"{self.issuer}/.well-known/jwks.json"
        self.jwks_ttl = jwks_ttl
        self.leeway = leeway
        self._timeout = timeout
        self._client = http_client

        self.check_revocations = check_revocations
        #: A value passed here is the operator's decision and stays put; without
        #: one the provider's advertised interval is followed.
        self._ttl_pinned = revocation_ttl is not None
        self.revocation_ttl = revocation_ttl if revocation_ttl is not None else 30
        self.fail_open_on_revocation_error = fail_open_on_revocation_error
        self.revocation_uri = f"{self.issuer}/api/v1/revocations"

        self._lock = threading.Lock()
        self._keys: dict[str, Any] = {}
        self._fetched_at: float = 0.0

        self._revocation_lock = threading.Lock()
        #: (sub, platform-or-None) -> minimum acceptable token_version
        self._revocations: dict[tuple[str, str | None], int] = {}
        self._revocations_at: float = 0.0
        self._revocations_ok = False

    # ------------------------------------------------------------------ keys
    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def _refresh_keys(self, *, force: bool = False) -> None:
        with self._lock:
            fresh = (time.monotonic() - self._fetched_at) < self.jwks_ttl
            if self._keys and fresh and not force:
                return
            try:
                response = self._http().get(self.jwks_uri)
                response.raise_for_status()
                document = response.json()
            except Exception as exc:  # noqa: BLE001
                # Keep serving with the keys we have. The identity provider being
                # briefly unreachable must not sign every user out of every
                # platform at once.
                if self._keys:
                    log.warning("JWKS refresh failed (%s) — using cached keys", exc)
                    return
                raise TokenError(f"cannot fetch JWKS from {self.jwks_uri}: {exc}") from exc

            self._keys = {
                k["kid"]: jwt.PyJWK.from_dict(k).key
                for k in document.get("keys", [])
                if k.get("kid")
            }
            self._fetched_at = time.monotonic()
            log.info("loaded %d signing key(s) from %s", len(self._keys), self.jwks_uri)

    def _key_for(self, kid: str):
        self._refresh_keys()
        key = self._keys.get(kid)
        if key is None:
            # An unknown kid means a rotation happened since the last fetch.
            # Refetching once here is what makes rotation invisible to users.
            self._refresh_keys(force=True)
            key = self._keys.get(kid)
        if key is None:
            raise TokenError(f"unknown signing key '{kid}'")
        return key

    # ------------------------------------------------------------ revocations
    def _refresh_revocations(self) -> None:
        with self._revocation_lock:
            if (time.monotonic() - self._revocations_at) < self.revocation_ttl:
                return
            try:
                response = self._http().get(self.revocation_uri)
                response.raise_for_status()
                document = response.json()
            except Exception as exc:  # noqa: BLE001
                # Keep the last known list and try again next time. Discarding it
                # here would mean a momentary blip re-admits accounts that were
                # revoked minutes ago.
                log.warning("revocation refresh failed (%s)", exc)
                self._revocations_at = time.monotonic()
                if not self._revocations_ok and not self.fail_open_on_revocation_error:
                    raise TokenError("revocation list unavailable") from exc
                return

            entries: dict[tuple[str, str | None], int] = {}
            for entry in document.get("revocations", []):
                sub = entry.get("sub")
                if not sub:
                    continue
                key = (str(sub), entry.get("platform"))
                entries[key] = max(entries.get(key, 0), int(entry.get("min_tv", 0)))

            self._revocations = entries
            self._revocations_at = time.monotonic()
            self._revocations_ok = True

            # The provider suggests how often to come back so the interval is
            # consistent across platforms — but only when this one did not pin
            # its own. Silently lengthening an interval an operator deliberately
            # shortened would quietly weaken the guarantee they asked for.
            suggested = document.get("poll_after_seconds")
            if not self._ttl_pinned and isinstance(suggested, int) and suggested > 0:
                self.revocation_ttl = suggested

    def _assert_not_revoked(self, claims: dict[str, Any]) -> None:
        if not self.check_revocations:
            return
        self._refresh_revocations()
        if not self._revocations:
            return

        sub = str(claims.get("sub", ""))
        version = int(claims.get("tv", 0) or 0)

        # A revocation for this platform specifically, and one covering every
        # platform, are both binding.
        for key in ((sub, None), (sub, self.audience)):
            minimum = self._revocations.get(key)
            if minimum is not None and version < minimum:
                raise TokenError("access has been revoked")

    # ----------------------------------------------------------------- verify
    def verify(self, token: str) -> dict[str, Any]:
        """Return the claims, or raise TokenError."""
        if not token:
            raise TokenError("no token supplied")

        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise TokenError(f"malformed token: {exc}") from exc

        # Pin the algorithm. Trusting the header's `alg` is how a token signed
        # with `none`, or an HMAC over the public key, gets accepted.
        if header.get("alg") != "RS256":
            raise TokenError(f"unexpected algorithm '{header.get('alg')}'")

        key = self._key_for(header.get("kid", ""))

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                leeway=self.leeway,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenError("token has expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise TokenError(f"token is not for '{self.audience}'") from exc
        except jwt.PyJWTError as exc:
            raise TokenError(f"invalid token: {exc}") from exc

        if claims.get("typ") != "access":
            raise TokenError("not an access token")

        # Signature and expiry are not enough: the account behind the token must
        # still be allowed in. This is the check that makes a superadmin's
        # "revoke now" take effect in seconds rather than at the token's expiry.
        self._assert_not_revoked(claims)

        return claims

    def principal(self, token: str) -> Principal:
        return Principal.from_claims(self.verify(token))

    def principal_or_none(self, token: str | None) -> Principal | None:
        """Non-raising variant, for WebSocket upgrades and optional auth."""
        if not token:
            return None
        try:
            return self.principal(token)
        except TokenError:
            return None

    # ------------------------------------------------------------- utilities
    @staticmethod
    def bearer_from_header(authorization: str | None) -> str | None:
        if not authorization:
            return None
        scheme, _, value = authorization.partition(" ")
        return value.strip() if scheme.lower() == "bearer" and value.strip() else None

    def reject_reason(self, token: str | None) -> str:
        """Why a token was refused — for logs, never for the client.

        A WebSocket upgrade rejected before accept gives the browser a bare 403,
        so without this the three causes that look identical in the console (no
        token, wrong issuer, expired) are indistinguishable server-side too.
        """
        if not token:
            return "no token presented"
        try:
            self.verify(token)
        except TokenError as exc:
            return str(exc)
        return "accepted"
