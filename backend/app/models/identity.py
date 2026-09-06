"""Organizations, users and the SSO session.

The user row is the single account across every Hynt platform. What a user may
*do* is not stored here — that lives on :class:`Membership`, one row per user
per platform, because the same person is legitimately an admin on one platform
and a plain user on another.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import INET, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    PENDING = "pending"      # invited, has not set a password yet
    SUSPENDED = "suspended"  # blocked by an admin; sessions are killed on transition


class Organization(Base, TimestampMixin):
    """A tenant. Every user belongs to exactly one, created implicitly on signup
    so that per-org billing has somewhere to attach later without a migration
    that has to invent owners for existing rows."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    billing_email: Mapped[str | None] = mapped_column(String(320))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    users: Mapped[list["User"]] = relationship(back_populates="organization")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )

    # Stored lowercased. Case-preserving email would let alice@ and Alice@ become
    # two accounts that both look correct to a human reading the admin list.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    avatar_url: Mapped[str | None] = mapped_column(Text)

    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status", native_enum=False, length=16),
        nullable=False, default=UserStatus.ACTIVE,
    )

    # A superadmin is above the per-platform role table entirely: they administer
    # the identity provider itself, including which platforms exist.
    is_superadmin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Bumped on password change, on "sign out everywhere" and on suspension.
    # Access tokens carry it, so a token minted before the bump is refused by the
    # platforms without any of them having to call back here.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    mfa_secret: Mapped[str | None] = mapped_column(Text)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped[Organization] = relationship(back_populates="users")
    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE


class SsoSession(Base):
    """The browser session at accounts.hynt.one.

    The cookie carries an opaque id whose SHA-256 is stored here — a database
    read of this table cannot be replayed as a login. Revoking a row is what
    makes single logout actually log the user out of all three platforms once
    their short-lived access token expires.
    """

    __tablename__ = "sso_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    user_agent: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(INET)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class PasswordReset(Base):
    """Single-use, hashed, and expiring. Kept as rows rather than as a signed
    stateless token so that using one can actually consume it."""

    __tablename__ = "password_resets"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LoginAttempt(Base):
    """Brute-force counter.

    In a table rather than a process dict because the throttle has to hold across
    workers; a per-process dict quietly multiplies the configured limit by the
    number of workers, which is the same as not having a throttle.
    """

    __tablename__ = "login_attempts"

    id: Mapped[uuid.UUID] = uuid_pk()
    # email|ip, so hammering one address from elsewhere cannot lock the real
    # owner out of their own account from their own machine.
    scope_key: Mapped[str] = mapped_column(String(400), nullable=False, index=True)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_failure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_failure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("ix_login_attempts_scope_unique", LoginAttempt.scope_key, unique=True)
