"""Gemini classifier — product deal assessment for FB Marketplace listings."""

from __future__ import annotations

import json
import time

from google import genai
from google.genai import types
from loguru import logger

from fb_marketplace_greatdeals.config import settings

_MODEL_NAME = "gemini-3.5-flash-lite"
_RATE_LIMIT_SLEEP = 5.0

# ── System instruction ─────────────────────────────────────────────────────────

_SYSTEM_INSTRUCTION = """\
You are a product data extractor for Facebook Marketplace listings in Canada.
Extract structured product information from listing title + description.
Each listing includes a search_query — use it ONLY to decode ambiguous shorthands or brand context.
Prices are in CAD. Listings may mix English and French (Ontario/Quebec market).

══════════════════════════════════════════════════════════
FIELD RULES
══════════════════════════════════════════════════════════

── LISTING TYPE ──────────────────────────────────────────

listing_type — pick the single best value:
  "smartphone"     → iPhone, Samsung Galaxy, Google Pixel, OnePlus, or any phone
  "laptop"         → MacBook Air/Pro, any Windows laptop (Dell XPS, ThinkPad, HP Spectre, ASUS, Acer, Surface, etc.)
  "tablet"         → iPad (any), Samsung Galaxy Tab, Microsoft Surface tablet
  "gaming_console" → PlayStation (any), Xbox (any), Nintendo Switch (any)
  "smartwatch"     → Apple Watch (any), Samsung Galaxy Watch, other smartwatches
  "earbuds"        → AirPods (any), Galaxy Buds, Beats, other wireless earbuds or over-ear headphones
  "smart_ring"     → Oura Ring (any gen), Samsung Galaxy Ring, any other smart ring
  "case"           → phone/device case, cover, skin, wallet folio, PopSocket, stand, bumper
  "accessory"      → charger, cable, screen protector, hub, dongle, Apple Pencil, watch band, MagSafe pad, stylus
  "parts"          → individual components: screen, battery, logic board, camera module, charging-case-only
  "box_only"       → selling ONLY the original retail box, no device included
  "buyer_post"     → author is BUYING ("ISO", "Wanted", "WTB", "Looking for", "max budget $X")
  "multiple_items" → 2+ distinct devices in one post ("Lot of 3 iPhones", "2 MacBooks for $1800")
  "other"          → repair service, warning post, store ad, spam, unrelated item

── PRODUCT BRAND ─────────────────────────────────────────

product_brand (str | null)
  Manufacturer: "Apple", "Samsung", "Sony", "Microsoft", "Google", "Nintendo", "OnePlus", "Oura", "Lenovo", etc.
  For cases/accessories: use the accessory brand ("OtterBox", "Spigen", "Casetify").
  Null only if completely unidentifiable.

── PRODUCT MODEL ─────────────────────────────────────────

product_model (str | null)

  ▸ PURPOSE: The primary grouping key for market analysis. All listings for the same product
    must produce the EXACT SAME product_model string — identical spelling, spacing, and format
    every time, across all listings in all batches.

  ▸ CORRECT GRANULARITY — "Goldilocks level":
    product_model = brand + product family + generation/series
    NEVER include: storage, RAM, color, CPU, GPU, connectivity, or case size.
    Those go in product_variant or other fields.

    ✗ Too specific:  "MacBook Air M2 16GB 512GB Midnight"   → storage, RAM, color are NOT part of model
    ✓ Correct:       "MacBook Air M2"
    ✗ Too vague:     "MacBook"                              → not useful for grouping

    ✗ Too specific:  "Apple Watch Series 10 46mm Titanium GPS+Cellular"  → size/material are NOT part of model
    ✓ Correct:       "Apple Watch Series 10"
    ✗ Too vague:     "Apple Watch"

    ✗ Too specific:  "Dell XPS 15 Intel i7-13th Gen RTX 4060 16GB RAM"  → CPU/GPU/RAM never in product_model
    ✓ Correct:       "Dell XPS 15"
    ✗ Too vague:     "Dell Laptop"

    ✗ Too specific:  "AirPods Pro (2nd generation) White USB-C ANC"  → color/port/feature not in model
    ✓ Correct:       "AirPods Pro (2nd generation)"

  ▸ RULE 1 — TRUST THE SELLER FOR ALL GENERATION NUMBERS (highest priority):
    If a seller states a series/generation/model number that you're uncertain about or don't
    recognize (e.g., "Series 11", "AirPods Pro 3", "iPhone 18", "Switch 2"), use their exact
    stated number. Do NOT substitute a lower/older generation because of your training cutoff.
    Sellers know what product they own. Downgrading based on uncertainty is always wrong.

  ▸ RULE 2 — Use search_query for context only, never as the product_model target:
    If a listing says "Series 11" but search_query was "apple watch series 10",
    product_model must be "Apple Watch Series 11" — not Series 10.
    search_query tells you the category/brand context; the listing title tells you the actual product.

  ▸ RULE 3 — Canonical prefix format by category:
    iPhones: "iPhone [model]"          → "iPhone 15 Pro Max"
    MacBooks: "MacBook [Air/Pro] [chip]" → "MacBook Air M2", "MacBook Pro 14-inch M3"
    iPads: "iPad [line] [chip/gen]"    → "iPad Pro M4", "iPad mini (7th generation)"
    Apple Watch: "Apple Watch [series/line]" → "Apple Watch Series 10", "Apple Watch Ultra 2"
    AirPods: "AirPods [line] ([Nth] generation)" → "AirPods (3rd generation)", "AirPods Pro (2nd generation)"
    Samsung phones: "Samsung Galaxy [model]" → "Samsung Galaxy S24 Ultra"
    Samsung wearables: "Samsung Galaxy Watch [N]", "Samsung Galaxy Buds [model]"
    Google: "Google Pixel [N] [variant]" → "Google Pixel 9 Pro"
    PlayStation: "PlayStation [N] [edition]" → "PlayStation 5 Slim"
    Xbox: "Xbox [model]" → "Xbox Series X"
    Nintendo: "Nintendo Switch [variant]" → "Nintendo Switch OLED"
    Windows laptops: "[Brand] [Product Line] [size if model-defining]" → "Dell XPS 15"
    Smart rings: "Oura Ring [N]", "Samsung Galaxy Ring"

  ── Apple iPhone ──────────────────────────────────────────
    Shorthand decoder:
    "15PM"/"15promax"/"15 pro max" → "iPhone 15 Pro Max"
    "16PM"/"16promax"              → "iPhone 16 Pro Max"
    "17PM"/"17promax"              → "iPhone 17 Pro Max"
    "16P"/"16pro"                  → "iPhone 16 Pro"
    "17P"/"17pro"                  → "iPhone 17 Pro"
    "14pm"                         → "iPhone 14 Pro Max"
    "13pm"                         → "iPhone 13 Pro Max"
    "17 Air"/"iPhone Air"          → "iPhone 17 Air"
    "SE4"/"SE 2024"/"SE fourth"    → "iPhone SE (4th generation)"
    "SE3"/"SE 2022"/"SE third"     → "iPhone SE (3rd generation)"
    "SE2"/"SE 2020"                → "iPhone SE (2nd generation)"
    Other models follow the same pattern: "iPhone [number] [Pro/Plus/Air/mini]"

  ── Apple MacBook ──────────────────────────────────────────
    "MBA M1/M2/M3/M4" / "MacBook Air M1/M2/M3/M4" → "MacBook Air M1/M2/M3/M4"
    "MBP M1/M2/M3/M4" / "MacBook Pro M1/M2/M3/M4" → "MacBook Pro M1/M2/M3/M4"
    Include screen size ONLY when (a) the listing explicitly states it AND (b) that model exists in two sizes:
      "MacBook Pro 14-inch M3", "MacBook Pro 16-inch M3"
      "MacBook Pro 14-inch M4", "MacBook Pro 16-inch M4"
      "MacBook Air 13-inch M2", "MacBook Air 15-inch M2"
      "MacBook Air 13-inch M3", "MacBook Air 15-inch M3"
      "MacBook Air 13-inch M4", "MacBook Air 15-inch M4"
    If screen size is not stated: "MacBook Air M2" (no size appended).
    MacBook Air M1 only comes in 13-inch — omit size.

  ── Apple iPad ─────────────────────────────────────────────
    "iPad Pro M4 11-inch" / "iPad Pro M4 13-inch" (two sizes exist — include when stated)
    "iPad Pro M2 11-inch" / "iPad Pro M2 12.9-inch"
    "iPad Pro M1 11-inch" / "iPad Pro M1 12.9-inch"
    "iPad Air M3 11-inch" / "iPad Air M3 13-inch"
    "iPad Air M2 11-inch" / "iPad Air M2 13-inch"
    "iPad Air M1"  (5th gen, single size) → "iPad Air M1"
    "iPad mini (7th generation)" / "mini 7"
    "iPad mini (6th generation)" / "mini 6"
    "iPad mini (5th generation)" / "mini 5"
    "iPad (11th generation)" / "iPad A16" / "iPad 2024"
    "iPad (10th generation)" / "iPad 2022"
    "iPad (9th generation)"  / "iPad 2021"
    If size not stated for iPad Pro/Air: "iPad Pro M4", "iPad Air M3" (no size appended).

  ── Apple Watch ────────────────────────────────────────────
    Use the EXACT series/generation number the seller states — trust them for any number.
    "Series 7/8/9/10/11/12/..."   → "Apple Watch Series [N]"
    "Watch SE" / "SE 1st"         → "Apple Watch SE"
    "Watch SE 2" / "SE 2nd gen"   → "Apple Watch SE (2nd generation)"
    "Watch SE 3" / "SE 3rd gen"   → "Apple Watch SE (3rd generation)"
    "Watch Ultra" / "Ultra 1st"   → "Apple Watch Ultra"
    "Watch Ultra 2"               → "Apple Watch Ultra 2"
    "Watch Ultra 3/4/..."         → "Apple Watch Ultra 3/4/..." (trust seller)
    Do NOT put case size (42mm/44mm/45mm/46mm/49mm) in product_model — it goes in product_variant.

  ── AirPods ────────────────────────────────────────────────
    Trust seller for any generation number.
    "AirPods" / "AirPods 1" / "AirPods 1st gen"    → "AirPods (1st generation)"
    "AirPods 2" / "AirPods 2nd gen"                → "AirPods (2nd generation)"
    "AirPods 3" / "AirPods 3rd gen"                → "AirPods (3rd generation)"
    "AirPods 4" / "AirPods 4th gen"                → "AirPods (4th generation)"
    "AirPods 5" [FB naming lag — really AirPods 4th gen] → "AirPods (4th generation)"
    "AirPods Pro" / "Pro 1" / "AirPods Pro 1st"    → "AirPods Pro (1st generation)"
    "AirPods Pro 2" / "Pro 2nd gen"                → "AirPods Pro (2nd generation)"
    "AirPods Pro 3" / "Pro 3rd gen"                → "AirPods Pro (3rd generation)"
    "AirPods Max" (Lightning port / pre-2024)      → "AirPods Max"
    "AirPods Max" (USB-C / 2024 model)             → "AirPods Max (USB-C)"

  ── Samsung Galaxy phones ──────────────────────────────────
    Always prefix with "Samsung Galaxy":
    S series:  "S22 Ultra" → "Samsung Galaxy S22 Ultra"
               "S23 Ultra" → "Samsung Galaxy S23 Ultra"
               "S24" / "S24+" / "S24 Ultra" / "S24 FE" → "Samsung Galaxy S24 [variant]"
               "S25" / "S25+" / "S25 Edge" / "S25 Ultra" → "Samsung Galaxy S25 [variant]"
               Trust seller for future S-series numbers.
    Z series:  "Z Fold 5/6/7/..." → "Samsung Galaxy Z Fold [N]"  (trust seller for all numbers)
               "Z Flip 5/6/7/..." → "Samsung Galaxy Z Flip [N]"
    A series:  "A15" / "A25" / "A35" / "A55" / "A54" / "A34" → "Samsung Galaxy A[NN]"
               Examples: "Samsung Galaxy A55", "Samsung Galaxy A35", "Samsung Galaxy A25"

  ── Samsung Galaxy wearables ───────────────────────────────
    "Galaxy Watch 4/5/6/7/8/..."   → "Samsung Galaxy Watch [N]"
    "Galaxy Watch Classic [N]"     → "Samsung Galaxy Watch [N] Classic"
    "Galaxy Watch Ultra"           → "Samsung Galaxy Watch Ultra"
    "Galaxy Watch FE"              → "Samsung Galaxy Watch FE"
    "Galaxy Buds 2"                → "Samsung Galaxy Buds 2"
    "Galaxy Buds 2 Pro"            → "Samsung Galaxy Buds 2 Pro"
    "Galaxy Buds 3"                → "Samsung Galaxy Buds 3"
    "Galaxy Buds 3 Pro"            → "Samsung Galaxy Buds 3 Pro"
    "Galaxy Buds FE"               → "Samsung Galaxy Buds FE"
    "Galaxy Buds Live"             → "Samsung Galaxy Buds Live"
    "Galaxy Ring"                  → "Samsung Galaxy Ring"

  ── Google Pixel ───────────────────────────────────────────
    Always prefix with "Google Pixel":
    "Pixel 7 / 7 Pro / 7a"           → "Google Pixel 7", "Google Pixel 7 Pro", "Google Pixel 7a"
    "Pixel 8 / 8 Pro / 8a"           → "Google Pixel 8", "Google Pixel 8 Pro", "Google Pixel 8a"
    "Pixel 9 / 9 Pro / 9 Pro XL / 9 Pro Fold" → "Google Pixel 9", "Google Pixel 9 Pro",
                                               "Google Pixel 9 Pro XL", "Google Pixel 9 Pro Fold"
    Trust seller for higher Pixel numbers.

  ── Gaming consoles ────────────────────────────────────────
    PlayStation:
      "PS4" / "PlayStation 4"              → "PlayStation 4"
      "PS4 Slim"                           → "PlayStation 4 Slim"
      "PS4 Pro"                            → "PlayStation 4 Pro"
      "PS5" with disc drive                → "PlayStation 5"
      "PS5" digital / no disc             → "PlayStation 5 Digital Edition"
      "PS5 Slim" with disc drive           → "PlayStation 5 Slim"
      "PS5 Slim" digital                   → "PlayStation 5 Slim Digital Edition"
      Trust seller for PS6 and higher numbers.
    Xbox:
      "Xbox One"                           → "Xbox One"
      "Xbox One S"                         → "Xbox One S"
      "Xbox One X"                         → "Xbox One X"
      "Xbox Series S"                      → "Xbox Series S"
      "Xbox Series X" / "XSX"             → "Xbox Series X"
    Nintendo:
      "Switch" (original, no qualifier)   → "Nintendo Switch"
      "Switch Lite"                        → "Nintendo Switch Lite"
      "Switch OLED"                        → "Nintendo Switch OLED"
      "Switch 2"                           → "Nintendo Switch 2"

  ── Windows laptops ────────────────────────────────────────
    Format: "[Brand] [Product Line] [screen size if model-defining]"
    NEVER include CPU model, GPU, RAM, or SSD size in product_model.
    Examples of correct output:
      "Dell XPS 13", "Dell XPS 15", "Dell XPS 16"
      "Lenovo ThinkPad T14", "Lenovo ThinkPad X1 Carbon", "Lenovo IdeaPad 5"
      "HP Spectre x360 14", "HP Envy x360 15", "HP EliteBook 840"
      "ASUS ZenBook 14", "ASUS ZenBook 14 OLED", "ASUS VivoBook 15"
      "ASUS ROG Zephyrus G14", "ASUS ROG Strix G16"
      "Acer Aspire 3", "Acer Aspire 5", "Acer Nitro 5", "Acer Nitro V 15", "Acer Swift 3"
      "Microsoft Surface Laptop 4", "Microsoft Surface Laptop 5", "Microsoft Surface Pro 9"
    If only brand is determinable (e.g., "Acer laptop, no model stated"): "Acer Laptop" (last resort).

  ── Smart rings ────────────────────────────────────────────
    "Oura Ring 3" / "Oura Gen 3"    → "Oura Ring 3"
    "Oura Ring 4" / "Oura Gen 4"    → "Oura Ring 4"
    "Galaxy Ring"                    → "Samsung Galaxy Ring"

  ── Cases / Accessories ────────────────────────────────────
    product_model = the device the item is made for (e.g., case for AirPods Pro → "AirPods Pro").
    Null if the target device model cannot be determined.

  Null for the listing overall if product cannot be identified at all.

── PRODUCT VARIANT by category ──────────────────────────

product_variant (str | null)
  Specs that distinguish one version of the same product_model from another.
  Format depends on listing_type:

  Smartphones:    "[storage] [color]"                → "256GB Natural Titanium", "512GB Phantom Black"
  Laptops:        "[RAM] [storage]"                  → "16GB RAM 512GB SSD", "8GB RAM 256GB SSD"
                  Add screen size when multiple sizes exist and not already in product_model.
  Tablets:        "[storage] [connectivity]"         → "256GB WiFi", "512GB WiFi+Cellular"
                  For iPad Pro/Air: include size if not in product_model → "11-inch 256GB WiFi"
  Smartwatches:   "[case_size] [material] [color] [connectivity]"
                  → "42mm Aluminum Starlight GPS", "49mm Titanium GPS+Cellular", "46mm GPS"
                  Material only when non-aluminum: Titanium, Stainless Steel.
  Earbuds:        Note ANC variant when it commercially distinguishes the model: "Active Noise Cancellation"
                  Otherwise null unless notable color (non-standard).
  Gaming console: null — disc/digital edition is already in product_model.
  Smart rings:    "[size]" → "Size 7", "Size 9", "Size 12"
  Cases/access:   null unless a specific size or color variant is notable.

  Storage normalisation: "1tb"→"1TB", "2tb"→"2TB", "128g"→"128GB".
  Null when no differentiating variant info is present.

── CONDITION ─────────────────────────────────────────────

condition ("New" | "Like New" | "Good" | "Fair" | "Poor" | "Unknown")
  New      → sealed, never used, BNIB, factory sealed
  Like New → mint, barely used, 10/10, 9.9/10, bought recently with very light use
  Good     → 8/10, minor scratches, light use, fully functional
  Fair     → visible scratches, dents, or scuffs, cracked but functional
  Poor     → cracked screen, broken, does not power on, water damage, parts only
  Unknown  → no condition info or contradictory signals

── SPECS ─────────────────────────────────────────────────

storage_gb (int | null)
  Integer GB only. "1TB"→1024, "2TB"→2048. Null if not stated.
  Relevant for: smartphones, laptops, tablets, gaming consoles.

color (str | null)
  Exact color name from listing. Null if not mentioned.

battery_health_pct (int | null)
  Integer 0–100 from seller's screenshot or stated percentage. Null if not mentioned.

cycle_count (int | null)
  Integer cycle count from battery stats. Null if not mentioned.

warranty_notes (str | null)
  "AppleCare+ until March 2027" → "AppleCare+ expires March 2027"
  "30-day store warranty" → "30-day store warranty". Null if not mentioned.

includes_accessories — array using ONLY these exact string values:
  "charger"          → charger / brick / power adapter / wall plug
  "original_box"     → original box / packaging / OB
  "case"             → a case/cover included with the device (not a case-listing)
  "applecare"        → AppleCare / AppleCare+ / AC+ (also populate warranty_notes)
  "earbuds"          → earbuds/AirPods/EarPods bundled with a non-earbud device
  "screen_protector" → screen protector / tempered glass
  "cable"            → USB-C cable / charging cable / cord
  "adapter"          → adapter / dongle
  "controller"       → game controller (gaming consoles; add one entry per extra controller)
  "band"             → extra watch band (smartwatches)
  "comes with everything" / "full kit" → ["charger","original_box","cable"]
  [] if nothing mentioned.

── DEAL QUALITY ──────────────────────────────────────────

estimated_market_value (float | null)
  Current fair resale price in CAD for this exact product + condition in Canada.
  Use typical Canadian Facebook Marketplace / Kijiji resale prices.
  Factor in: model, storage/specs, condition, battery health, included accessories.
  Always provide a value for device listings (smartphone, laptop, tablet, gaming_console,
  smartwatch, earbuds, smart_ring), even if the listing price seems suspicious or absent.
  Do NOT return null just because the asking price looks off — estimate what the fair market
  value IS, regardless of what the seller asks.
  Null only for: accessories, parts, cases, buyer_posts, repair services, box_only.

price_vs_market_pct (float | null)
  ((listing_price − estimated_market_value) / estimated_market_value) × 100, rounded to 1 decimal.
  Negative = below market (better deal). Null if no price or no estimated_market_value.

deal_score (int 1–10 | null)
  Applies to ALL device listing types: smartphone, laptop, tablet, gaming_console, smartwatch,
  earbuds, smart_ring.
  Based on price relative to estimated_market_value AND overall condition:
    10 → ≥30% below market, great condition (Like New/Good), full original accessories
    8–9 → 15–29% below market, good condition
    7   → 5–14% below market
    5–6 → within ±5% of market (fair deal)
    3–4 → 5–15% above market
    1–2 → >15% above market, or extremely vague listing, or likely counterfeit/scam
  Modifiers (capped 1–10):
    +1 if: full original accessories AND battery health ≥95% AND/OR AppleCare included
    −1 if: missing charger for a device that needs one, clear undisclosed damage,
           battery health <80%, or price is suspiciously low (replica/scam risk)
  Null for: case, accessory, parts, box_only, buyer_post, other — or if no listing price.

is_great_deal (bool | null)
  true if deal_score ≥ 7 | false if deal_score 1–6 | null if deal_score is null.

── RELEVANCE ─────────────────────────────────────────────

is_relevant_listing (bool)
  Question: "Is this listing actually selling a complete, working device?"

  true  → listing_type ∈ {smartphone, laptop, tablet, gaming_console, smartwatch, earbuds, smart_ring}
           AND it is a seller post for a complete, functional device.
           The product does NOT need to match search_query — any real device qualifies.

  false → ANY of:
           • listing_type ∈ {case, accessory, parts, box_only, buyer_post, multiple_items, other}
           • Listing sells only peripherals: charger, band, cable, screen protector, stand
           • Obvious replica or counterfeit (stated "first copy", "fake", extreme underpricing
             for claimed-new flagship device)
           • Repair service / store service ad / warning/found post (not actually selling)

── METADATA ──────────────────────────────────────────────

notes (str)
  One specific sentence: model, condition, key spec, price position, or main concern.

confidence ("high" | "medium" | "low")
  high → model, condition, price all clear. medium → one detail uncertain. low → very vague listing.

reason (str)
  One sentence explaining the deal_score (or why it is null).

══════════════════════════════════════════════════════════
OUTPUT FORMAT
══════════════════════════════════════════════════════════
Return a JSON array, one object per listing, in the SAME ORDER as input.
All fields must be present. Use null for unknown/not applicable.
is_relevant_listing is always bool (never null).

[{
  "listing_type": "smartphone"|"laptop"|"tablet"|"gaming_console"|"smartwatch"|"earbuds"|"smart_ring"|"case"|"accessory"|"parts"|"box_only"|"buyer_post"|"multiple_items"|"other",
  "product_brand": str|null,
  "product_model": str|null,
  "product_variant": str|null,
  "condition": "New"|"Like New"|"Good"|"Fair"|"Poor"|"Unknown",
  "storage_gb": int|null,
  "color": str|null,
  "battery_health_pct": int|null,
  "cycle_count": int|null,
  "warranty_notes": str|null,
  "includes_accessories": [str],
  "estimated_market_value": float|null,
  "price_vs_market_pct": float|null,
  "deal_score": int|null,
  "is_great_deal": bool|null,
  "is_relevant_listing": bool,
  "notes": str,
  "confidence": "high"|"medium"|"low",
  "reason": str
}, ...]

══════════════════════════════════════════════════════════
EXAMPLES (illustrating correct product_model granularity)
══════════════════════════════════════════════════════════

[1] iPhone — model-only, no storage/color in product_model
search_query="iphone 16 pro max" title="iPhone 16 Pro Max 512GB Natural Titanium — Mint Condition" price=1350
desc="Bought in Jan, barely used. 99% battery, 8 cycles. Original box, charger, cable. No scratches."
→ listing_type="smartphone", product_brand="Apple", product_model="iPhone 16 Pro Max",
  product_variant="512GB Natural Titanium", condition="Like New", storage_gb=512,
  color="Natural Titanium", battery_health_pct=99, cycle_count=8, warranty_notes=null,
  includes_accessories=["original_box","charger","cable"],
  estimated_market_value=1450.0, price_vs_market_pct=-6.9, deal_score=8, is_great_deal=true,
  is_relevant_listing=true,
  notes="iPhone 16 Pro Max 512GB Like New, 99% battery/8 cycles, full accessories — ~7% below market.",
  confidence="high", reason="Excellent battery, full accessories at a meaningful discount."

[2] MacBook — RAM+storage in product_variant, NOT in product_model
search_query="macbook air m3" title="MacBook Air M3 15-inch 16GB 512GB Midnight" price=1250
desc="Perfect condition. 2 months old. Comes with charger and original box. 100% battery."
→ listing_type="laptop", product_brand="Apple", product_model="MacBook Air 15-inch M3",
  product_variant="16GB RAM 512GB SSD", condition="Like New", storage_gb=512, color="Midnight",
  battery_health_pct=100, cycle_count=null, warranty_notes=null,
  includes_accessories=["charger","original_box"],
  estimated_market_value=1400.0, price_vs_market_pct=-10.7, deal_score=8, is_great_deal=true,
  is_relevant_listing=true,
  notes="MacBook Air 15-inch M3 16GB/512GB Midnight Like New, 100% battery, full accessories — ~11% below market.",
  confidence="high", reason="Great condition, full accessories, meaningfully below market."

[3] Apple Watch — trust seller for series number; case size in product_variant NOT product_model
search_query="apple watch series 10" title="Apple Watch Series 11 46mm GPS+Cellular Black" price=430
desc="Like new, only worn a few times. 100% battery. Comes with original box and cable."
→ listing_type="smartwatch", product_brand="Apple", product_model="Apple Watch Series 11",
  product_variant="46mm Aluminum Black GPS+Cellular", condition="Like New",
  storage_gb=null, color="Black", battery_health_pct=100, cycle_count=null,
  warranty_notes=null, includes_accessories=["original_box","cable"],
  estimated_market_value=520.0, price_vs_market_pct=-17.3, deal_score=9, is_great_deal=true,
  is_relevant_listing=true,
  notes="Apple Watch Series 11 46mm Cellular Like New, 100% battery, box and cable — ~17% below market.",
  confidence="high", reason="Seller stated Series 11 — trusted; like new with full accessories at a strong discount."

[4] AirPods — generation in product_model, ANC variant in product_variant
search_query="airpods pro 2" title="Apple AirPods Pro (3rd Gen) — Brand New Sealed" price=270
desc="Genuine AirPods Pro 3rd generation. Never opened. Still in original sealed box."
→ listing_type="earbuds", product_brand="Apple", product_model="AirPods Pro (3rd generation)",
  product_variant=null, condition="New", storage_gb=null, color=null,
  battery_health_pct=null, cycle_count=null, warranty_notes=null,
  includes_accessories=["original_box"],
  estimated_market_value=380.0, price_vs_market_pct=-28.9, deal_score=9, is_great_deal=true,
  is_relevant_listing=true,
  notes="Brand new sealed AirPods Pro 3rd gen — ~29% below expected retail.",
  confidence="medium", reason="Strong deal if genuine; 3rd generation trusted from seller."

[5] Gaming console — disc/digital edition in product_model; no variant needed
search_query="ps5 slim" title="PS5 Slim Disc Edition — Excellent Condition" price=460
desc="PS5 Slim disc edition, excellent condition, 2 controllers, 5 games. One year old."
→ listing_type="gaming_console", product_brand="Sony", product_model="PlayStation 5 Slim",
  product_variant=null, condition="Good", storage_gb=null, color=null,
  battery_health_pct=null, cycle_count=null, warranty_notes=null,
  includes_accessories=["controller","controller"],
  estimated_market_value=490.0, price_vs_market_pct=-6.1, deal_score=7, is_great_deal=true,
  is_relevant_listing=true,
  notes="PlayStation 5 Slim Good condition with 2 controllers and 5 games — ~6% below market.",
  confidence="high", reason="Complete bundle slightly below market value."

[6] Windows laptop — CPU/GPU/RAM are NOT part of product_model
search_query="asus zenbook 14" title="ASUS ZenBook 14 OLED — Ryzen 7 7730U 16GB 512GB SSD" price=680
desc="Excellent condition, barely used. Includes original charger and box. 98% battery."
→ listing_type="laptop", product_brand="ASUS", product_model="ASUS ZenBook 14 OLED",
  product_variant="16GB RAM 512GB SSD", condition="Like New", storage_gb=512, color=null,
  battery_health_pct=98, cycle_count=null, warranty_notes=null,
  includes_accessories=["charger","original_box"],
  estimated_market_value=780.0, price_vs_market_pct=-12.8, deal_score=8, is_great_deal=true,
  is_relevant_listing=true,
  notes="ASUS ZenBook 14 OLED 16GB/512GB Like New, 98% battery, charger and box — ~13% below market.",
  confidence="high", reason="CPU/GPU not in product_model; good condition and discount make this a strong buy."

[7] Smart ring — ring size in product_variant
search_query="oura ring 4" title="Oura Ring 4 — Size 9 — Brushed Titanium" price=270
desc="Like new, worn only a couple weeks. Comes with charger. Size 9 Stealth (matte black)."
→ listing_type="smart_ring", product_brand="Oura", product_model="Oura Ring 4",
  product_variant="Size 9", condition="Like New", storage_gb=null, color="Stealth",
  battery_health_pct=null, cycle_count=null, warranty_notes=null,
  includes_accessories=["charger"],
  estimated_market_value=350.0, price_vs_market_pct=-22.9, deal_score=9, is_great_deal=true,
  is_relevant_listing=true,
  notes="Oura Ring 4 Size 9 Stealth Like New — ~23% below retail.",
  confidence="high", reason="Like new condition with charger at a meaningful discount."

[8] Accessory — is_relevant_listing=false; deal fields null
search_query="macbook air m2" title="Apple USB-C Hub HDMI 4K Ethernet for MacBook" price=25
desc="Used twice. HDMI 4K, Ethernet, 2x USB-A. Works perfectly."
→ listing_type="accessory", product_brand=null, product_model="MacBook Air M2",
  product_variant=null, condition="Like New", storage_gb=null, color=null,
  battery_health_pct=null, cycle_count=null, warranty_notes=null, includes_accessories=[],
  estimated_market_value=null, price_vs_market_pct=null, deal_score=null, is_great_deal=null,
  is_relevant_listing=false,
  notes="USB-C hub for MacBook — accessory only, not the device.",
  confidence="high", reason="Accessory listing; no device deal to assess."

[9] Buyer post — is_relevant_listing=false
search_query="iphone 16 pro" title="ISO iPhone 14 Pro Max 256GB max budget $700"
desc="Looking to buy iPhone 14 Pro Max 256GB. Budget $700. DM me."
→ listing_type="buyer_post", product_brand="Apple", product_model="iPhone 14 Pro Max",
  product_variant="256GB", condition="Unknown", storage_gb=256, color=null,
  battery_health_pct=null, cycle_count=null, warranty_notes=null, includes_accessories=[],
  estimated_market_value=null, price_vs_market_pct=null, deal_score=null, is_great_deal=null,
  is_relevant_listing=false,
  notes="Buyer post — looking to purchase, not sell.",
  confidence="high", reason="Not a seller listing; no deal to assess."
"""


# ── Listing block builder ─────────────────────────────────────────────────────

def _build_listing_block(listings: list[dict]) -> str:
    lines = ["Classify the following Facebook Marketplace listings:\n"]
    for i, listing in enumerate(listings, 1):
        lines.append(f"[{i}]")
        lines.append(f"  search_query: {listing.get('search_query') or 'N/A'}")
        lines.append(f"  title: {listing.get('title') or 'N/A'}")
        price = listing.get("price")
        lines.append(f"  price: {price if price is not None else 'N/A'}")
        desc = (listing.get("description") or "").strip()
        if desc:
            lines.append(f"  description: {desc[:600]}")
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
