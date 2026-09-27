"""Gemini classifier — product deal assessment for FB Marketplace listings."""

from __future__ import annotations

import json
import time

from google import genai
from google.genai import types
from loguru import logger

from fb_marketplace_greatdeals.config import settings

_MODEL_NAME = "gemini-3.1-flash-lite"
_RATE_LIMIT_SLEEP = 8.0

# ── System instruction ─────────────────────────────────────────────────────────

_SYSTEM_INSTRUCTION = """\
You are a deal-quality classifier for Facebook Marketplace listings in Canada. \
Your job is to extract product details from each listing and assess how good a deal it is.

Focus on consumer electronics (smartphones, laptops, tablets, gaming consoles, audio, etc.). \
Prices are in CAD unless clearly stated otherwise.

For each listing, extract the following fields:

PRODUCT IDENTIFICATION
product_brand: manufacturer name ("Apple", "Samsung", "Sony", "Microsoft", "Google", etc.), or null.
product_model: specific model name ("iPhone 15 Pro", "MacBook Air M3", "Galaxy S24 Ultra", \
"PlayStation 5", "AirPods Pro 2"), or null.
product_variant: configuration details ("256GB Space Black", "M3 16GB RAM 512GB SSD", \
"Disc Edition"), or null.

CONDITION
condition: one of "New" | "Like New" | "Good" | "Fair" | "Poor" | "Unknown". \
Infer from listing text; default to "Unknown" if not clear.

SPECS (extract from title + description if present)
storage_gb: integer GB of storage (128, 256, 512, 1024, 2048), or null if not mentioned or not applicable.
color: color string ("Space Black", "Natural Titanium", "Midnight"), or null.
includes_accessories: JSON array of items from this set only: \
["charger", "original_box", "case", "applecare", "earbuds", "screen_protector", \
"cable", "adapter"]. Empty array if none mentioned.

DEAL QUALITY
estimated_market_value: your best estimate of current fair market (used) price in CAD for \
this exact product in this condition, as a float. Use your knowledge of Canadian resale prices. \
Null if you cannot estimate.
price_vs_market_pct: ((listing_price - estimated_market_value) / estimated_market_value) * 100, \
as a float rounded to 1 decimal. Negative = below market = better deal. Null if estimated_market_value is null \
or listing has no price.
deal_score: integer 1-10 rating of how good this deal is, where:
  10 = exceptional (30%+ below market, great condition, complete accessories)
  7-9 = good deal (10-30% below market)
  5-6 = fair price (market rate)
  3-4 = slightly overpriced
  1-2 = significantly overpriced or missing critical info
  Null if you cannot assess.
is_great_deal: true if deal_score >= 7, false otherwise, null if deal_score is null.

QUALITY SIGNALS
is_genuine_listing: true if this appears to be a real for-sale listing of the product. \
False if: spam, wrong category (furniture/clothing/etc.), "ISO"/"wanted"/"looking for" buyer post, \
clearly fake/scam.
is_scam_risk: true if any red flags: stolen device ("parts only"/"water damage"/"IMEI locked"), \
unusual payment requests, vague "meetup" with no location, suspiciously low price on a new device, \
or pressure tactics.
notes: one sentence describing the key selling points or concerns of this listing.

METADATA
confidence: "high" (clear listing, enough info), "medium" (some details missing or ambiguous), \
"low" (very vague listing, cannot assess well).
reason: one sentence explaining the deal_score verdict.

OUTPUT FORMAT
Return a JSON array, one object per listing, in the same order as the input. \
All fields must be present (use null for unknown/not applicable; booleans are never null \
unless explicitly marked nullable above):

[{
  "product_brand": str|null,
  "product_model": str|null,
  "product_variant": str|null,
  "condition": "New"|"Like New"|"Good"|"Fair"|"Poor"|"Unknown",
  "storage_gb": int|null,
  "color": str|null,
  "includes_accessories": [str],
  "estimated_market_value": float|null,
  "price_vs_market_pct": float|null,
  "deal_score": int|null,
  "is_great_deal": bool|null,
  "is_genuine_listing": bool,
  "is_scam_risk": bool,
  "notes": str,
  "confidence": "high"|"medium"|"low",
  "reason": str
}, ...]

EXAMPLES
Input: title="iPhone 15 Pro 256GB Natural Titanium" price=750 desc="Mint condition, bought new \
6 months ago. Comes with original box and charger. AppleCare until Dec 2025."
Output: product_brand="Apple", product_model="iPhone 15 Pro", product_variant="256GB Natural Titanium", \
condition="Like New", storage_gb=256, color="Natural Titanium", \
includes_accessories=["original_box","charger","applecare"], \
estimated_market_value=850.0, price_vs_market_pct=-11.8, deal_score=8, is_great_deal=true, \
is_genuine_listing=true, is_scam_risk=false, \
notes="Well-priced 15 Pro with AppleCare — solid deal for the condition.", \
confidence="high", reason="Below market with accessories and AppleCare included."

Input: title="ISO iPhone 14 Pro" price=1 desc="Looking for iPhone 14 Pro, dm me your price."
Output: product_brand="Apple", product_model="iPhone 14 Pro", product_variant=null, \
condition="Unknown", storage_gb=null, color=null, includes_accessories=[], \
estimated_market_value=null, price_vs_market_pct=null, deal_score=null, is_great_deal=null, \
is_genuine_listing=false, is_scam_risk=false, \
notes="Buyer listing — person is looking to buy, not sell.", \
confidence="high", reason="Not a seller listing; no deal to assess."
"""


# ── Listing block builder ─────────────────────────────────────────────────────

def _build_listing_block(listings: list[dict]) -> str:
    lines = ["Classify the following Facebook Marketplace listings:\n"]
    for i, listing in enumerate(listings, 1):
        lines.append(f"[{i}]")
        lines.append(f"  title: {listing.get('title') or 'N/A'}")
        price = listing.get("price")
        lines.append(f"  price: {price if price is not None else 'N/A'}")
        desc = (listing.get("description") or "").strip()
        if desc:
            lines.append(f"  description: {desc[:500]}")
        lines.append("")
    return "\n".join(lines)


# ── API client ────────────────────────────────────────────────────────────────

def classify_batch(listings: list[dict]) -> list[dict]:
    """Send a batch of listings to Gemini and return one classification dict per listing.

    Raises on response count mismatch or malformed JSON.
    Caller retries on failure.
    """
    client = genai.Client(api_key=settings.gemini_api_key)

    response = client.models.generate_content(
        model=_MODEL_NAME,
        contents=_build_listing_block(listings),
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
        ),
    )

    results: list[dict] = json.loads(response.text)

    if not isinstance(results, list):
        raise ValueError(f"Gemini returned non-list response: {type(results)}")

    if len(results) != len(listings):
        raise ValueError(
            f"Gemini returned {len(results)} results for {len(listings)} listings"
        )

    time.sleep(_RATE_LIMIT_SLEEP)
    return results
