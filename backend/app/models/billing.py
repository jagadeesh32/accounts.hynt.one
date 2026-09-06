"""Plans grant entitlements and limits. Access is role ∩ plan: a platform admin
on the free tier still does not get the paid feature."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import uuid_pk


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("platform_id", "slug", name="uq_plan_platform_slug"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    platform_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platforms.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(120))
    price_inr: Mapped[int] = mapped_column(Integer, default=0)     # paise-free: whole rupees
    interval: Mapped[str] = mapped_column(String(20), default="month")
    entitlements: Mapped[list] = mapped_column(JSONB, default=list)   # ["terminal.intraday"]
    limits: Mapped[dict] = mapped_column(JSONB, default=dict)         # {"scans_per_day": 1000}
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)  # auto-assigned on provisioning
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "platform_id", name="uq_subscription_user_platform"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platforms.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(20), default="active")   # active | past_due | cancelled
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user = relationship("User", back_populates="subscriptions")
    plan = relationship("Plan", lazy="selectin")
    platform = relationship("Platform", lazy="selectin")
