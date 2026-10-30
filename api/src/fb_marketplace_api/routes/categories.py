from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from fb_marketplace_api.errors import ApiError
from fb_marketplace_api.repository import Repository, get_repository
from fb_marketplace_api.schemas import CategoryProductCard, CategoryProducts, CategorySummary, Envelope

router = APIRouter(prefix="/v1")


@router.get("/categories", response_model=Envelope[list[CategorySummary]])
def get_categories(
    repo: Annotated[Repository, Depends(get_repository)],
) -> Envelope[list[CategorySummary]]:
    result = repo.get_categories()
    if result is None:
        raise ApiError(503, "database_unavailable", "No categories are available.")
    return Envelope(
        data_as_of=result["data_as_of"],
        data=[CategorySummary.model_validate(row) for row in result["rows"]],
    )


@router.get("/categories/{category_key}/products", response_model=Envelope[CategoryProducts])
def get_category_products(
    category_key: Annotated[str, Path(max_length=100)],
    repo: Annotated[Repository, Depends(get_repository)],
) -> Envelope[CategoryProducts]:
    result = repo.get_category_products(category_key)
    if result is None:
        raise ApiError(404, "category_not_found", f"No category with key '{category_key}'.")
    return Envelope(
        data_as_of=result["data_as_of"],
        data=CategoryProducts(
            category_key=result["category_key"],
            category_name=result["category_name"],
            products=[CategoryProductCard.model_validate(row) for row in result["rows"]],
        ),
    )
