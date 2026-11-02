from __future__ import annotations

from itertools import groupby
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path

from fb_marketplace_api.errors import ApiError
from fb_marketplace_api.repository import Repository, get_repository
from fb_marketplace_api.schemas import DealRow, Envelope, ProductDeals

router = APIRouter(prefix="/v1")


def _group_by_product(rows: list[dict[str, Any]]) -> list[ProductDeals]:
    products = []
    for slug, group in groupby(rows, key=lambda row: row["slug"]):
        deals = list(group)
        products.append(
            ProductDeals(
                slug=slug,
                display_name=deals[0]["display_name"],
                category_key=deals[0]["category_key"],
                deals=[DealRow.model_validate(row) for row in deals],
            )
        )
    return products


@router.get("/deals/{category_key}/top", response_model=Envelope[list[ProductDeals]])
def get_category_top_deals(
    category_key: Annotated[str, Path(max_length=100)],
    repo: Annotated[Repository, Depends(get_repository)],
) -> Envelope[list[ProductDeals]]:
    result = repo.get_top_deals(category_key)
    if result is None:
        raise ApiError(404, "category_not_found", f"No category with key '{category_key}'.")
    return Envelope(data_as_of=result["data_as_of"], data=_group_by_product(result["rows"]))
