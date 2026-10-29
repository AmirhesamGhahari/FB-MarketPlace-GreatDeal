from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from fb_marketplace_api.errors import ApiError
from fb_marketplace_api.repository import WINDOW_DAYS, ListingSort, Repository, Window, get_repository
from fb_marketplace_api.schemas import (
    Envelope,
    ListingRow,
    PagedEnvelope,
    Pagination,
    ProductSeries,
    ProductSummary,
    SeriesPoint,
)

router = APIRouter(prefix="/v1")

MAX_PAGE = 30  # 30 pages x 20 = the first 600 listings of any sort order are reachable


@router.get("/products/{slug}", response_model=Envelope[ProductSummary])
def get_product(
    slug: Annotated[str, Path(max_length=100)],
    repo: Annotated[Repository, Depends(get_repository)],
) -> Envelope[ProductSummary]:
    row = repo.get_product_summary(slug)
    if row is None:
        raise ApiError(404, "product_not_found", f"No product with slug '{slug}'.")
    updated_at = row.pop("updated_at")
    return Envelope(data_as_of=updated_at, data=ProductSummary(**row))


@router.get("/products/{slug}/series", response_model=Envelope[ProductSeries])
def get_product_series(
    slug: Annotated[str, Path(max_length=100)],
    repo: Annotated[Repository, Depends(get_repository)],
) -> Envelope[ProductSeries]:
    rows = repo.get_product_series(slug)
    if not rows:
        raise ApiError(404, "product_not_found", f"No product with slug '{slug}'.")
    points = [SeriesPoint.model_validate(row) for row in rows]
    return Envelope(data_as_of=rows[0]["updated_at"], data=ProductSeries(slug=slug, series=points))


@router.get("/products/{slug}/listings", response_model=PagedEnvelope[list[ListingRow]])
def get_product_listings(
    slug: Annotated[str, Path(max_length=100)],
    repo: Annotated[Repository, Depends(get_repository)],
    window: Window = "30d",
    sort: ListingSort = "price_asc",
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
) -> PagedEnvelope[list[ListingRow]]:
    result = repo.get_product_listings(slug, WINDOW_DAYS[window], sort, page)
    if result is None:
        raise ApiError(404, "product_not_found", f"No product with slug '{slug}'.")
    total_items = result["total_items"]
    page_size = result["page_size"]
    return PagedEnvelope(
        data_as_of=result["data_as_of"],
        data=[ListingRow.model_validate(row) for row in result["rows"]],
        pagination=Pagination(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=min(math.ceil(total_items / page_size), MAX_PAGE),
        ),
    )
