from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKeyConstraint, Index, Integer
from sqlalchemy import Numeric, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fb_marketplace_greatdeals.db.base import Base


class FbListingClassified(Base):
    """AI-enriched classification of a raw FB Marketplace listing.

    One row per raw listing (enforced via UNIQUE on raw_listing_id).
    Stores extracted product details and a deal-quality score from Gemini.
    Lives in the facebook schema as facebook.fb_listings_classified.
    """

    __tablename__ = "fb_listings_classified"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    raw_listing_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    fb_listing_id: Mapped[str] = mapped_column(Text, nullable=False)

    llm_model: Mapped[str] = mapped_column(Text, nullable=False)

    # What kind of listing this is
    listing_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Product identification (AI-extracted)
    product_brand: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    product_model: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    product_variant: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Condition
    condition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Specs
    storage_gb: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    battery_health_pct: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    cycle_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    warranty_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    includes_accessories: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    # Deal quality
    deal_score: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    is_great_deal: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    estimated_market_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    price_vs_market_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)

    # Relevance
    is_relevant_listing: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    confidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_llm_response: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["raw_listing_id"],
            ["facebook.fb_listings_raw.id"],
            name="fk_fb_classified_raw_listing_id",
        ),
        ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name="fk_fb_classified_category_id",
        ),
        Index("idx_fb_classified_raw_listing", "raw_listing_id", unique=True),
        Index("idx_fb_classified_category_deals", "category_id", "is_great_deal", "deal_score"),
        Index("idx_fb_classified_category_at", "category_id", "classified_at"),
        {"schema": "facebook"},
    )
