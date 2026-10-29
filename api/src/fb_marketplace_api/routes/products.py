from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from fb_marketplace_api.errors import ApiError
from fb_marketplace_api.repository import Repository, get_repository
from fb_marketplace_api.schemas import Envelope, ProductSeries, ProductSummary, SeriesPoint

router = APIRouter(prefix="/v1")


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
