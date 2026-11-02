"""All SQL lives here; endpoints only call these functions.

Queries use named parameters (:slug) so the same SQL can run through SQLAlchemy locally and, later, through the
RDS Data API. Only the `serving` schema is queried.
"""
from __future__ import annotations

import time
from functools import lru_cache
from typing import Any, Literal, Protocol

from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
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

CATEGORIES_SQL = text(
    """
    select category_key, category_name, brand, count(*) as product_count, max(updated_at) as data_as_of
    from serving.dim_products
    group by category_key, category_name, brand
    order by category_key
    """
)

CATEGORY_PRODUCTS_SQL = text(
    """
    select p.slug, p.display_name, p.category_key, p.category_name,
           s.listings_30d, s.avg_price_30d, s.avg_price_7d, s.cutoff_price_cheapest_25pct_30d,
           p.updated_at as data_as_of
    from serving.dim_products as p
    left join serving.mart_product_summary as s on s.slug = p.slug
    where p.category_key = :category_key
    order by p.display_name
    """
)


DEALS_META_SQL = text(
    """
    select
        exists (select 1 from serving.dim_products where category_key = :category_key) as category_exists,
        (select max(updated_at) from serving.mart_top_deals) as data_as_of
    """
)

DEALS_BY_CATEGORY_SQL = text(
    """
    select slug, display_name, category_key, deal_rank, fb_listing_id, title, price, listing_url,
           location_city, listed_at, condition, avg_price_30d, price_diff_30d, cutoff_price_cheapest_25pct_30d
    from serving.mart_top_deals
    where category_key = :category_key
    order by display_name, slug, deal_rank
    """
)


class Repository(Protocol):
    def get_product_summary(self, slug: str) -> dict[str, Any] | None:
        """One summary row (including `updated_at`), or None for an unknown slug."""

    def get_product_series(self, slug: str) -> list[dict[str, Any]]:
        """Daily rows (including `updated_at`), oldest first; an empty list for an unknown slug."""

    def get_product_listings(
        self, slug: str, window_days: int, sort: ListingSort, page: int
    ) -> dict[str, Any] | None:
        """None for an unknown slug; otherwise {"data_as_of", "total_items", "page_size", "rows"} (rows may be empty)."""

    def get_categories(self) -> dict[str, Any] | None:
        """{"data_as_of", "rows"} with one row per catalog category; None if the catalog is empty."""

    def get_category_products(self, category_key: str) -> dict[str, Any] | None:
        """None for an unknown category; otherwise {"data_as_of", "category_key", "category_name", "rows"}."""

    def get_top_deals(self, category_key: str) -> dict[str, Any] | None:
        """None if the category is not in the catalog; otherwise {"data_as_of", "rows"}: flat deal rows
        ordered by product, then rank (rows may be empty)."""


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


# A paused Aurora cluster needs ~10-15 s to resume. Worst case (every attempt hangs for the full connect timeout):
# 3 x 5 s + 2 x 4 s = 23 s, which stays under API Gateway's 30 s limit. Do not raise these without redoing that sum.
CONNECT_MAX_ATTEMPTS = 3
CONNECT_RETRY_DELAY_SECONDS = 4
RESUMING_RETRY_AFTER_SECONDS = "15"


def _connect_with_retry() -> Connection:
    """Open a connection, retrying connection failures (not query failures).

    OperationalError only says "could not connect"; it cannot tell a waking cluster from a down one (or a wrong
    password or a blocked network). After the last attempt the failure is reported as `database_resuming` anyway,
    and the real cause is logged so it can be found in the logs."""
    for attempt in range(1, CONNECT_MAX_ATTEMPTS + 1):
        try:
            return _engine().connect()
        except OperationalError as exc:
            logger.warning(f"[DB] Connection attempt {attempt}/{CONNECT_MAX_ATTEMPTS} failed: {exc}")
            if attempt == CONNECT_MAX_ATTEMPTS:
                raise ApiError(
                    503,
                    "database_resuming",
                    "The database is not reachable right now (it may be starting up). Please retry in a few seconds.",
                    headers={"Retry-After": RESUMING_RETRY_AFTER_SECONDS},
                ) from exc
            time.sleep(CONNECT_RETRY_DELAY_SECONDS)


class SqlAlchemyRepository:
    def _query(self, sql: TextClause, params: dict[str, Any]) -> list[dict[str, Any]]:
        conn = _connect_with_retry()
        try:
            with conn:
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

    def get_categories(self) -> dict[str, Any] | None:
        rows = self._query(CATEGORIES_SQL, {})
        if not rows:
            return None
        return {"data_as_of": rows[0]["data_as_of"], "rows": rows}

    def get_category_products(self, category_key: str) -> dict[str, Any] | None:
        rows = self._query(CATEGORY_PRODUCTS_SQL, {"category_key": category_key})
        if not rows:
            return None
        first = rows[0]
        return {
            "data_as_of": first["data_as_of"],
            "category_key": first["category_key"],
            "category_name": first["category_name"],
            "rows": rows,
        }

    def get_top_deals(self, category_key: str) -> dict[str, Any] | None:
        meta = self._query(DEALS_META_SQL, {"category_key": category_key})[0]
        if not meta["category_exists"]:
            return None
        if meta["data_as_of"] is None:
            raise ApiError(503, "database_unavailable", "No deals data is available.")
        rows = self._query(DEALS_BY_CATEGORY_SQL, {"category_key": category_key})
        return {"data_as_of": meta["data_as_of"], "rows": rows}


def get_repository() -> Repository:
    return SqlAlchemyRepository()
