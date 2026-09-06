"""OAuth 2.1 authorization-code + PKCE, and the OIDC discovery surface.

How a platform signs a user in:

  1. terminal.hynt.one redirects the browser to ``/oauth/authorize``.
  2. This service reads the ``hynt_sso`` cookie. If it is live, no password is
     asked for — that is the single sign-on. Otherwise the browser is sent to the
     accounts login page, which returns here afterwards.
  3. A one-minute, single-use code goes back to the platform's redirect URI.
  4. The platform's SPA exchanges it at ``/oauth/token`` with its PKCE verifier
     and receives an access token scoped to that platform alone.

Silent renewal uses the same route with ``prompt=none``: it either returns a
fresh code straight away or fails with ``login_required``, which keeps refresh
tokens out of browser storage entirely.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from cello import Blueprint, Response
from sqlalchemy import select

from app import config
from app.core import audit, keys, sessions
from app.core.authz import current_context
from app.core.http import (
    ApiError,
    body_json,
    client_ip,
    endpoint,
    get_cookie,
    ok,
    query,
    user_agent,
)
from app.core.security import constant_time_equals, new_secret, token_digest, verify_password
from app.core.tokens import build_grant, decode, issue_access_token, issue_id_token
from app.models import (
    AuthorizationCode,
    Membership,
    OAuthClient,
    RefreshToken,
    Subscription,
    User,
    UserStatus,
)

log = logging.getLogger("hynt.oauth")

bp = Blueprint("/oauth")
well_known = Blueprint("/.well-known")

SUPPORTED_SCOPES = ["openid", "profile", "email", "offline_access"]


# --------------------------------------------------------------------------- #
#  Discovery
# --------------------------------------------------------------------------- #
@well_known.get("/openid-configuration")
@endpoint
def discovery(request, db):
    """Standard OIDC metadata, so a platform can be configured with an issuer URL
    and nothing else."""
    base = config.ISSUER.rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "userinfo_endpoint": f"{base}/oauth/userinfo",
        "jwks_uri": f"{base}/.well-known/jwks.json",
        "introspection_endpoint": f"{base}/oauth/introspect",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "end_session_endpoint": f"{base}/oauth/logout",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": [config.JWT_ALG],
        "scopes_supported": SUPPORTED_SCOPES,
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "code_challenge_methods_supported": ["S256"],
        "claims_supported": [
            "sub", "iss", "aud", "exp", "iat", "email", "email_verified", "name",
            "org", "role", "rank", "perms", "plan", "ent", "lim", "tv", "sid",
        ],
    }


@well_known.get("/jwks.json")
@endpoint
def jwks_document(request, db):
    """Public keys. This is the only thing a platform needs to fetch from here,
    and it is cacheable for hours."""
    response = ok(keys.jwks(db))
    response.set_header("Cache-Control", "public, max-age=3600")
    return response


# --------------------------------------------------------------------------- #
#  Authorize
# --------------------------------------------------------------------------- #
class _RedirectError(Exception):
    """An OAuth error that is safe to hand back to the client's redirect_uri.

    Only raised once the redirect_uri has been validated against the registered
    list — before that, an error has to be rendered here, because bouncing to an
    unverified URI is exactly the open redirect this flow must not have.
    """

    def __init__(self, redirect_uri: str, error: str, description: str, state: str | None):
        super().__init__(error)
        self.redirect_uri = redirect_uri
        self.error = error
        self.description = description
        self.state = state

    def to_response(self) -> Response:
        params = {"error": self.error, "error_description": self.description}
        if self.state:
            params["state"] = self.state
        joiner = "&" if "?" in self.redirect_uri else "?"
        return Response.redirect(f"{self.redirect_uri}{joiner}{urlencode(params)}")


def _client_or_error(db, client_id: str | None) -> OAuthClient:
    if not client_id:
        raise ApiError(400, "invalid_request", "client_id is required.")
    client = db.scalar(
        select(OAuthClient).where(OAuthClient.client_id == client_id, OAuthClient.active.is_(True))
    )
    if client is None:
        raise ApiError(400, "invalid_client", "Unknown or disabled client.")
    return client


def _validate_redirect(client: OAuthClient, redirect_uri: str | None) -> str:
    """Exact string match against the registered list.

    Not a prefix or a host comparison: prefix matching on redirect URIs is the
    classic route from "open redirect" to "authorization code stolen".
    """
    if not redirect_uri:
        raise ApiError(400, "invalid_request", "redirect_uri is required.")
    if redirect_uri not in (client.redirect_uris or []):
        raise ApiError(400, "invalid_redirect_uri",
                       "redirect_uri is not registered for this client.")
    return redirect_uri


@bp.get("/authorize")
@endpoint
def authorize(request, db):
    client_id = query(request, "client_id")
    redirect_uri = query(request, "redirect_uri")
    state = query(request, "state")
    scope = query(request, "scope", "openid profile email") or "openid profile email"
    nonce = query(request, "nonce")
    prompt = query(request, "prompt", "") or ""
    response_type = query(request, "response_type", "code")
    challenge = query(request, "code_challenge")
    challenge_method = query(request, "code_challenge_method", "S256")

    client = _client_or_error(db, client_id)
    redirect_uri = _validate_redirect(client, redirect_uri)

    # From here on errors can safely go back to the client.
    try:
        if response_type != "code":
            raise _RedirectError(redirect_uri, "unsupported_response_type",
                                 "Only the authorization code flow is supported.", state)
        # PKCE is mandatory for every client, public or not. An authorization code
        # without a verifier is a bearer credential sitting in a URL and in browser
        # history.
        if not challenge:
            raise _RedirectError(redirect_uri, "invalid_request",
                                 "code_challenge is required (PKCE).", state)
        if challenge_method != "S256":
            raise _RedirectError(redirect_uri, "invalid_request",
                                 "Only the S256 code challenge method is supported.", state)

        ctx = current_context(request, db)

        if ctx is None:
            if "none" in prompt:
                # The silent-renewal path. The platform's hidden frame gets this
                # and knows to send the user to a real login.
                raise _RedirectError(redirect_uri, "login_required",
                                     "No active session.", state)
            return Response.redirect(_login_url(request))

        if "login" in prompt:
            # An explicit re-authentication request; ignore the live session.
            return Response.redirect(_login_url(request))

        user = ctx.user
        if user.status != UserStatus.ACTIVE:
            raise _RedirectError(redirect_uri, "access_denied", "This account is not active.", state)

        # Access to *this* platform is decided here, not by the platform itself.
        # A user with a live SSO session but no membership is signed in to Hynt
        # and still refused at terminal's door.
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.platform_id == client.platform_id,
                Membership.active.is_(True),
            )
        )
        if membership is None and not user.is_superadmin:
            audit.record(db, audit.AUTHORIZE_DENIED, actor_user_id=user.id,
                         platform_slug=client.platform.slug, ip=ctx.ip, agent=ctx.agent,
                         reason="no_membership")
            raise _RedirectError(
                redirect_uri, "access_denied",
                f"You do not have access to {client.platform.name}.", state,
            )

        now = datetime.now(timezone.utc)
        raw_code = new_secret(32)
        db.add(
            AuthorizationCode(
                code_hash=token_digest(raw_code),
                client_id=client.client_id,
                user_id=user.id,
                session_id=ctx.session.id,
                redirect_uri=redirect_uri,
                scope=scope,
                nonce=nonce,
                code_challenge=challenge,
                code_challenge_method=challenge_method,
                expires_at=now + timedelta(seconds=config.AUTH_CODE_TTL_SEC),
                created_at=now,
            )
        )
        audit.record(db, audit.AUTHORIZE_GRANTED, actor_user_id=user.id,
                     platform_slug=client.platform.slug, ip=ctx.ip, agent=ctx.agent,
                     client_id=client.client_id, silent="none" in prompt)

        params = {"code": raw_code}
        if state:
            params["state"] = state
        joiner = "&" if "?" in redirect_uri else "?"
        return Response.redirect(f"{redirect_uri}{joiner}{urlencode(params)}")

    except _RedirectError as exc:
        return exc.to_response()


def _login_url(request) -> str:
    """Send the browser to the accounts login page, carrying the original
    authorize request so it can be replayed verbatim after sign-in.

    ``request.query`` is a parsed dict, not the raw query string, so the
    authorize URL is rebuilt from it — interpolating the dict directly produces
    a Python repr in the URL and a login page that can never return the user
    anywhere.
    """
    params = dict(request.query or {})
    original = f"{config.ISSUER.rstrip('/')}/oauth/authorize?{urlencode(params)}"
    return f"{config.ACCOUNT_APP_URL.rstrip('/')}/login?{urlencode({'next': original})}"


# --------------------------------------------------------------------------- #
#  Token
# --------------------------------------------------------------------------- #
def _form_or_json(request) -> dict:
    """The token endpoint takes form encoding per the spec; the SPAs send JSON.
    Accept both rather than making every caller remember which."""
    try:
        if request.is_json():
            return body_json(request)
    except Exception:
        pass
    try:
        form = request.form()
        if form:
            return {k: v for k, v in dict(form).items()}
    except Exception:
        pass
    try:
        return body_json(request)
    except ApiError:
        return {}


def _oauth_error(error: str, description: str, status: int = 400) -> Response:
    return Response.json({"error": error, "error_description": description}, status=status)


def _authenticate_client(db, data: dict) -> OAuthClient:
    client = _client_or_error(db, data.get("client_id"))
    if not client.is_public:
        secret = data.get("client_secret") or ""
        if not client.client_secret_hash or not verify_password(secret, client.client_secret_hash):
            raise ApiError(401, "invalid_client", "Client authentication failed.")
    return client


@bp.post("/token")
@endpoint
def token(request, db):
    data = _form_or_json(request)
    grant_type = data.get("grant_type")

    if grant_type == "authorization_code":
        return _exchange_code(request, db, data)
    if grant_type == "refresh_token":
        return _exchange_refresh(request, db, data)
    return _oauth_error("unsupported_grant_type", f"grant_type '{grant_type}' is not supported.")


def _mint(db, user: User, client: OAuthClient, scope: str, session_id, nonce=None) -> dict:
    """Build the token response for one (user, platform) pair."""
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.platform_id == client.platform_id,
            Membership.active.is_(True),
        )
    )
    subscription = db.scalar(
        select(Subscription).where(
            Subscription.user_id == user.id, Subscription.platform_id == client.platform_id
        )
    )
    grant = build_grant(user, client.platform.slug, membership, subscription)
    access, expires_in = issue_access_token(db, grant, sso_session_id=session_id, scope=scope)

    payload = {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "scope": scope,
        # Not part of the OAuth response proper, but it saves every platform an
        # immediate /userinfo round-trip just to render the user's name.
        "platform": client.platform.slug,
        "role": grant.role,
        "plan": grant.plan,
    }
    if "openid" in scope.split():
        payload["id_token"] = issue_id_token(
            db, user, client.client_id, nonce=nonce, sso_session_id=session_id
        )
    return payload


def _exchange_code(request, db, data: dict) -> Response:
    try:
        client = _authenticate_client(db, data)
    except ApiError as exc:
        return _oauth_error(exc.code, exc.message, exc.status)

    code = data.get("code")
    verifier = data.get("code_verifier")
    redirect_uri = data.get("redirect_uri")

    if not code or not verifier:
        return _oauth_error("invalid_request", "code and code_verifier are required.")

    row = db.scalar(select(AuthorizationCode).where(AuthorizationCode.code_hash == token_digest(code)))
    if row is None:
        return _oauth_error("invalid_grant", "Authorization code is invalid.")

    now = datetime.now(timezone.utc)
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)

    if row.consumed_at is not None:
        # Replay. The code was already spent, so whoever is presenting it now is
        # not the party that obtained it — kill anything that came from it.
        db.execute(
            RefreshToken.__table__.update()
            .where(RefreshToken.session_id == row.session_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        audit.record(db, audit.TOKEN_REUSE_DETECTED, actor_user_id=row.user_id,
                     platform_slug=client.platform.slug, ip=client_ip(request),
                     client_id=client.client_id, kind="authorization_code")
        return _oauth_error("invalid_grant", "Authorization code has already been used.")

    if expires <= now:
        return _oauth_error("invalid_grant", "Authorization code has expired.")
    if row.client_id != client.client_id:
        return _oauth_error("invalid_grant", "Authorization code was issued to another client.")
    if redirect_uri and redirect_uri != row.redirect_uri:
        return _oauth_error("invalid_grant", "redirect_uri does not match the authorization request.")

    # PKCE: SHA-256 of the verifier must equal the challenge captured at
    # /authorize. This is what stops a stolen code being redeemed by anyone else.
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    if not constant_time_equals(computed, row.code_challenge):
        return _oauth_error("invalid_grant", "PKCE verification failed.")

    user = db.get(User, row.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        return _oauth_error("invalid_grant", "The account is no longer active.")

    row.consumed_at = now

    payload = _mint(db, user, client, row.scope, row.session_id, nonce=row.nonce)

    # A refresh token only for clients that asked for one and are not browser
    # SPAs; the SPAs renew silently against the SSO cookie instead.
    if "offline_access" in row.scope.split() and not client.is_public:
        raw_refresh = new_secret(40)
        db.add(
            RefreshToken(
                token_hash=token_digest(raw_refresh),
                user_id=user.id,
                client_id=client.client_id,
                session_id=row.session_id,
                scope=row.scope,
                expires_at=now + timedelta(seconds=config.REFRESH_TOKEN_TTL_SEC),
                created_at=now,
            )
        )
        payload["refresh_token"] = raw_refresh

    audit.record(db, audit.TOKEN_ISSUED, actor_user_id=user.id,
                 platform_slug=client.platform.slug, ip=client_ip(request),
                 client_id=client.client_id, grant="authorization_code")
    return ok(payload)


def _exchange_refresh(request, db, data: dict) -> Response:
    try:
        client = _authenticate_client(db, data)
    except ApiError as exc:
        return _oauth_error(exc.code, exc.message, exc.status)

    raw = data.get("refresh_token")
    if not raw:
        return _oauth_error("invalid_request", "refresh_token is required.")

    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_digest(raw)))
    if row is None:
        return _oauth_error("invalid_grant", "Refresh token is invalid.")

    now = datetime.now(timezone.utc)
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)

    if row.revoked_at is not None:
        # Rotation means a used token is dead. Seeing one again means it was
        # captured, so the whole chain for that session goes.
        db.execute(
            RefreshToken.__table__.update()
            .where(RefreshToken.session_id == row.session_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        audit.record(db, audit.TOKEN_REUSE_DETECTED, actor_user_id=row.user_id,
                     platform_slug=client.platform.slug, ip=client_ip(request),
                     client_id=client.client_id, kind="refresh_token")
        return _oauth_error("invalid_grant", "Refresh token has been revoked.")

    if expires <= now:
        return _oauth_error("invalid_grant", "Refresh token has expired.")
    if row.client_id != client.client_id:
        return _oauth_error("invalid_grant", "Refresh token was issued to another client.")

    # The SSO session is still the authority: signing out at accounts.hynt.one
    # must invalidate refresh tokens minted from that session too.
    if row.session_id is not None:
        from app.models import SsoSession

        sso = db.get(SsoSession, row.session_id)
        if sso is None or sso.revoked_at is not None:
            return _oauth_error("invalid_grant", "The originating session has ended.")

    user = db.get(User, row.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        return _oauth_error("invalid_grant", "The account is no longer active.")

    rotated = new_secret(40)
    replacement = RefreshToken(
        token_hash=token_digest(rotated),
        user_id=user.id,
        client_id=client.client_id,
        session_id=row.session_id,
        scope=row.scope,
        expires_at=now + timedelta(seconds=config.REFRESH_TOKEN_TTL_SEC),
        created_at=now,
    )
    db.add(replacement)
    db.flush()
    row.revoked_at = now
    row.replaced_by = replacement.id

    payload = _mint(db, user, client, row.scope, row.session_id)
    payload["refresh_token"] = rotated

    audit.record(db, audit.TOKEN_ISSUED, actor_user_id=user.id,
                 platform_slug=client.platform.slug, ip=client_ip(request),
                 client_id=client.client_id, grant="refresh_token")
    return ok(payload)


# --------------------------------------------------------------------------- #
#  Userinfo / introspect / revoke / logout
# --------------------------------------------------------------------------- #
def _bearer(request) -> str | None:
    header = request.get_header("authorization") or ""
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


@bp.get("/userinfo")
@endpoint
def userinfo(request, db):
    """OIDC userinfo. Present for spec completeness and for server-side clients;
    the SPAs read the same claims out of the token they already hold."""
    raw = _bearer(request)
    if not raw:
        return _oauth_error("invalid_token", "A bearer access token is required.", 401)

    claims = decode(db, raw)
    if claims is None or claims.get("typ") != "access":
        return _oauth_error("invalid_token", "The access token is invalid or expired.", 401)

    user = db.get(User, claims["sub"])
    if user is None or user.status != UserStatus.ACTIVE:
        return _oauth_error("invalid_token", "The account is no longer active.", 401)
    if claims.get("tv") != user.token_version:
        return _oauth_error("invalid_token", "The access token has been superseded.", 401)

    return {
        "sub": str(user.id),
        "email": user.email,
        "email_verified": user.email_verified,
        "name": user.full_name,
        "picture": user.avatar_url,
        "org": str(user.org_id),
        "role": claims.get("role"),
        "perms": claims.get("perms", []),
        "plan": claims.get("plan"),
    }


@bp.post("/introspect")
@endpoint
def introspect(request, db):
    """RFC 7662. For a platform that would rather ask than verify locally —
    correct, but a network hop per request, so the SDK does not use it."""
    data = _form_or_json(request)
    raw = data.get("token")
    if not raw:
        return {"active": False}

    claims = decode(db, raw)
    if claims is None:
        return {"active": False}

    user = db.get(User, claims.get("sub"))
    if user is None or user.status != UserStatus.ACTIVE or claims.get("tv") != user.token_version:
        return {"active": False}

    return {"active": True, **{k: v for k, v in claims.items() if k != "jti"}}


@bp.post("/revoke")
@endpoint
def revoke_token(request, db):
    """RFC 7009. Always answers 200, per the spec — telling a caller that a token
    they presented was already unknown is itself information."""
    data = _form_or_json(request)
    raw = data.get("token")
    if raw:
        row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_digest(raw)))
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
    return {"ok": True}


@bp.get("/logout")
@endpoint
def rp_logout(request, db):
    """RP-initiated single logout.

    Ends the SSO session, so the next silent renewal on every platform fails and
    each of them falls back to the login screen. Access tokens already issued
    stay valid until they expire — the price of local verification, and the
    reason the TTL is 15 minutes.
    """
    from app.core.http import build_cookie

    ctx = current_context(request, db)
    redirect_to = query(request, "post_logout_redirect_uri")
    client_id = query(request, "client_id")

    if ctx is not None:
        sessions.revoke(db, ctx.session)
        db.execute(
            RefreshToken.__table__.update()
            .where(RefreshToken.session_id == ctx.session.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        audit.record(db, audit.LOGOUT, actor_user_id=ctx.user.id, ip=ctx.ip, agent=ctx.agent,
                     rp_initiated=True)

    # Only bounce to a URI the client registered, for the same reason /authorize
    # validates redirect_uri.
    target = config.ACCOUNT_APP_URL
    if redirect_to and client_id:
        client = db.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))
        if client is not None and redirect_to in (client.post_logout_redirect_uris or []):
            target = redirect_to

    response = Response.redirect(target)
    response.set_header("Set-Cookie", build_cookie(config.COOKIE_NAME, "", max_age=0, delete=True))
    return response
