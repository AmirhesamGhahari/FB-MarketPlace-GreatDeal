from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from fb_marketplace_greatdeals.db.base import Base


class NotificationLog(Base):

    __tablename__ = "notification_log"
    __table_args__ = (
        Index("idx_notification_created_at", "created_at"),
        Index("idx_notification_message_id", "message_id"),
        {"schema": "facebook"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(Text, nullable=False)          # "email"
    status: Mapped[str] = mapped_column(Text, nullable=False)           # "sent" | "failed"
    listing_count: Mapped[int] = mapped_column(Integer, nullable=False)
    message_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # SNS MessageId when sent
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


class DealAlert(Base):

    __tablename__ = "deal_alerts"
    __table_args__ = (
        UniqueConstraint("fb_listing_id", "price", name="uq_deal_alerts_listing_price"),
        # Notify reads only the alerts not emailed yet; this index stays tiny
        Index("idx_deal_alerts_unsent", "id", postgresql_where=text("email_sent_at IS NULL")),
        Index("idx_deal_alerts_raw_listing_id", "raw_listing_id"),
        Index("idx_deal_alerts_email_notification_id", "email_notification_id"),
        Index("idx_deal_alerts_evaluated_at", "evaluated_at"),
        {"schema": "facebook"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fb_listing_id: Mapped[str] = mapped_column(Text, nullable=False)
    raw_listing_id: Mapped[int] = mapped_column(BigInteger, nullable=False)   # version that triggered the alert
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)    # price at alert time

    # When the listing was selected for alerting
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    email_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    email_notification_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("facebook.notification_log.id"), nullable=True)
