"""Facebook Marketplace — Stage 2 classification pipeline.

Reads unclassified raw listings from S3, classifies them via Gemini,
and writes results as Parquet back to S3.

Deduplication: listings whose fb_listing_id already appears in the classified
S3 prefix are skipped. Failed batches are excluded and retried on the next run.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

import awswrangler as wr
import boto3
import pandas as pd
from loguru import logger

from fb_marketplace_greatdeals.config import settings
from fb_marketplace_greatdeals.sources.facebook_legacy.gemini import classify_batch

BATCH_SIZE = 20
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 4
_MODEL_NAME = "gemini-3.5-flash-lite"
_TZ = ZoneInfo("America/Toronto")


@dataclass
class ClassifyResult:
    run_id: str
    status: str
    total: int = 0
    classified: int = 0
    errors: int = 0


# ── S3 read helpers ───────────────────────────────────────────────────────────


def _boto_session() -> boto3.Session:
    return boto3.Session(region_name=settings.aws_region)


def _read_raw_listings(category_key: Optional[str]) -> pd.DataFrame:
    """Read all raw listings from S3, returning the latest version per fb_listing_id."""
    path = f"s3://{settings.s3_bucket}/raw/"
    if category_key:
        path += f"category_key={category_key}/"

    try:
        df = wr.s3.read_parquet(path=path, dataset=True, boto3_session=_boto_session())
    except Exception:
        logger.info("[Classify] No raw listings found in S3")
        return pd.DataFrame()

    if df.empty:
        return df

    # Keep only the latest scraped version of each listing
    df = df.sort_values("scraped_at", na_position="first")
    df = df.drop_duplicates(subset=["fb_listing_id"], keep="last")
    return df.reset_index(drop=True)


def _read_classified_ids(category_key: Optional[str]) -> set[str]:
    """Return the set of fb_listing_ids already classified."""
    path = f"s3://{settings.s3_bucket}/classified/"
    if category_key:
        path += f"category_key={category_key}/"

    try:
        df = wr.s3.read_parquet(
            path=path,
            dataset=True,
            columns=["fb_listing_id"],
            boto3_session=_boto_session(),
        )
        return set(df["fb_listing_id"].dropna().tolist())
    except Exception:
        return set()


# ── S3 write helpers ──────────────────────────────────────────────────────────


def _write_classified(rows: list[dict], category_key: str, run_id: str) -> None:
    classified_date = datetime.now(_TZ).strftime("%Y-%m-%d")
    s3_path = (
        f"s3://{settings.s3_bucket}/classified/"
        f"category_key={category_key}/"
        f"classified_date={classified_date}/"
        f"{run_id}.parquet"
    )
    df = pd.DataFrame(rows)
    if "classified_at" in df.columns:
        df["classified_at"] = pd.to_datetime(df["classified_at"], utc=True)
    wr.s3.to_parquet(df=df, path=s3_path, boto3_session=_boto_session())
    logger.info(f"[Classify] Wrote {len(rows)} classified rows → {s3_path}")


def _write_run_metadata(run_id: str, result: ClassifyResult) -> None:
    body = json.dumps({
        "run_id": run_id,
        "status": result.status,
        "total": result.total,
        "classified": result.classified,
        "errors": result.errors,
        "finished_at": datetime.now(_TZ).isoformat(),
    }).encode()
    s3 = boto3.client("s3", region_name=settings.aws_region)
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=f"pipeline_runs/stage2/{run_id}.json",
        Body=body,
    )


# ── Main pipeline ─────────────────────────────────────────────────────────────


def run(category_key: Optional[str] = None) -> ClassifyResult:
    """Classify all unclassified current-version raw listings via Gemini.

    Pass category_key to restrict to one category, or omit to classify across all.
    Idempotent: listings already in the classified S3 prefix are skipped.
    """
    run_id = str(uuid.uuid4())
    result = ClassifyResult(run_id=run_id, status="completed")

    raw_df = _read_raw_listings(category_key)
    if raw_df.empty:
        logger.info("[Classify] No raw listings found — nothing to do")
        _write_run_metadata(run_id, result)
        return result

    classified_ids = _read_classified_ids(category_key)
    unclassified = raw_df[~raw_df["fb_listing_id"].isin(classified_ids)].reset_index(drop=True)

    result.total = len(unclassified)
    if result.total == 0:
        logger.info("[Classify] No unclassified listings — nothing to do")
        _write_run_metadata(run_id, result)
        return result

    logger.info(f"[Classify] {result.total} listings to classify in batches of {BATCH_SIZE}")

    exclude_indices: set[int] = set()
    offset = 0

    while True:
        available = unclassified[~unclassified.index.isin(exclude_indices)]
        batch_df = available.iloc[offset: offset + BATCH_SIZE]
        if batch_df.empty:
            break

        listings = [
            {
                "search_query": row.get("search_query"),
                "title": row.get("title"),
                "description": row.get("description"),
                "price": row.get("price"),
            }
            for row in batch_df.to_dict("records")
        ]

        success = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                classifications = classify_batch(listings)
                classified_rows = []
                now = datetime.now(_TZ)
                for idx, (_, raw_row) in enumerate(batch_df.iterrows()):
                    clf = classifications[idx]
                    deal_score = clf.get("deal_score")
                    emv = clf.get("estimated_market_value")
                    pvm = clf.get("price_vs_market_pct")
                    bh = clf.get("battery_health_pct")
                    cc = clf.get("cycle_count")
                    classified_rows.append({
                        "classified_id": str(uuid.uuid4()),
                        "pipeline_run_id": run_id,
                        "fb_listing_id": raw_row.get("fb_listing_id"),
                        "category_key": raw_row.get("category_key", category_key),
                        "classified_at": now,
                        "llm_model": _MODEL_NAME,
                        "listing_type": clf.get("listing_type"),
                        "product_brand": clf.get("product_brand"),
                        "product_model": clf.get("product_model"),
                        "product_variant": clf.get("product_variant"),
                        "condition": clf.get("condition"),
                        "storage_gb": clf.get("storage_gb"),
                        "color": clf.get("color"),
                        "battery_health_pct": int(bh) if bh is not None else None,
                        "cycle_count": int(cc) if cc is not None else None,
                        "warranty_notes": clf.get("warranty_notes"),
                        "includes_accessories": json.dumps(clf.get("includes_accessories") or []),
                        "deal_score": int(deal_score) if deal_score is not None else None,
                        "is_great_deal": clf.get("is_great_deal"),
                        "estimated_market_value": float(emv) if emv is not None else None,
                        "price_vs_market_pct": float(pvm) if pvm is not None else None,
                        "is_relevant_listing": bool(clf.get("is_relevant_listing", False)),
                        "notes": clf.get("notes"),
                        "confidence": clf.get("confidence", "low"),
                        "reason": clf.get("reason"),
                    })

                cat = category_key or (batch_df.iloc[0].get("category_key") if not batch_df.empty else "unknown")
                _write_classified(classified_rows, cat, f"{run_id}-{offset}")
                result.classified += len(batch_df)
                logger.info(f"[Classify] {result.classified}/{result.total} classified")
                offset += BATCH_SIZE
                success = True
                break

            except Exception as exc:
                logger.warning(f"[Classify] Batch attempt {attempt}/{MAX_RETRIES} failed: {exc}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)

        if not success:
            logger.error(
                f"[Classify] Batch permanently failed after {MAX_RETRIES} attempts — "
                f"skipping {len(batch_df)} rows this run"
            )
            result.errors += len(batch_df)
            for idx in batch_df.index:
                exclude_indices.add(idx)
            offset += BATCH_SIZE

    result.status = "completed" if result.errors == 0 else "partial"
    _write_run_metadata(run_id, result)
    logger.info(
        f"[Classify] Done — total={result.total} "
        f"classified={result.classified} errors={result.errors}"
    )
    return result
