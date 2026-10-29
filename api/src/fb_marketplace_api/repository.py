"""All SQL lives here; endpoints only call these functions.

Queries use named parameters (:slug) so the same SQL can run through SQLAlchemy locally and, later, through the
RDS Data API. Only the `serving` schema is queried.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

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


class Repository(Protocol):
    def get_product_summary(self, slug: str) -> dict[str, Any] | None:
        """One summary row (including `updated_at`), or None for an unknown slug."""

    def get_product_series(self, slug: str) -> list[dict[str, Any]]:
        """Daily rows (including `updated_at`), oldest first; an empty list for an unknown slug."""


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


def get_repository() -> Repository:
    return SqlAlchemyRepository()
