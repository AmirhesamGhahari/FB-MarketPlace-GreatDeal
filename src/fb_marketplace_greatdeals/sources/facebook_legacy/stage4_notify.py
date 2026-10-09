from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from loguru import logger
from sqlalchemy import text

from fb_marketplace_greatdeals.config import settings
from fb_marketplace_greatdeals.db.engine import SessionLocal
from fb_marketplace_greatdeals.sources.facebook_legacy.notifiers import build_email, send_email

_RULES = (
    "hit_tenth_cheapest_7d",
    "hit_tenth_cheapest_30d",
    "hit_cheapest_decile_7d",
    "hit_cheapest_decile_30d",
    "deal8_hit_tenth_cheapest_7d",
    "deal8_hit_tenth_cheapest_30d",
    "deal8_hit_cheapest_decile_7d",
    "deal8_hit_cheapest_decile_30d",
)
_BENCHMARKS = (
    "tenth_cheapest_price_7d", "tenth_cheapest_price_30d",
    "cutoff_price_cheapest_10pct_7d", "cutoff_price_cheapest_10pct_30d",
    "deal8_tenth_cheapest_price_7d", "deal8_tenth_cheapest_price_30d",
    "deal8_cutoff_price_cheapest_10pct_7d", "deal8_cutoff_price_cheapest_10pct_30d",
)

_ANY_HIT = " OR ".join(f"c.{rule}" for rule in _RULES)
_PASSED = f"c.skip_reason IS NULL AND ({_ANY_HIT})"

_DEAL_COLUMNS = ", ".join(f"c.{col}" for col in (
    "fb_listing_id", "listing_url", "title", "product_model", "price",
    "deal_score", "estimated_market_value", "condition", "location_city",
    *_BENCHMARKS,
    *_RULES,
))


@dataclass
class NotifyResult:
    status: str = "completed"
    new_alerts: int = 0
    emailed: int = 0
    error: Optional[str] = None


def _add_new_alerts(session) -> int:
    """Insert alerts for passing candidates. The caller commits (or rolls back).

    A listing is skipped only if it already has an alert at the same or a lower price, so a new
    version that qualifies at a lower price gets a new alert.
    """
    result = session.execute(text(f"""
        INSERT INTO facebook.deal_alerts (fb_listing_id, raw_listing_id, price)
        SELECT c.fb_listing_id, c.raw_listing_id, c.price
        FROM transformed.fct_deal_candidates c
        WHERE {_PASSED}
          AND NOT EXISTS (
              SELECT 1 FROM facebook.deal_alerts a
              WHERE a.fb_listing_id = c.fb_listing_id AND a.price <= c.price
          )
        ON CONFLICT (fb_listing_id, price) DO NOTHING
    """))
    return result.rowcount or 0


def _unsent_alerts(session) -> list[dict]:
    """The latest unsent alert per listing, with the listing's details from fct_deal_candidates.

    previous_price is the lowest price the listing was alerted at before this alert.
    """
    rows = session.execute(text(f"""
        SELECT DISTINCT ON (a.fb_listing_id)
               a.id AS alert_id,
               (SELECT min(p.price) FROM facebook.deal_alerts p
                WHERE p.fb_listing_id = a.fb_listing_id AND p.id < a.id) AS previous_price,
               {_DEAL_COLUMNS}
        FROM facebook.deal_alerts a
        JOIN transformed.fct_deal_candidates c ON c.fb_listing_id = a.fb_listing_id
        WHERE a.email_sent_at IS NULL
        ORDER BY a.fb_listing_id, a.id DESC
    """)).mappings().all()
    deals = [dict(r) for r in rows]
    deals.sort(key=lambda d: (-(d["deal_score"] or 0), d["price"]))
    return deals


def run(dry_run: bool = True) -> NotifyResult:
    result = NotifyResult()

    if not dry_run and not settings.deal_alerts_topic_arn:
        raise RuntimeError("DEAL_ALERTS_TOPIC_ARN is not set; cannot send deal alerts")

    with SessionLocal() as session:
        result.new_alerts = _add_new_alerts(session)
        deals = _unsent_alerts(session)
        logger.info(f"[Notify] {result.new_alerts} new alert(s), {len(deals)} to email")

        if dry_run:
            session.rollback()
            result.emailed = len(deals)
            if deals:
                subject, body = build_email(deals)
                logger.info(f"[Notify] dry run, email would be:\nSubject: {subject}\n\n{body}")
            return result

        session.commit()
        if not deals:
            return result

        try:
            message_id = send_email(deals)
        except Exception as exc:  # noqa: BLE001 — any send failure must leave the alerts unsent
            logger.error(f"[Notify] email failed: {exc}")
            session.execute(
                text("""
                    INSERT INTO facebook.notification_log (channel, status, listing_count, error)
                    VALUES ('email', 'failed', :count, :error)
                """),
                {"count": len(deals), "error": str(exc)[:1000]},
            )
            session.commit()
            result.status = "failed"
            result.error = str(exc)
            return result

        # The log row and the alert updates commit together, so an alert is never marked
        # sent without its log row (or the reverse).
        log_id = session.execute(
            text("""
                INSERT INTO facebook.notification_log (channel, status, listing_count, message_id)
                VALUES ('email', 'sent', :count, :message_id)
                RETURNING id
            """),
            {"count": len(deals), "message_id": message_id},
        ).scalar_one()
        session.execute(
            text("""
                UPDATE facebook.deal_alerts
                SET email_sent_at = now(), email_notification_id = :log_id
                WHERE email_sent_at IS NULL AND fb_listing_id = ANY(:listing_ids)
            """),
            {"log_id": log_id, "listing_ids": [d["fb_listing_id"] for d in deals]},
        )
        session.commit()
        result.emailed = len(deals)
        logger.info(f"[Notify] emailed {len(deals)} listing(s)")

    return result
