"""Deal digest email, sent through an SNS topic that has an email subscription."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from fb_marketplace_greatdeals.config import settings

Deal = Mapping[str, Any]

# Max listings per email, and max characters of a listing title shown in it
MAX_LISTINGS_PER_EMAIL = 50
TITLE_MAX_CHARS = 90

# fct_products_daily columns shown under each listing
BENCHMARK_COLUMNS = (
    "avg_market_value_30d",
    *(f"{prefix}{metric}_{w}d"
      for w in (30, 7, 3, 1)
      for prefix, metric in (
          ("", "listings"), ("", "avg_price"), ("", "cutoff_price_cheapest_25pct"), ("", "lowest_5_deals"),
          ("deal8_", "listings"), ("deal8_", "avg_price"), ("deal8_", "cutoff_price_cheapest_25pct"),
          ("good_condition_", "count"), ("good_condition_", "avg"),
      )),
)


def _money(value: Any) -> str:
    return "n/a" if value is None else f"${float(value):,.0f}"


def _short(text: str) -> str:
    """First TITLE_MAX_CHARS characters of a title."""
    return text if len(text) <= TITLE_MAX_CHARS else text[:TITLE_MAX_CHARS] + "..."


def build_email(deals: Sequence[Deal], part: int = 1, parts: int = 1) -> tuple[str, str]:
    subject = f"FB Deals: {len(deals)} new"
    if parts > 1:
        subject += f" (email {part} of {parts})"
    blocks = []
    for deal in deals:
        title = _short(deal["title"] or deal["product_model"] or deal["fb_listing_id"])
        price_line = f"  Price: {_money(deal['price'])}"
        if deal["previous_price"] is not None:
            price_line += f" (dropped from {_money(deal['previous_price'])})"
        price_line += f" (market {_money(deal['estimated_market_value'])}, score {deal['deal_score']})"
        benchmarks = "\n".join(f"    {col}: {deal[col]}" for col in BENCHMARK_COLUMNS)
        blocks.append(
            f"{title}\n"
            f"{price_line}\n"
            f"  {deal['product_model']} | {deal['condition'] or ''} | {deal['location_city'] or ''} | listed {deal['listed_at']}\n"
            f"  Benchmarks:\n{benchmarks}\n"
            f"  {deal['listing_url'] or ''}"
        )
    return subject, "\n\n".join(blocks)


def send_email(deals: Sequence[Deal], part: int = 1, parts: int = 1) -> str:
    """Publish one email and return the SNS MessageId. Raises on failure so the caller leaves the listings unsent."""
    import boto3

    subject, body = build_email(deals, part, parts)
    response = boto3.client("sns").publish(
        TopicArn=settings.deal_alerts_topic_arn,
        Subject=subject[:100],
        Message=body,
    )
    return response["MessageId"]
