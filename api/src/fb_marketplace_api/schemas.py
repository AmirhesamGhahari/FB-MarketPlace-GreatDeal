from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Generic, TypeVar
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel

T = TypeVar("T")

TORONTO = ZoneInfo("America/Toronto")
TorontoDatetime = Annotated[datetime, AfterValidator(lambda value: value.astimezone(TORONTO))]


class Envelope(BaseModel, Generic[T]):
    data_as_of: TorontoDatetime
    data: T


class LowestDeal(BaseModel):
    listing_id: str
    url: str
    price: float


class ProductSummary(BaseModel):
    """GET /v1/products/{slug}: flat, all mart_product_summary columns except updated_at."""

    slug: str
    display_name: str
    category_key: str
    as_of_date: date
    listings_30d: int | None
    avg_price_30d: float | None
    listings_7d: int | None
    avg_price_7d: float | None
    deal8_listings_30d: int | None
    deal8_avg_price_30d: float | None
    deal8_listings_7d: int | None
    deal8_avg_price_7d: float | None
    cutoff_price_cheapest_25pct_30d: float | None
    cutoff_price_cheapest_25pct_7d: float | None
    lowest_5_deals_30d: list[LowestDeal] | None
    lowest_5_deals_7d: list[LowestDeal] | None
    deal8_lowest_5_deals_30d: list[LowestDeal] | None
    deal8_lowest_5_deals_7d: list[LowestDeal] | None


class SeriesPoint(BaseModel):
    """One day of chart data (a row of mart_product_daily)."""

    stat_date: date
    listings_1d: int | None
    avg_price_1d: float | None
    avg_price_3d: float | None
    avg_price_7d: float | None
    avg_price_30d: float | None
    deal8_listings_1d: int | None
    deal8_avg_price_7d: float | None
    deal8_avg_price_30d: float | None
    lowest_3_deals_7d: list[LowestDeal] | None
    cutoff_price_cheapest_25pct_30d: float | None
    cutoff_price_cheapest_25pct_7d: float | None


class ProductSeries(BaseModel):
    """GET /v1/products/{slug}/series: up to 60 days, oldest first."""

    slug: str
    series: list[SeriesPoint]
