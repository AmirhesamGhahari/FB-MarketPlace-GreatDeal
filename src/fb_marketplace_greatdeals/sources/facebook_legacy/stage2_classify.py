from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
from typing import Optional

from loguru import logger
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from fb_marketplace_greatdeals.db.engine import SessionLocal
from fb_marketplace_greatdeals.db.models.fb_listing_classified import FbListingClassified
from fb_marketplace_greatdeals.db.models.pipeline_tables import PipelineRun
from fb_marketplace_greatdeals.sources.facebook_legacy.gemini import classify_batch

BATCH_SIZE = 40
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 4

_MODEL_NAME = "gemini-3.5-flash-lite"

_COUNT_ALL = text("""
    SELECT COUNT(*) FROM facebook.fb_listings_raw
    WHERE valid_to IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM facebook.fb_listings_classified
          WHERE raw_listing_id = facebook.fb_listings_raw.id
      )
""")

_COUNT_CATEGORY = text("""
    SELECT COUNT(*) FROM facebook.fb_listings_raw
    WHERE valid_to IS NULL
      AND category_id = :category_id
      AND NOT EXISTS (
          SELECT 1 FROM facebook.fb_listings_classified
          WHERE raw_listing_id = facebook.fb_listings_raw.id
      )
""")

_FETCH_ALL = text("""
    SELECT id, fb_listing_id, category_id, title, description, price, search_query
    FROM facebook.fb_listings_raw
    WHERE valid_to IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM facebook.fb_listings_classified
          WHERE raw_listing_id = facebook.fb_listings_raw.id
      )
      AND id NOT IN :exclude_ids
    ORDER BY id
    LIMIT :limit
""").bindparams(bindparam("exclude_ids", expanding=True))

_FETCH_CATEGORY = text("""
    SELECT id, fb_listing_id, category_id, title, description, price, search_query
    FROM facebook.fb_listings_raw
    WHERE valid_to IS NULL
      AND category_id = :category_id
      AND NOT EXISTS (
          SELECT 1 FROM facebook.fb_listings_classified
          WHERE raw_listing_id = facebook.fb_listings_raw.id
      )
      AND id NOT IN :exclude_ids
    ORDER BY id
    LIMIT :limit
""").bindparams(bindparam("exclude_ids", expanding=True))


@dataclass
class ClassifyResult:
    run_id: uuid.UUID
    status: str
    total: int = 0
    classified: int = 0
    errors: int = 0


def run(category_id: Optional[uuid.UUID] = None, category_key: Optional[str] = None) -> ClassifyResult:
    """Classify all unclassified current-version raw listings via Gemini.

    Pass category_id to restrict to one category, or omit to classify across all.
    Idempotent: records already in fb_listings_classified are skipped via NOT EXISTS.
    Failed batches are retried on the next run.
    """
    with SessionLocal() as session:
        db_run = _create_run(session, category_key, category_id=category_id)
        result = ClassifyResult(run_id=db_run.id, status="completed")

        if category_id:
            total = session.execute(_COUNT_CATEGORY, {"category_id": str(category_id)}).scalar() or 0
        else:
            total = session.execute(_COUNT_ALL).scalar() or 0

        result.total = total

        if total == 0:
            logger.info("[Classify] No unclassified listings — nothing to do")
            _finish_run(session, db_run, result)
            return result

        logger.info(f"[Classify] {total} listings to classify in batches of {BATCH_SIZE}")

        exclude_ids: list = []
        while True:
            fetch_params: dict = {"limit": BATCH_SIZE, "exclude_ids": exclude_ids}
            if category_id:
                fetch_params["category_id"] = str(category_id)
                rows = session.execute(_FETCH_CATEGORY, fetch_params).fetchall()
            else:
                rows = session.execute(_FETCH_ALL, fetch_params).fetchall()

            if not rows:
                break

            listings = [
                {
                    "id": row.id,
                    "search_query": row.search_query,
                    "title": row.title,
                    "description": row.description,
                    "price": float(row.price) if row.price is not None else None,
                }
                for row in rows
            ]

            success = False
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    classifications = classify_batch(listings)
                    for row, clf in zip(rows, classifications):
                        deal_score = clf.get("deal_score")
                        emv = clf.get("estimated_market_value")
                        pvm = clf.get("price_vs_market_pct")
                        bh = clf.get("battery_health_pct")
                        cc = clf.get("cycle_count")
                        session.add(FbListingClassified(
                            raw_listing_id=row.id,
                            category_id=row.category_id,
                            fb_listing_id=row.fb_listing_id,
                            llm_model=_MODEL_NAME,
                            listing_type=clf.get("listing_type"),
                            product_brand=clf.get("product_brand"),
                            product_model=clf.get("product_model"),
                            product_variant=clf.get("product_variant"),
                            condition=clf.get("condition"),
                            storage_gb=clf.get("storage_gb"),
                            color=clf.get("color"),
                            battery_health_pct=int(bh) if bh is not None else None,
                            cycle_count=int(cc) if cc is not None else None,
                            warranty_notes=clf.get("warranty_notes"),
                            includes_accessories=clf.get("includes_accessories") or [],
                            deal_score=int(deal_score) if deal_score is not None else None,
                            is_great_deal=clf.get("is_great_deal"),
                            estimated_market_value=Decimal(str(emv)) if emv is not None else None,
                            price_vs_market_pct=Decimal(str(pvm)) if pvm is not None else None,
                            is_relevant_listing=bool(clf.get("is_relevant_listing", False)),
                            notes=clf.get("notes"),
                            confidence=clf.get("confidence", "low"),
                            reason=clf.get("reason"),
                            raw_llm_response=clf,
                        ))
                    session.commit()
                    result.classified += len(rows)
                    logger.info(f"[Classify] {result.classified}/{total} classified")
                    success = True
                    break

                except Exception as exc:
                    session.rollback()
                    logger.warning(f"[Classify] Batch attempt {attempt}/{MAX_RETRIES} failed: {exc}")
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_BACKOFF_SECONDS * attempt)

            if not success:
                logger.error(f"[Classify] Batch permanently failed after {MAX_RETRIES} attempts — skipping {len(rows)} rows this run")
                result.errors += len(rows)
                exclude_ids.extend(row.id for row in rows)

        result.status = "completed" if result.errors == 0 else "partial"
        _finish_run(session, db_run, result)

    logger.info(
        f"[Classify] Done — total={result.total} "
        f"classified={result.classified} errors={result.errors}"
    )
    return result


def _create_run(
    session: Session,
    category_key: Optional[str],
    category_id: Optional[uuid.UUID] = None,
) -> PipelineRun:
    run = PipelineRun(
        stage="stage2_classify",
        source=category_key if category_key else "all",
        source_type="facebook_legacy",
        category_key=category_key,
        category_id=category_id,
        status="running",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _finish_run(session: Session, run: PipelineRun, result: ClassifyResult) -> None:
    run.status = result.status
    run.finished_at = datetime.now(ZoneInfo("America/Toronto"))
    run.total_records = result.total
    run.newly_added_count = result.classified
    run.error_count = result.errors
    session.commit()
