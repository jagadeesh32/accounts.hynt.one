"""Platforms, roles, permissions and per-platform membership.

The shape of the problem: one identity, several products, a different role in
each. So authority is a triple — (user, platform, role) — and that triple is the
:class:`Membership` row. A user with no membership for a platform has no access
to it at all, which is what makes adding a fourth platform a data change rather
than a code change.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk


class RoleCode(str, enum.Enum):
    """Ranked, because "is this user at least an admin" is asked far more often
    than "is this user exactly an admin"."""

    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    STAFF = "staff"
    USER = "user"


#: Higher outranks lower. Used by :func:`app.core.authz.has_at_least`.
ROLE_RANK: dict[str, int] = {
    RoleCode.SUPERADMIN.value: 40,
    RoleCode.ADMIN.value: 30,
    RoleCode.STAFF.value: 20,
    RoleCode.USER.value: 10,
}


class Platform(Base, TimestampMixin):
    """One of terminal / xterminal / intelligence — and whatever comes next.

    ``slug`` is the JWT audience. A token minted for ``terminal`` is rejected by
    xterminal's verifier, so a leaked token cannot be replayed sideways across
    the estate.
    """

    __tablename__ = "platforms"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    base_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    icon: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    roles: Mapped[list["Role"]] = relationship(back_populates="platform")
    plans: Mapped[list["Plan"]] = relationship(back_populates="platform")


class Permission(Base):
    """A named capability, e.g. ``terminal:scanner.run``.

    Permissions are what a platform should actually check. Roles are a bundle of
    them, so tightening one role does not mean hunting for every `role == "admin"`
    comparison scattered across three codebases.
    """

    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Role(Base, TimestampMixin):
    """A role scoped to a platform. ``platform_id`` NULL means a global role
    (only ``superadmin`` uses this today)."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("platform_id", "code", name="uq_roles_platform_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    platform_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("platforms.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    platform: Mapped[Platform | None] = relationship(back_populates="roles")
    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan", lazy="selectin"
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_pair"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    role_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )

    role: Mapped[Role] = relationship(back_populates="permissions")
    permission: Mapped[Permission] = relationship(lazy="joined")


class Membership(Base, TimestampMixin):
    """(user, platform) → role. The unit of access.

    ``extra_permissions`` is an escape hatch for the one user who needs a single
    capability beyond their role, so that granting it does not require inventing
    a whole new role that then has to be maintained forever.
    """

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "platform_id", name="uq_memberships_user_platform"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("platforms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    extra_permissions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    user: Mapped["object"] = relationship("User", back_populates="memberships")
    platform: Mapped[Platform] = relationship(lazy="joined")
    role: Mapped[Role] = relationship(lazy="joined")
