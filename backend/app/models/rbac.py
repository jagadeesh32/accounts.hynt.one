"""Platforms, roles and the (user, platform, role) triple that is authority here."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import uuid_pk


class Platform(Base):
    __tablename__ = "platforms"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True)   # terminal | xterminal | intelligence
    name: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(String(400), default="")
    icon: Mapped[str] = mapped_column(String(16), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Role(Base):
    """Roles are per-platform. `rank` is what stops an admin minting a superadmin:
    you may never grant a role whose rank is >= your own."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("platform_id", "slug", name="uq_role_platform_slug"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    platform_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platforms.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(120))
    rank: Mapped[int] = mapped_column(Integer, default=10)
    # ["terminal:scanner.run", ...] — flat strings, namespaced by platform slug.
    permissions: Mapped[list] = mapped_column(JSONB, default=list)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "platform_id", name="uq_membership_user_platform"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platforms.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="memberships")
    platform = relationship("Platform", lazy="selectin")
    role = relationship("Role", lazy="selectin")
