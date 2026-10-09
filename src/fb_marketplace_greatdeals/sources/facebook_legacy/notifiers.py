"""Deal digest email, sent through an SNS topic that has an email subscription."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from fb_marketplace_greatdeals.config import settings

Deal = Mapping[str, Any]

# Rule column -> label shown in the email
RULE_LABELS = {
    "hit_tenth_cheapest_7d": "10th-cheapest 7d",
    "hit_cheapest_decile_30d": "cheapest-10% 30d",
    "deal8_hit_tenth_cheapest_7d": "score8 10th-cheapest 7d",
    "deal8_hit_cheapest_decile_30d": "score8 cheapest-10% 30d",
}


def _money(value: Any) -> str:
    return "n/a" if value is None else f"${float(value):,.0f}"


def _rules(deal: Deal) -> str:
    return ", ".join(label for column, label in RULE_LABELS.items() if deal[column])


def build_email(deals: Sequence[Deal]) -> tuple[str, str]:
    subject = f"FB Deals: {len(deals)} new"
    blocks = []
    for deal in deals:
        title = deal["title"] or deal["product_model"] or deal["fb_listing_id"]
        blocks.append(
            f"{title}\n"
            f"  Price: {_money(deal['price'])} "
            f"(market {_money(deal['estimated_market_value'])}, score {deal['deal_score']})\n"
            f"  Rules hit: {_rules(deal)}\n"
            f"  Benchmarks: 10th cheapest 7d {_money(deal['tenth_cheapest_price_7d'])}, "
            f"cheapest-10% cutoff 30d {_money(deal['cutoff_price_cheapest_10pct_30d'])}\n"
            f"  Score 8+ benchmarks: 10th cheapest 7d {_money(deal['deal8_tenth_cheapest_price_7d'])}, "
            f"cheapest-10% cutoff 30d {_money(deal['deal8_cutoff_price_cheapest_10pct_30d'])}\n"
            f"  {deal['condition'] or ''} {deal['location_city'] or ''}\n"
            f"  {deal['listing_url'] or ''}"
        )
    return subject, "\n\n".join(blocks)


def send_email(deals: Sequence[Deal]) -> str:
    """Publish one digest and return the SNS MessageId. Raises on failure so the caller leaves the listings unsent."""
    import boto3

    subject, body = build_email(deals)
    response = boto3.client("sns").publish(
        TopicArn=settings.deal_alerts_topic_arn,
        Subject=subject[:100],
        Message=body,
    )
    return response["MessageId"]
