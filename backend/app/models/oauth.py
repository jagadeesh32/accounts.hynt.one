"""OAuth clients, one-shot authorization codes, signing keys, revocations."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import uuid_pk


class OAuthClient(Base):
    __tablename__ = "oauth_clients"

    id: Mapped[uuid.UUID] = uuid_pk()
    client_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    platform_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platforms.id", ondelete="CASCADE"))
    redirect_uris: Mapped[list] = mapped_column(JSONB, default=list)
    # SPAs are public clients: no secret, PKCE required. A confidential client
    # (a server-side integration) gets a secret hash here instead.
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    secret_hash: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthorizationCode(Base):
    """60-second, single-use, PKCE-bound. Stored hashed for the same reason
    sessions are: the row is not the credential."""

    __tablename__ = "authorization_codes"

    id: Mapped[uuid.UUID] = uuid_pk()
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(String(80), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    redirect_uri: Mapped[str] = mapped_column(String(500))
    code_challenge: Mapped[str] = mapped_column(String(200))
    code_challenge_method: Mapped[str] = mapped_column(String(10), default="S256")
    scope: Mapped[str] = mapped_column(String(200), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SigningKey(Base):
    """RSA keypair. Rotation activates a new row and marks the old one retired —
    the retired *public* key stays in the JWKS until every token it signed has
    expired, so rotation never invalidates live sessions."""

    __tablename__ = "signing_keys"

    id: Mapped[uuid.UUID] = uuid_pk()
    kid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    private_pem: Mapped[str] = mapped_column(Text)
    public_pem: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Revocation(Base):
    """The bridge between local verification and "revoke now". Platforms poll
    /api/v1/revocations every ~30s and refuse anything listed here."""

    __tablename__ = "revocations"

    id: Mapped[uuid.UUID] = uuid_pk()
    subject_type: Mapped[str] = mapped_column(String(20), index=True)   # user | session
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    reason: Mapped[str] = mapped_column(String(120), default="")
    # Entries older than the longest token lifetime are pruned: a token that
    # has already expired cannot be replayed, so listing it forever is waste.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
