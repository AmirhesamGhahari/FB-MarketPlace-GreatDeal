"""Facebook Marketplace — Stage 1 extract pipeline.

Reads Apify records and writes them as Parquet to S3.
Each run appends a new file: s3://bucket/raw/category_key={key}/run_date={YYYY-MM-DD}/{run_id}.parquet
Deduplication (latest version per fb_listing_id) is handled at query time in Athena via ROW_NUMBER().
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional

import awswrangler as wr
import boto3
import pandas as pd
from loguru import logger

from fb_marketplace_greatdeals.config import settings

_TZ = ZoneInfo("America/Toronto")


@dataclass
class PipelineResult:
    run_id: str
    status: str
    total: int = 0
    errors: int = 0
    newly_added: int = 0
    change_added: int = 0  # unused in S3 mode, kept for CLI display compatibility
    skipped: int = 0       # unused in S3 mode, kept for CLI display compatibility


# ── Field parsing ─────────────────────────────────────────────────────────────


def _parse_price(price_str: Optional[str]) -> Optional[float]:
    if not price_str:
        return None
    try:
        digits = re.sub(r"[^\d.]", "", str(price_str))
        return float(digits) if digits else None
    except (ValueError, TypeError):
        return None


def _parse_listed_at(ms: Optional[int]) -> Optional[datetime]:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=_TZ)
    except (OSError, ValueError, OverflowError):
        return None


def _parse_fetched_at(iso_str: Optional[str]) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone(_TZ)
    except ValueError:
        return None


# ── Row builder ───────────────────────────────────────────────────────────────


def _build_row(record: dict, run_id: str, category_key: str) -> dict:
    price = record.get("price") or {}
    location = record.get("location") or {}
    extra = record.get("extraListingData") or {}

    extra_images: list = extra.get("images") or []
    primary = record.get("primaryImage")
    if primary and primary not in extra_images:
        all_images = [primary] + extra_images
    else:
        all_images = extra_images or ([primary] if primary else [])

    fb_condition = None
    for attr in (extra.get("attribute_data") or []):
        if attr.get("attribute_name") == "Condition":
            fb_condition = attr.get("value")
            break

    badges = extra.get("commerce_badges_info") or {}
    is_highly_rated = badges.get("source_summary") is not None

    strikethrough = record.get("strikethroughPrice") or {}
    original_price = _parse_price(strikethrough.get("amount"))

    return {
        "raw_id": str(uuid.uuid4()),
        "pipeline_run_id": run_id,
        "category_key": category_key,
        "fb_listing_id": record.get("listingId") or record.get("id"),
        "listing_url": record.get("url"),
        "title": record.get("title"),
        "description": extra.get("description"),
        "price": _parse_price(price.get("formatted")),
        "currency": price.get("currency"),
        "original_price": original_price,
        "location_city": location.get("city"),
        "location_state": location.get("state"),
        "image_urls": json.dumps(all_images),
        "is_sold": bool(record.get("isSold", False)),
        "listed_at": _parse_listed_at(record.get("listing_date_ms")),
        "scraped_at": _parse_fetched_at(record.get("_fetchedAt")),
        "search_query": record.get("searchQuery"),
        "fb_condition": fb_condition,
        "delivery_types": json.dumps(record.get("deliveryTypes") or []),
        "is_highly_rated_seller": is_highly_rated,
    }


# ── S3 write ──────────────────────────────────────────────────────────────────


def _write_to_s3(rows: list[dict], category_key: str, run_id: str) -> None:
    run_date = datetime.now(_TZ).strftime("%Y-%m-%d")
    s3_path = (
        f"s3://{settings.s3_bucket}/raw/"
        f"category_key={category_key}/"
        f"run_date={run_date}/"
        f"{run_id}.parquet"
    )
    df = pd.DataFrame(rows)
    for col in ("listed_at", "scraped_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)
    wr.s3.to_parquet(df=df, path=s3_path, boto3_session=boto3.Session(region_name=settings.aws_region))
    logger.info(f"[FB Stage 1] Wrote {len(rows)} rows → {s3_path}")


def _write_run_metadata(run_id: str, result: PipelineResult) -> None:
    body = json.dumps({
        "run_id": run_id,
        "status": result.status,
        "total": result.total,
        "newly_added": result.newly_added,
        "errors": result.errors,
        "finished_at": datetime.now(_TZ).isoformat(),
    }).encode()
    s3 = boto3.client("s3", region_name=settings.aws_region)
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=f"pipeline_runs/stage1/{run_id}.json",
        Body=body,
    )


# ── Core logic ────────────────────────────────────────────────────────────────


def _process_records(
    records: list[dict],
    run_id: str,
    category_key: str,
    result: PipelineResult,
) -> None:
    rows = []
    for record in records:
        result.total += 1
        listing_id = record.get("listingId") or record.get("id")
        if not listing_id:
            result.errors += 1
            logger.debug(f"[FB Stage 1] Skipping record with no listing ID: {record.get('url')!r}")
            continue
        rows.append(_build_row(record, run_id, category_key))
        result.newly_added += 1

    if rows:
        _write_to_s3(rows, category_key, run_id)


# ── Entry points ──────────────────────────────────────────────────────────────


def run(file_path: Path, category_key: str) -> PipelineResult:
    """Run Stage 1 from a saved Apify JSON file (dev / backfill use)."""
    run_id = str(uuid.uuid4())
    logger.info(f"[FB Stage 1] Starting — source: {file_path.name}")
    result = PipelineResult(run_id=run_id, status="completed")

    try:
        with open(file_path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON array, got {type(data).__name__}")
        records = [r for r in data if isinstance(r, dict)]
        if not records:
            raise ValueError("File contains no readable records")
    except Exception as exc:
        result.status = "failed"
        logger.error(f"[FB Stage 1] Failed to read file: {exc}")
        _write_run_metadata(run_id, result)
        return result

    logger.info(f"[FB Stage 1] Loaded {len(records)} records from file")
    _process_records(records, run_id, category_key, result)
    _write_run_metadata(run_id, result)
    logger.info(
        f"[FB Stage 1] Done — total={result.total} "
        f"newly_added={result.newly_added} errors={result.errors}"
    )
    return result


def run_from_records(
    records: list[dict],
    source: str,
    category_key: str,
    mode: str = "periodic",
) -> PipelineResult:
    """Run Stage 1 from records returned by ApifyRunner (live run)."""
    run_id = str(uuid.uuid4())
    logger.info(f"[FB Stage 1] Starting — source: {source} mode: {mode} ({len(records)} records)")
    result = PipelineResult(run_id=run_id, status="completed")
    _process_records(records, run_id, category_key, result)
    _write_run_metadata(run_id, result)
    logger.info(
        f"[FB Stage 1] Done — total={result.total} "
        f"newly_added={result.newly_added} errors={result.errors}"
    )
    return result
