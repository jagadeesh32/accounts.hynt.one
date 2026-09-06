"""Per-platform pricing plans and subscriptions.

Built now, charged later. The point of having it in the token from day one is
that a platform can gate a feature on ``plan`` without a second lookup, and the
day pricing goes live nothing about the token shape changes.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk


class BillingInterval(str, enum.Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"


class SubscriptionStatus(str, enum.Enum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    EXPIRED = "expired"


class Plan(Base, TimestampMixin):
    """A priced tier on one platform. ``code`` is what appears in the token."""

    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("platform_id", "code", name="uq_plans_platform_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    platform_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("platforms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Integer minor units. Floats and money do not belong in the same column.
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    interval: Mapped[BillingInterval] = mapped_column(
        Enum(BillingInterval, name="billing_interval", native_enum=False, length=16),
        nullable=False, default=BillingInterval.MONTHLY,
    )
    trial_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Marketing bullet points, rendered by the pricing page.
    features: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: Enforceable numbers, e.g. {"scans_per_day": 500}. Travels in the token so
    #: the platform can enforce a quota without asking this service.
    limits: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: Capability codes this plan unlocks, on top of whatever the role allows.
    #: Access is the intersection of role and plan: a platform admin on the free
    #: tier still does not get the paid feature.
    entitlements: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    platform: Mapped["object"] = relationship("Platform", back_populates="plans")


class Subscription(Base, TimestampMixin):
    """One user's standing on one platform.

    Scoped to the user rather than the org because today every org is one person;
    ``org_id`` is carried so that moving to seat-based org billing is a change of
    which column the query groups by, not a schema migration under load.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "platform_id", name="uq_subscriptions_user_platform"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("platforms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
    )

    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status", native_enum=False, length=16),
        nullable=False, default=SubscriptionStatus.ACTIVE,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_ref: Mapped[str | None] = mapped_column(String(160))  # payment provider id

    plan: Mapped[Plan] = relationship(lazy="joined")
    platform: Mapped["object"] = relationship("Platform", lazy="joined")

    @property
    def is_current(self) -> bool:
        return self.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING)
