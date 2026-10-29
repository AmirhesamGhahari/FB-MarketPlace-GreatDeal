"""All SQL lives here; endpoints only call these functions.

Queries use named parameters (:slug) so the same SQL can run through SQLAlchemy locally and, later, through the
RDS Data API. Only the `serving` schema is queried.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal, Protocol

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql.elements import TextClause

from fb_marketplace_api.errors import ApiError
from fb_marketplace_api.settings import get_settings

PRODUCT_SUMMARY_SQL = text(
    """
    select slug, display_name, category_key, as_of_date,
           listings_30d, avg_price_30d, listings_7d, avg_price_7d,
           deal8_listings_30d, deal8_avg_price_30d, deal8_listings_7d, deal8_avg_price_7d,
           cutoff_price_cheapest_25pct_30d, cutoff_price_cheapest_25pct_7d,
           lowest_5_deals_30d, lowest_5_deals_7d,
           deal8_lowest_5_deals_30d, deal8_lowest_5_deals_7d,
           updated_at
    from serving.mart_product_summary
    where slug = :slug
    """
)

PRODUCT_SERIES_SQL = text(
    """
    select stat_date, listings_1d, avg_price_1d, avg_price_3d, avg_price_7d, avg_price_30d,
           deal8_listings_1d, deal8_avg_price_7d, deal8_avg_price_30d, lowest_3_deals_7d,
           cutoff_price_cheapest_25pct_30d, cutoff_price_cheapest_25pct_7d,
           updated_at
    from serving.mart_product_daily
    where slug = :slug
    order by stat_date
    """
)

Window = Literal["60d", "30d", "15d", "7d", "3d", "1d"]
WINDOW_DAYS = {"60d": 60, "30d": 30, "15d": 15, "7d": 7, "3d": 3, "1d": 1}
ListingSort = Literal["price_asc", "price_desc", "newest"]
PAGE_SIZE = 20

# Sort name -> ORDER BY text. Only these fixed strings are ever put into the SQL, never request text.
# Ties: price sorts show the newest listing first; every sort ends on fb_listing_id so pages are stable.
LISTING_ORDER_BY: dict[str, str] = {
    "price_asc": "price asc, listed_at desc, fb_listing_id",
    "price_desc": "price desc, listed_at desc, fb_listing_id",
    "newest": "listed_at desc, fb_listing_id",
}

LISTINGS_META_SQL = text(
    """
    select
        exists (select 1 from serving.dim_products where slug = :slug) as product_exists,
        (select count(*) from serving.mart_product_listings
          where slug = :slug and days_ago < :days) as total_items,
        coalesce(
            (select max(updated_at) from serving.mart_product_listings),
            (select updated_at from serving.dim_products where slug = :slug)
        ) as data_as_of
    """
)

LISTINGS_PAGE_SQL = {
    sort: text(
        f"""
        select fb_listing_id, listing_url, title, price, condition, storage_gb, color, location_city,
               listed_at, days_ago, avg_price_30d, avg_price_7d, price_diff_30d, price_diff_7d
        from serving.mart_product_listings
        where slug = :slug and days_ago < :days
        order by {order_by}
        limit :limit offset :offset
        """
    )
    for sort, order_by in LISTING_ORDER_BY.items()
}


class Repository(Protocol):
    def get_product_summary(self, slug: str) -> dict[str, Any] | None:
        """One summary row (including `updated_at`), or None for an unknown slug."""

    def get_product_series(self, slug: str) -> list[dict[str, Any]]:
        """Daily rows (including `updated_at`), oldest first; an empty list for an unknown slug."""

    def get_product_listings(
        self, slug: str, window_days: int, sort: ListingSort, page: int
    ) -> dict[str, Any] | None:
        """None for an unknown slug; otherwise {"data_as_of", "total_items", "page_size", "rows"} (rows may be empty)."""


@lru_cache
def _engine() -> Engine:
    settings = get_settings()
    if not settings.database_url:
        raise ApiError(503, "database_unavailable", "Database is not configured.")
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.db_connect_timeout},
    )


class SqlAlchemyRepository:
    def _query(self, sql: TextClause, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            with _engine().connect() as conn:
                return [dict(row) for row in conn.execute(sql, params).mappings()]
        except OperationalError as exc:
            raise ApiError(503, "database_unavailable", "Database is unavailable.") from exc

    def get_product_summary(self, slug: str) -> dict[str, Any] | None:
        rows = self._query(PRODUCT_SUMMARY_SQL, {"slug": slug})
        return rows[0] if rows else None

    def get_product_series(self, slug: str) -> list[dict[str, Any]]:
        return self._query(PRODUCT_SERIES_SQL, {"slug": slug})

    def get_product_listings(
        self, slug: str, window_days: int, sort: ListingSort, page: int
    ) -> dict[str, Any] | None:
        meta = self._query(LISTINGS_META_SQL, {"slug": slug, "days": window_days})[0]
        if not meta["product_exists"]:
            return None
        total_items = meta["total_items"]
        offset = (page - 1) * PAGE_SIZE
        rows: list[dict[str, Any]] = []
        if offset < total_items:
            rows = self._query(
                LISTINGS_PAGE_SQL[sort],
                {"slug": slug, "days": window_days, "limit": PAGE_SIZE, "offset": offset},
            )
        return {"data_as_of": meta["data_as_of"], "total_items": total_items, "page_size": PAGE_SIZE, "rows": rows}


def get_repository() -> Repository:
    return SqlAlchemyRepository()
