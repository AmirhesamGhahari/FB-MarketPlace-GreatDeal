from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fb_marketplace_greatdeals.db.base import Base


class Category(Base):
    """Product category / search registry.

    Each row represents one product family being tracked on FB Marketplace
    (e.g. iphone, macbook, ps5). category_key matches the YAML config filename.
    """

    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    category_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    category_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    brand: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
