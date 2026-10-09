from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from fb_marketplace_greatdeals.db.base import Base


class NotificationLog(Base):
    """One row per email attempt, sent or failed.

    raw_listing_ids records exactly which listings the attempt covered, so a failed attempt
    is still traceable to its listings (a failed attempt leaves deal_alerts unlinked).
    """

    __tablename__ = "notification_log"
    __table_args__ = (
        Index("idx_notification_created_at", "created_at"),
        Index("idx_notification_message_id", "message_id"),
        {"schema": "facebook"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(Text, nullable=False)          # "email"
    status: Mapped[str] = mapped_column(Text, nullable=False)           # "sent" | "failed"
    raw_listing_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    message_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # SNS MessageId when sent
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


class DealAlert(Base):
    """A listing selected for alerting, and whether the alert email has gone out.

    Only listings that passed the deal rules in transformed.fct_deal_candidates get a row.
    Listing details for the email are read from fct_deal_candidates by raw_listing_id.
    email_notification_id links to the notification_log row of the email that delivered it.
    """

    __tablename__ = "deal_alerts"
    __table_args__ = (
        # Notify reads only the alerts not emailed yet; this index stays tiny
        Index("idx_deal_alerts_unsent", "raw_listing_id", postgresql_where=text("email_sent_at IS NULL")),
        Index("idx_deal_alerts_email_notification_id", "email_notification_id"),
        Index("idx_deal_alerts_evaluated_at", "evaluated_at"),
        {"schema": "facebook"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    raw_listing_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    email_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    email_notification_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("facebook.notification_log.id"), nullable=True)
