from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKeyConstraint, Index
from sqlalchemy import Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fb_marketplace_greatdeals.db.base import Base


class FbListingRaw(Base):
    """Raw CDC record from a Facebook Marketplace scrape run.

    One row per scraped version of a listing. Current version has valid_to IS NULL.
    Keyed on (category_id, fb_listing_id) for CDC uniqueness.
    Lives in the facebook schema as facebook.fb_listings_raw.
    """

    __tablename__ = "fb_listings_raw"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category_key: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    fb_listing_id: Mapped[str] = mapped_column(Text, nullable=False)
    listing_url: Mapped[str] = mapped_column(Text, nullable=False)
    seller_profile_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    location_city: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_urls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    is_sold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Structured fields from Apify payload (no LLM needed)
    search_query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fb_condition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivery_types: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    is_highly_rated_seller: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    original_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    listed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # CDC timestamps — valid_to IS NULL means this is the current version
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(["category_id"], ["categories.id"], name="fk_fb_listing_raw_category_id"),
        ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], name="fk_fb_listing_raw_run_id"),
        Index("idx_fb_listing_raw_category_listing", "category_id", "fb_listing_id"),
        Index("idx_fb_listing_raw_category_listed_at", "category_id", "listed_at"),
        Index("idx_fb_listing_raw_run", "pipeline_run_id"),
        Index(
            "idx_fb_listing_raw_current",
            "category_id",
            "fb_listing_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
        {"schema": "facebook"},
    )
