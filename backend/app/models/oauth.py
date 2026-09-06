"""OAuth 2.1 / OIDC storage: clients, authorization codes, refresh tokens, keys.

The three platforms are public clients (browser SPAs), so every one of them uses
authorization code + PKCE and holds no secret. Their backends never talk to this
service at request time — they verify RS256 signatures against the published
JWKS, which is why ``SigningKey`` lives here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk


class OAuthClient(Base, TimestampMixin):
    __tablename__ = "oauth_clients"

    id: Mapped[uuid.UUID] = uuid_pk()
    client_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    #: NULL for a public client. A secret shipped inside a browser bundle is not
    #: a secret, so the SPAs deliberately have none and rely on PKCE.
    client_secret_hash: Mapped[str | None] = mapped_column(Text)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    platform_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("platforms.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: Exact-match only. Prefix matching on redirect URIs is how open redirects
    #: turn into stolen authorization codes.
    redirect_uris: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    post_logout_redirect_uris: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    #: First-party apps we own; no consent screen is shown for them.
    trusted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    platform: Mapped["object"] = relationship("Platform", lazy="joined")


class AuthorizationCode(Base):
    """Single-use, 60-second, PKCE-bound. Stored hashed for the same reason
    sessions are: this table should be useless to anyone who reads it."""

    __tablename__ = "authorization_codes"

    id: Mapped[uuid.UUID] = uuid_pk()
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    client_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sso_sessions.id", ondelete="CASCADE")
    )

    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="")
    nonce: Mapped[str | None] = mapped_column(String(160))
    code_challenge: Mapped[str] = mapped_column(String(200), nullable=False)
    code_challenge_method: Mapped[str] = mapped_column(String(10), nullable=False, default="S256")

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RefreshToken(Base):
    """Rotating refresh token for confidential clients and native apps.

    The browser SPAs do not use these — they renew silently against the SSO
    cookie via ``prompt=none``, which keeps long-lived credentials out of
    ``localStorage`` entirely. ``replaced_by`` exists so that presenting an
    already-rotated token can be detected as theft and kill the whole chain.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sso_sessions.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="")

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))


class SigningKey(Base):
    """RSA keypair backing the JWKS.

    Rotation keeps old public keys published (``active=False``, not deleted) until
    every token they signed has expired; removing a key the moment it stops being
    used would invalidate live sessions across all three platforms at once.
    """

    __tablename__ = "signing_keys"

    id: Mapped[uuid.UUID] = uuid_pk()
    kid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    alg: Mapped[str] = mapped_column(String(10), nullable=False, default="RS256")
    private_pem: Mapped[str] = mapped_column(Text, nullable=False)
    public_jwk: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Append-only record of who did what.

    Written for every state change an administrator can make and every
    authentication decision. Deliberately has no update path.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = uuid_pk()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(60))
    target_id: Mapped[str | None] = mapped_column(String(120))
    platform_slug: Mapped[str | None] = mapped_column(String(64), index=True)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class Revocation(Base):
    """A published "stop trusting this" record.

    Access tokens are verified locally by each platform against the JWKS — that
    is what makes authorisation a signature check rather than a network call.
    The cost is that a token stays cryptographically valid until it expires, so
    suspending an account would otherwise take up to ``ACCESS_TOKEN_TTL_SEC`` to
    take effect.

    This table closes that window. Platforms poll ``/api/v1/revocations`` on a
    short interval and cache the result, so a revocation lands in seconds while
    still costing one small cached request per platform rather than a lookup per
    user request.

    ``platform_slug`` NULL means every platform. ``min_token_version`` is the
    lowest ``tv`` claim still acceptable for that user — a token carrying less
    than this is refused.
    """

    __tablename__ = "revocations"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_slug: Mapped[str | None] = mapped_column(String(64), index=True)
    min_token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reason: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    #: When this entry can be dropped: once every token it could match has
    #: expired on its own, the record is noise.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
