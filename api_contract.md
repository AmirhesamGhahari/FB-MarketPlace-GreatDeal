# API Contract (v1)

Status: **DRAFT for review, 2026-10-23.** Nothing in this document is implemented yet. It is the agreement between the API (Phase 3) and the frontend (Phase 5). Design decisions and their reasons are in `api_front_end.md` (Section 5.2 and the decision log); this file only specifies the shapes.

Example values are illustrative.

---

## 1. Conventions

| Topic | Rule |
|---|---|
| Method | Every endpoint is `GET` (read-only). Pagination is a query parameter on a `GET`, so each page is its own URL. |
| Base path | `/v1`. Served under the same domain as the website (`/api/v1/...` at the CDN; the Lambda sees `/v1/...`). |
| Format | JSON, UTF-8. |
| Field names | `snake_case`, same as the serving table columns. |
| Prices | JSON numbers, CAD. Currency is stated here once and not repeated per row. These are **asking prices**, not sold prices. |
| Dates | Timestamps: ISO 8601 in **Toronto time** (`America/Toronto`) with the UTC offset, `-04:00` in summer and `-05:00` in winter (`2026-10-23T10:02:11-04:00`). Calendar dates: `YYYY-MM-DD` (Toronto calendar days; see Section 3). |
| Missing values | `null`, never an empty string or `0`. The frontend decides how to render it ("Not enough data"). The 25th-percentile cutoff is `null` when the window has fewer than 10 listings. |
| Slugs | Lowercase with hyphens (`iphone-16-pro-max`). Category keys are lowercase (`iphone`, `macbook`). |

### 1.1 Envelope

Every successful response:

```json
{
  "data_as_of": "2026-10-23T10:02:11-04:00",
  "data": { }
}
```

- `data_as_of` is the **oldest** `updated_at` of the serving tables the endpoint reads (a failed dbt model can leave one table older than the others). It is when the data was built, not when the request was made.
- `data` is an object, or an array where an endpoint says so.
- The paginated listings endpoint adds a sibling `pagination` object (Section 2.5).

### 1.2 Errors

Every error uses one shape and a matching HTTP status:

```json
{
  "error": {
    "code": "invalid_parameter",
    "message": "window must be one of: 60d, 30d, 15d, 7d, 3d, 1d",
    "details": { "parameter": "window", "allowed": ["60d", "30d", "15d", "7d", "3d", "1d"] },
    "request_id": "abc123"
  }
}
```

`details` is optional (may be omitted). `request_id` matches a line in the API logs.

| Scenario | Status | `code` |
|---|---|---|
| Unknown product slug | 404 | `product_not_found` |
| Unknown category key | 404 | `category_not_found` |
| Unknown URL | 404 | `route_not_found` |
| Bad `window`, `sort` or `page` | 422 | `invalid_parameter` |
| Rate limit hit | 429 | `rate_limited` (header `Retry-After`) |
| Database waking up (paused cluster resuming) | 503 | `database_resuming` (header `Retry-After`) |
| Database error or unreachable | 503 | `database_unavailable` |
| Unexpected failure | 500 | `internal_error` |

### 1.3 Caching headers

Set by the API on every response, so they work the same locally and behind any CDN. CloudFront is configured (Phase 4) to honour them within a safety maximum.

| Response | `Cache-Control` |
|---|---|
| Successful `GET` (200) | `public, max-age=300, s-maxage=21600` (browser 5 min; CDN 6 hours; the CDN cache is purged after each pipeline run) |
| Any error | `no-store` (a temporary 503 must never be cached) |

---

## 2. Endpoints

### 2.1 `GET /v1/categories`

Categories with their product counts.

- Source: `serving.dim_products` (grouped by `category_key`)
- Parameters: none

```json
{
  "data_as_of": "2026-10-23T10:02:11-04:00",
  "data": [
    { "category_key": "iphone",  "category_name": "iPhone",  "brand": "Apple", "product_count": 2 },
    { "category_key": "macbook", "category_name": "MacBook", "brand": "Apple", "product_count": 2 }
  ]
}
```

Ordered by `category_key`.

### 2.2 `GET /v1/categories/{category_key}/products`

The products in one category, with headline stats (one card per product on the category page).

- Source: `serving.dim_products` (category name) and `serving.mart_product_summary` (stats); `data_as_of` is the older of the two tables' `updated_at`
- Errors: `category_not_found`

```json
{
  "data_as_of": "2026-10-23T10:02:11-04:00",
  "data": {
    "category_key": "iphone",
    "category_name": "iPhone",
    "products": [
      {
        "slug": "iphone-16-pro-max",
        "display_name": "iPhone 16 Pro Max",
        "listings_30d": 781,
        "avg_price_30d": 1135.0,
        "avg_price_7d": 1120.5,
        "cutoff_price_cheapest_25pct_30d": 1050.0
      }
    ]
  }
}
```

Products are ordered by `display_name`.

### 2.3 `GET /v1/products/{slug}`

Full summary stats for one product (the stat cards on the product page). All columns of `mart_product_summary` except `updated_at`, which becomes `data_as_of`. The shape is flat on purpose; unused fields can be removed later.

- Source: `serving.mart_product_summary`
- Errors: `product_not_found`

```json
{
  "data_as_of": "2026-10-23T10:02:11-04:00",
  "data": {
    "slug": "iphone-16-pro-max",
    "display_name": "iPhone 16 Pro Max",
    "category_key": "iphone",
    "as_of_date": "2026-10-23",
    "listings_30d": 781,
    "avg_price_30d": 1135.0,
    "listings_7d": 237,
    "avg_price_7d": 1120.5,
    "deal8_listings_30d": 120,
    "deal8_avg_price_30d": 1010.0,
    "deal8_listings_7d": 35,
    "deal8_avg_price_7d": 998.0,
    "cutoff_price_cheapest_25pct_30d": 1050.0,
    "cutoff_price_cheapest_25pct_7d": 1040.0,
    "lowest_5_deals_30d": [
      { "listing_id": "123456789", "url": "https://www.facebook.com/marketplace/item/123456789", "price": 700.0 }
    ],
    "lowest_5_deals_7d": [],
    "deal8_lowest_5_deals_30d": [],
    "deal8_lowest_5_deals_7d": []
  }
}
```

Notes:
- `deal8_*` = listings with deal score 8 or higher.
- Each `lowest_5_*` entry is `{listing_id, url, price}`, cheapest first, up to 5 entries. The list is `null` or empty when the window has no listings.
- Averages and cutoffs are **all configurations** (all storage sizes and colours together).

### 2.4 `GET /v1/products/{slug}/series`

All chart data for one product: one object per day, oldest first, up to 60 days. One request feeds all five charts. The frontend trims to 10/20/30 days itself.

- Source: `serving.mart_product_daily`
- Parameters: none
- Errors: `product_not_found`

```json
{
  "data_as_of": "2026-10-23T10:02:11-04:00",
  "data": {
    "slug": "iphone-16-pro-max",
    "series": [
      {
        "stat_date": "2026-10-23",
        "listings_1d": 12,
        "avg_price_1d": 1101.0,
        "avg_price_3d": 1110.0,
        "avg_price_7d": 1120.5,
        "avg_price_30d": 1135.0,
        "deal8_listings_1d": 2,
        "deal8_avg_price_7d": 998.0,
        "deal8_avg_price_30d": 1010.0,
        "lowest_3_deals_7d": [
          { "listing_id": "123456789", "url": "https://www.facebook.com/marketplace/item/123456789", "price": 700.0 }
        ],
        "cutoff_price_cheapest_25pct_30d": 1050.0,
        "cutoff_price_cheapest_25pct_7d": 1040.0
      }
    ]
  }
}
```

Notes:
- The last element is today, which is partial; the UI labels it "today so far".
- Early days may have fewer than 30 days of history behind their 30-day figures; values are passed through as they are.
- Charts: (a) `listings_1d` and `avg_price_1d`; (b) `avg_price_3d/7d/30d`; (c) `deal8_*`; (d) `lowest_3_deals_7d` with clickable URLs; (e) the two cutoff columns.

### 2.5 `GET /v1/products/{slug}/listings`

Listings behind a product page, paginated. Every listing is a benchmark listing (condition not Poor, no defect keyword, price within the product's normal range).

- Source: `serving.mart_product_listings`
- Parameters:

| Parameter | Allowed values | Default |
|---|---|---|
| `window` | `60d`, `30d`, `15d`, `7d`, `3d`, `1d` (filter: `days_ago < N`; `1d` means listed today so far, not the last 24 hours) | `30d` |
| `sort` | `price_asc`, `price_desc`, `newest` | `price_asc` |
| `page` | integer, 1 or higher | `1` |

Page size is fixed at 20 (no `page_size` parameter). Any other value for `window` or `sort`, or a `page` that is not a positive integer, returns `422 invalid_parameter`.

- Errors: `product_not_found`, `invalid_parameter`
- A page past the end returns `200` with `"data": []` (and the same `pagination` block).

Example: `GET /v1/products/iphone-16-pro-max/listings?window=7d&sort=price_asc&page=1`

```json
{
  "data_as_of": "2026-10-23T10:02:11-04:00",
  "data": [
    {
      "fb_listing_id": "123456789",
      "listing_url": "https://www.facebook.com/marketplace/item/123456789",
      "title": "iPhone 16 Pro Max 256GB",
      "price": 900.0,
      "condition": "Like New",
      "storage_gb": 256,
      "color": "Black Titanium",
      "location_city": "Toronto",
      "listed_at": "2026-10-22T14:30:00-04:00",
      "days_ago": 1,
      "avg_price_30d": 1135.0,
      "avg_price_7d": 1120.5,
      "price_diff_30d": -235.0,
      "price_diff_7d": -220.5
    }
  ],
  "pagination": { "page": 1, "page_size": 20, "total_items": 183, "total_pages": 10 }
}
```

Notes:
- `price_diff_*` = price minus the average (negative = cheaper than average).
- `condition`, `storage_gb`, `color` and `location_city` can be `null` when the listing did not provide them.
- `slug` is not repeated on each row (it is in the URL). No deal score, description or images (links out to Facebook only).
- Tie-break when sorting: `price_*` sorts break ties by newest first; all sorts break remaining ties by `fb_listing_id`.

### 2.6 `GET /v1/deals/top`

The best current deals: up to 10 listings per product, grouped by product. A deal is ranked by how far its price is below the product's 30-day 25th-percentile cutoff (largest gap first), among listings from the last 30 days.

- Source: `serving.mart_top_deals`
- Parameters: none

```json
{
  "data_as_of": "2026-10-23T10:02:11-04:00",
  "data": [
    {
      "slug": "iphone-16-pro-max",
      "display_name": "iPhone 16 Pro Max",
      "category_key": "iphone",
      "deals": [
        {
          "deal_rank": 1,
          "fb_listing_id": "123456789",
          "title": "iPhone 16 Pro Max 256GB",
          "price": 700.0,
          "listing_url": "https://www.facebook.com/marketplace/item/123456789",
          "location_city": "Toronto",
          "listed_at": "2026-10-22T14:30:00-04:00",
          "condition": "Like New",
          "avg_price_30d": 1135.0,
          "price_diff_30d": -435.0,
          "cutoff_price_cheapest_25pct_30d": 1050.0
        }
      ]
    }
  ]
}
```

Notes:
- Products are ordered by `category_key`, then `display_name`; deals within a product by `deal_rank`.
- A product with no deals (fewer than 10 listings in 30 days, so no cutoff) is **omitted** from `data`.
- Deals are asking prices from listings whose availability is not verified (see `api_front_end.md`, Section 11.3).

---

## 3. Notes and known inconsistencies (to revisit)

- **Day bucketing uses Toronto time** (decided 2026-10-28; see `api_front_end.md`, Section 11.5): `stat_date`, `as_of_date` and `days_ago` come from dbt sessions set to `America/Toronto`, so a day is the Toronto calendar day. This applies once the full refresh of `fct_products_daily` has been run.

- The lowest-N lists inside `products/{slug}` and `series` use the keys `listing_id` / `url`, while listing rows use `fb_listing_id` / `listing_url`. This comes from the existing `fct_products_daily` JSON and is kept as is for now.
- Field sets are intentionally generous (flat, all columns). Remove fields that the frontend never uses once the pages are built.
- Response sizes: `series` is up to 60 small objects; `listings` returns 20 rows per request.
