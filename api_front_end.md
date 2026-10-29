# API & Front End — Design and Development Guide

Status: **PLANNING — nothing in this document has been implemented yet.**
Last updated: 2026-10-23

This is the working reference for adding a public website on top of the FB Marketplace Great Deals pipeline. It records what exists today, the architecture we chose, the reasoning, and the build order. Update the checklists and the "Decisions" section as work progresses.

Legend: **[DECIDED]** = agreed with the owner. **[PROPOSED]** = recommended, not yet confirmed. **[OPEN]** = needs an answer.

---

## 1. Goal

A website that shows, per product type (for example *iPhone 15 Pro Max*):

- Average price over the last 7 and 30 days, with charts over time
- 25th-percentile ("cheapest 25%") price cutoff for each period
- Cheapest prices for each period (the 5 lowest, and full lists)
- A list of all current listings for a period, sortable by price, with filters (storage, condition)
- A homepage with the best current deals across categories

Constraints: simple to build and run, **cheap on AWS** (target: a few dollars to roughly $15/month), reuse existing Python/Terraform/dbt skills.

---

## 2. Current state (what already exists)

### Pipeline (batch, scheduled)
```
EventBridge Scheduler → Step Functions
  → Lambda "fanout" (reads DynamoDB state: initial vs periodic mode)
  → ECS Fargate: scrape (Apify) + classify (Gemini)   [Map, max 3 concurrent]
  → ECS Fargate: `run-facebook transform`  (dbt)
  → ECS Fargate: `run-facebook notify`     (SNS email alerts)
```

### Database
- Aurora Serverless v2 PostgreSQL 16, `min_capacity = 0` (auto-pauses), `max_capacity = 1`
- Currently `publicly_accessible = true` and `enable_http_endpoint = true` (RDS Data API already on)
- Schemas: `public` (categories, pipeline_runs), `facebook` (raw CDC listings, classified listings, deal_alerts, notification_log), `transformed` (dbt output)

### dbt models that matter for the website (`transform/models/transformed/`)
| Model | What it is |
|---|---|
| `dim_classified_listings` | Current listing-level table (raw + Gemini classification), one row per `fb_listing_id`. Indexed on category, product_model, listed_at. Includes `has_defect_keyword`. |
| `fct_products_daily` | One row per `product_model` per day. Rolling 1/3/7/30-day windows: counts, averages, 25th-percentile cutoff, lowest 5 listings (JSONB), plus `deal_score >= 8` and good-condition variants. Outliers (<0.3x or >3x median), "Poor" condition and defect-keyword listings are excluded. |
| `dim_product_stats` | Per-model totals (listings, average price, great-deal count). |
| `fct_deal_candidates` | Alert candidates evaluated against the 30-day benchmark. |

Most of the statistics the website needs already exist; the work is reshaping and exposing them.

---

## 3. Facts about the data that drive the design

1. **Data changes only when the pipeline runs** (a few times a day). It is read-mostly, so we compute once and cache heavily.
2. **Aurora scale-to-zero vs. a website:** web traffic would keep Aurora awake (losing savings); a paused cluster takes roughly 10–15 s to resume on the first query. The design uses caching plus a cache-warm step so visitors rarely hit the DB.
3. **Grain [DECIDED]:** one product page = one `product_model`, covering **all storage sizes, colours and variants together**. No storage/colour filters or breakdowns. `fct_products_daily` is already at this grain. Caveat: averages mix configurations (e.g. 128GB and 1TB), so the average can move with the mix of listings; label stats "all configurations".
4. **Naming problem:** `product_model` is free text from Gemini. URLs need a canonical product table with slugs (`iphone-15-pro-max`) so spelling variants do not create duplicate pages.
5. **Hardcoded date:** `fct_products_daily` filters `listed_at::date >= '2026-08-01'`. Replace it with a variable or a rolling window.
6. **Availability is unknown.** The pipeline cannot tell sold or deleted listings apart (details in Section 5.1.1). **v1 decision: do not filter on it**; the site shows listings as scraped and says so. Proper handling is the deferred active-verification step (Section 11.1).
7. **These are asking prices, not sold prices.** Label charts accordingly.
8. **Legal/ToS:** publishing aggregated stats is low risk; republishing listing text/images is higher risk. Link out to Facebook rather than copying content or images.

---

## 4. Architecture [DECIDED: Option 2 — serverless API + CDN]

Four options were evaluated; the owner chose **Option 2**.

| Option | Summary | Why not (or why) |
|---|---|---|
| 1. Static JSON on S3/CloudFront | Export JSON after each run; no API | Cheapest and simplest, but no ad-hoc queries/filters. Possible fallback. |
| **2. Serverless API (chosen)** | API Gateway + Lambda reading a `serving` schema in Aurora, behind CloudFront cache | Flexible queries, reuses Python, scales to zero, cheap with caching. |
| 3. Always-on app (ECS/ALB) | FastAPI/Next.js service on Fargate | ~$35–80/month for a low-traffic site; loses DB scale-to-zero. |
| 4. Parquet + DuckDB | Export Parquet to S3, query in browser/Lambda | Creative and cheap, but least conventional; steeper learning curve. |

### Target architecture
```
EventBridge → Step Function → scrape → classify → dbt (+ serving models)
                                                      │
                                                      └─► purge + warm CloudFront cache   (new SFN step)

Browser → CloudFront ─┬─ /*      → S3 (static frontend)
                      └─ /api/*  → API Gateway (HTTP API) → Lambda (FastAPI + Mangum)
                                                              → Aurora `serving` schema (read-only role)
```

Core principle: **dbt builds tables shaped like the website's pages; the API is a thin read layer** (mostly one indexed lookup per request); **CloudFront caches responses for hours**, and the pipeline refreshes that cache after each run.

Serving the API under the same CloudFront domain (`/api/*`) avoids CORS configuration.

### Expected cost (rough; verify against current AWS pricing)
- CloudFront, S3, API Gateway, Lambda at low traffic: a few dollars/month
- Aurora: stays mostly asleep if caching works; an awake cluster costs roughly $45+/month at 0.5 ACU minimum, which is the main cost risk
- Route 53 hosted zone (if custom domain): ~$0.50/month, plus domain registration
- Budget alarm recommended at ~$20/month

---

## 5. Build order

**Working method [DECIDED]:** one step at a time. For each step: review the design requirements, make the design decisions, build only that step, verify it, record it here, then move to the next. Later steps are not designed or built in advance. Decisions that are not needed yet (domain, frontend framework, charts, budget alarm) are made just before the step that needs them.

Do **not** complete each phase fully before the next. Build a **walking skeleton** first (Section 5.9), then widen.

### 5.0 Phase 0 — Decisions and prep
- [x] Decide v1 scope **[DECIDED]**: categories `iphone` and `macbook`; products *iPhone 16 Pro Max*, *iPhone 17 Pro Max*, *MacBook Air M2*, *MacBook Air M3*. Categories are for navigation; **stats, endpoints and metrics are per `product_model`**. Chosen because these have solid data (see Section 5.0.1).
- [x] Category source **[DECIDED]**: a **product catalog dbt seed** is the source of truth for the product → category mapping and the allowlist (see Section 5.1).
- [x] Sanity check run: each `product_model` maps to exactly one `category_key` (0 conflicting rows), so the catalog seed lines up with the data
- [x] Sold-detection checks run (results in Section 5.1.1): `is_sold` is always false; current rows span 0–21 days since `scraped_at`, ~800–1500 per day
- [x] **[DECIDED]** v1 does **not** filter by sold/age/availability at all; handled later by active verification (Section 11.1)
- [x] **[DECIDED]** Shared filter model (`benchmark_listings`) used by both `fct_products_daily` and the serving models (Section 5.1)
- [ ] Decide on custom domain vs default CloudFront URL **[OPEN]**
- [x] **[DECIDED]** Aurora is left as it is (not made private); see Section 7
- Domain, frontend framework, chart library and budget alarm: decided just before the phase that needs them, not now
- [ ] Decide frontend framework **[OPEN]** (Section 5.5)
- [x] **[DECIDED]** "a product page" = one canonical `product_model`, all storage sizes, colours and variants grouped together; no storage/colour filters or breakdowns
- [ ] Create an AWS Budgets alarm

#### 5.0.1 Snapshot of v1 products (from `output_example.txt`, 2026-10-19)

| Product | Listings (all time) | 30d | 7d | 30d avg | 30d p25 cutoff | Notes |
|---|---|---|---|---|---|---|
| iPhone 16 Pro Max | 817 | 781 | 237 | $1,135 | $1,050 | Very strong |
| iPhone 17 Pro Max | 696 | 656 | 195 | $1,544 | $1,450 | Very strong |
| MacBook Air M2 | 136 | 129 | 43 | $914 | $800 | Usable |
| MacBook Air M3 | 86 | 81 | 15 | $1,379 | $1,100 | Thin; 1d/3d windows will be mostly empty |

Known data caveats for these products:
- **Generic "MacBook Air" bucket** (412 listings) is larger than M2 + M3 combined; Gemini could not identify the chip. M2/M3 pages therefore cover only part of the market. This is a classification-quality task for later, not an API problem.
- **MacBook price depends on screen size, RAM, and storage.** The classified table has `storage_gb` but no RAM or screen size, so MacBook model-level averages mix configurations (M3 avg ≈ M4 avg is a hint). v1: model-level stats only (no storage breakdown, by decision); the mixing is accepted and labelled "all configurations". Adding RAM/screen size to the Gemini extraction is a later improvement.
- **Thin windows:** the 25th-percentile cutoff requires ≥10 listings in the window. API and UI must return/render a clear "not enough data" state.
- The mean is outlier-sensitive and shifts with the storage mix. ~~Median over the last 30 days~~ **[REVERSED 2026-10-20]**: the owner decided no median in v1; `mart_product_summary` carries only what `fct_products_daily` already provides.
- **[DECIDED]** The generic "MacBook Air" bucket (chip unknown) is **left out of v1**: no catalog row, no page. Recovering those listings is a later re-classification task (Section 11.4).
- The sample file is a single day; confirm that `fct_products_daily` holds full history before designing the charts.

#### 5.0.2 Checks to run before Phase 1 (read-only)
```sql
-- Each product_model should belong to exactly one category (expect 0 rows)
select product_model, count(distinct category_key) as n_categories
from transformed.dim_classified_listings
where is_relevant_listing and product_model is not null
group by 1 having count(distinct category_key) > 1;

-- Is isSold ever true?
select is_sold, count(*) from facebook.fb_listings_raw where valid_to is null group by 1;

-- How stale are "current" rows? (shows the ghost-listing problem)
select (current_date - scraped_at::date) as days_since_scrape, count(*)
from facebook.fb_listings_raw where valid_to is null
group by 1 order by 1 limit 40;

-- Which fields does the actor return that might signal availability?
select k, count(*) from facebook.fb_listings_raw, jsonb_object_keys(raw_payload) k
where valid_to is null group by 1 order by 2 desc;
```

### 5.1 Phase 1 — Serving layer in dbt (foundation; do this first)
Create a `serving` schema (dbt `+schema: serving`, or a `serving/` folder under models). **[PROPOSED]** models:

**Layering rule [DECIDED]:** do **not** modify `fct_products_daily`. It also feeds `fct_deal_candidates` (email alerts, joined on `product_model` + `stat_date`). The website is layered on top:
```
dim_classified_listings ─┐
                         ├─► fct_products_daily ─► fct_deal_candidates (alerts, unchanged)
product_catalog (seed)   │            │
                         └────────────┴────► serving.mart_* (join catalog: category, slug, display name)
```
Serving models are `fct_products_daily JOIN product_catalog ON product_model`, and `dim_classified_listings JOIN product_catalog ON product_model`.

**Product catalog seed [DECIDED]:** a CSV in `transform/seeds/` with columns `category_key, product_model, slug, display_name, enabled`. It is the allowlist (only `enabled` rows get pages), the product → category mapping (one row per product, so duplicates are impossible), and the slug/name source. Adding a product later = adding a row. v1 rows: the four products in Section 5.0. Add a dbt test that compares the catalog's category against the category seen on listings and warns on a mismatch, plus uniqueness tests on `product_model` and `slug`.

| Model | Grain | Purpose |
|---|---|---|
| `dim_products` | one row per canonical product | Built from the catalog seed: `product_id`, `slug`, `display_name`, `category_key`, `brand`, `product_model` |
| `mart_product_summary` | one row per product (all storage/colour variants together) | Latest-day snapshot from the latest `fct_products_daily` row: listings and average (7d/30d), `deal_score >= 8` listings/averages, 25th-percentile cutoffs, lowest-5 lists, `as_of_date`, `updated_at`. No history, no median. |
| `mart_product_daily` | product × day, last 60 days (`chart_days` var), today included | Chart series from `fct_products_daily` joined to `dim_products`: listings/avg 1d, avg 3d/7d/30d, deal8 listings 1d and deal8 avg 7d/30d, `lowest_3_deals_7d` (JSON: listing_id, url, price), 25th-percentile cutoffs 30d/7d. One tall table, no per-metric JSON blobs. |
| `mart_product_listings` | one row per listing passing `benchmark_listings`, last 60 days (`listings_days` var) | slug, listing id, URL, title, price, condition, storage_gb, color, city, `listed_at`, `days_ago` (any "last N days" filter is `days_ago < N`), `avg_price_30d`/`avg_price_7d` (from `mart_product_summary`), `price_diff_30d`/`price_diff_7d` (price minus average; negative = cheaper). No deal score, description or images. Indexed on `(slug, price)` and `(slug, listed_at)`. No availability filtering in v1. |
| `mart_top_deals` | top 10 listings per product (`top_deals_per_product` var) | Homepage deals. Source: `mart_product_listings` + `mart_product_summary`; listings from the last 30 days (`days_ago < 30`), ranked by gap below `cutoff_price_cheapest_25pct_30d` (largest gap first). Columns: slug, display_name, category_key, deal_rank, title, price, listing_url, location_city, listed_at, condition, avg_price_30d, price_diff_30d, cutoff_price_cheapest_25pct_30d. Products with no 30d cutoff (<10 listings) get no rows. |

Work items:
- [x] **DONE** Product catalog seed built and verified: `transform/seeds/product_catalog.csv` (+ a minimal `seeds/schema.yml` with `unique`/`not_null` tests on `product_model` and `slug`). The four `product_model` spellings were checked against Gemini's output and match exactly. **[DECIDED]** no extra singular tests (listing-existence and category-mismatch checks were removed to keep tests minimal); a misspelled `product_model` in the catalog would silently give an empty page, so re-check spelling by query when adding products.
- [ ] Replace the hardcoded `'2026-08-01'` date
- [ ] Create the shared **`benchmark_listings`** model (**[DECIDED]**, see 5.1.2) and refactor `fct_products_daily` to read from it, proving the output is unchanged
- [ ] No sold/age/availability filter in v1 (**[DECIDED]**, see 5.1.1)
- [ ] Add dbt tests: unique slugs, not-null keys, price sanity ranges, minimum listings per product page
- [ ] Optional: a `product_page_payload (slug, payload jsonb)` table so the main product endpoint is a single primary-key lookup (decide after seeing real payload sizes)
- [x] **DONE (not yet applied)** Read-only Postgres role `web_serving_tables_reader` with `SELECT` on `serving` only (Alembic migration; password set in Phase 4)

#### 5.1.2 Shared filter model `benchmark_listings`  **[DECIDED]**

Problem: `fct_products_daily` only counts listings that pass these rules: price > 0, condition not "Poor", no defect keyword (`has_defect_keyword`), listed on or after the start date (currently hardcoded `2026-08-01`), and price within 0.3x–3x of the model's median. The website will also compute numbers straight from `dim_classified_listings` (listings table, median). If those use different rules the page contradicts itself (e.g. chart average $1,135 vs. a median or table computed with looser rules showing $1,090).

Decision: put the rules in **one** dbt model, `benchmark_listings` ("listings that pass all rules", including the per-model median outlier trim), and have both `fct_products_daily` and every serving model read from it. Changing a rule then changes everything consistently.

Refactor safety (do this first, before building serving models):
1. Create `benchmark_listings` with the filter logic moved out of `fct_products_daily`'s `base_listings`/`model_median`/`listings` CTEs.
2. Change `fct_products_daily` to read from it.
3. Prove the output is identical: build the old and new versions side by side and diff them (expect **zero** differing rows). Review the diff before committing.
4. `fct_deal_candidates` (alerts) must keep working unchanged.
5. While here, replace the hardcoded `'2026-08-01'` with a dbt var.

Note: the fct is incremental, so verify with a full refresh into a scratch schema/target, not on the production table.

#### 5.1.1 Detecting sold / inactive listings  **[v1: NOT DONE, DEFERRED]**

**Results of the checks (2026-10-19):** `is_sold` is false for every current row; current rows are spread across 0–21 days since `scraped_at` at roughly 800–1500 per day; no conflicting category mappings.

**v1 decision [DECIDED]:** ignore sold/age/availability completely. No `last_seen_at`, no age cutoff, no status column. Listings are shown as scraped, and the UI should say availability is not verified. Everything below is background for the deferred work in Section 11.

**Important finding about last-seen tracking:** periodic runs ask the actor for listings from the **last 7 days only** (`days_listed: 7`, plus `listings_per_search: 60`). A listing older than 7 days stops appearing in results even if it is still for sale. So "not seen recently" is only meaningful for listings younger than 7 days; for older ones it says nothing. Last-seen tracking is therefore weaker than first thought, and the reliable check for older listings is active verification (11.1). Keep the two together as one future piece of work.

What the pipeline does today (`stage1.py`):
1. `is_sold` is captured from the actor's `isSold` field and is a CDC field, but Facebook search results generally hide sold items, so it may almost never be true (verify with the checks in 5.0.2).
2. **Disappearing listings are invisible.** The pipeline only reacts to records it sees. A vanished listing keeps `valid_to IS NULL` forever, so `dim_classified_listings` (filter `valid_to is null`) treats ghosts as current.
3. **No last-seen tracking.** Unchanged re-scraped listings are just counted as `skipped`; `scraped_at` is not refreshed.
4. Periodic runs use `listings_per_search: 60` and `days_listed: 7`, so "not seen in one run" does not prove a listing is gone.

Options considered:

| # | Method | Strength | Weakness | Status |
|---|---|---|---|---|
| 1 | Actor's `isSold` flag | Free, authoritative when set | **Always false in our data** (checked) | Not usable |
| 2 | **Last-seen tracking**: add `last_seen_at`, update on every sighting (including unchanged), derive status in dbt | Catches dead listings younger than 7 days | Needs `stage1.py` change + Alembic migration; guard against failed/short runs; blind to listings older than 7 days (`days_listed`) | **[DEFERRED]** with #4 |
| 3 | Age cutoff (e.g. only show listings from the last N days) | Trivial, pure dbt | Crude; hides real long-lived listings | **[DEFERRED]** (owner chose to ignore age in v1) |
| 4 | Active verification (re-check URLs of displayed listings) | Fixes dead links in "cheapest" lists | Extra cost per run; depends on scraper and Facebook blocking | **[DEFERRED]** — see Section 11 |
| 5 | User "report dead link" | Free signal | Needs a backend write path | Later |

Proposed status derivation (in dbt, not Python): `sold` if `is_sold`; `active` if seen within N days (N from run cadence, ~2–3); otherwise `stale`; only mark `stale` for a category when its recent scrape runs succeeded with a normal record count.

**Two different views of the data:**
- *Historical market stats* (average, p25, charts) describe the market over time and may include listings that later sold; they do not need an active filter.
- *Live inventory* ("cheapest available now", the listings table) must be active-only.
- The existing `lowest_5_deals_*` columns mix both (cheapest *listed* in the window, possibly sold). The site should show both "cheapest seen in the period" and "cheapest available now".

Bonus (later): with `last_seen_at`, time-to-disappear approximates time-to-sell, enabling a price vs. days-on-market chart.

### 5.2 Phase 2 — API contract (write before implementing)
Decisions so far (2026-10-23). The contract document is `api_contract.md` (draft for review); where the two disagree, update both.

**[DECIDED]** endpoints (all six are in v1; every one is a `GET`):

| Endpoint | Returns | Serving source |
|---|---|---|
| `GET /v1/categories` | Categories with product counts | `dim_products` |
| `GET /v1/categories/{key}/products` | Products with headline stats | `mart_product_summary` |
| `GET /v1/products/{slug}` | Summary stats: 7d/30d average, 25th-percentile cutoff, cheapest | `mart_product_summary` |
| `GET /v1/products/{slug}/series` | All 60 days of chart data for one product, no parameters (the frontend trims to 10/20/30 days itself) | `mart_product_daily` |
| `GET /v1/products/{slug}/listings?window=7d&sort=price_asc&page=1` | Paginated listings | `mart_product_listings` |
| `GET /v1/deals/top` | Top 10 deals per product (grouped per product) | `mart_top_deals` |

**[DECIDED]** conventions:
- Version prefix `/v1`; JSON; `snake_case` field names; prices are numbers in CAD (stated once, not per row); dates are ISO 8601; slugs use hyphens (`iphone-16-pro-max`: hyphens are the web/SEO convention).
- Envelope: every response is `{"data_as_of": "<ISO timestamp>", "data": ...}` (`data_as_of` in the body, not a header).
- "Not enough data": return `null` (for example `cutoff_price_cheapest_25pct_30d: null`) and let the frontend render "Not enough data". No extra flag.
- Whitelisted query values only; anything else gets `422`:
  - `window`: `60d`, `30d`, `15d`, `7d`, `3d`, `1d` (filter is `days_ago < N`; `1d` means listed today so far, not the last 24 hours)
  - `sort`: `price_asc`, `price_desc`, `newest`. A sort by `price_diff_30d` was dropped: within one product the average is a constant, so it gives the same order as `price_asc`. `price_diff_30d` is still returned as a column.
  - `page`: page-number pagination, **fixed page size of 20** (no `page_size` parameter in v1)
- Error shape (one format for every error):
  ```json
  {"error": {"code": "invalid_parameter", "message": "window must be one of: 60d, 30d, 15d, 7d, 3d, 1d",
             "details": {"parameter": "window", "allowed": ["60d", "30d", "15d", "7d", "3d", "1d"]}, "request_id": "abc123"}}
  ```
  | Scenario | Status | `code` |
  |---|---|---|
  | Unknown slug or category | 404 | `product_not_found`, `category_not_found` |
  | Unknown URL | 404 | `route_not_found` |
  | Bad `window`, `sort` or `page` | 422 | `invalid_parameter` |
  | Rate limit hit | 429 | `rate_limited` (with `Retry-After`) |
  | Database waking up | 503 | `database_resuming` (with `Retry-After`) |
  | Database error or unreachable | 503 | `database_unavailable` |
  | Unexpected failure | 500 | `internal_error` |
  `request_id` ties an error to a CloudWatch log line.
- OpenAPI spec generated by FastAPI doubles as the contract for the frontend.

**[DECIDED 2026-10-23]** `data_as_of` source: every serving table has its own `updated_at` (`current_timestamp` at build time). One concern drove this: the serving tables are rebuilt in one `dbt run`, but one model can fail while the others succeed (a failed model keeps its old table, so tables can have different ages). An endpoint reports the **oldest** `updated_at` of the tables it reads, and reads it in the same SQL statement as its main query (no second round trip). Endpoint to table: `categories` uses `dim_products`; `products/{slug}` uses `mart_product_summary`; `series` uses `mart_product_daily`; `listings` uses `mart_product_listings`; `deals/top` uses `mart_top_deals`. Alternatives considered: a one-row `data_freshness` model depending on every mart; reusing the summary's `updated_at` for everything.
Note: a failed `RunTransform` should also stop the Step Functions flow before the cache purge/warm, so the site keeps serving the previous consistent state.

### 5.3 Phase 3 — API application
- Location: a new package in this repo (e.g. `src/fb_marketplace_greatdeals/api/`) or a sibling `api/` directory; reuse `config.py`
- Stack: FastAPI + Mangum (Lambda adapter), Pydantic response models, SQL against `serving.*` only
- **Database access [PROPOSED: Data API for v1]:**

  | Option | Pros | Cons |
  |---|---|---|
  | RDS Data API (already enabled) | Lambda stays outside the VPC; IAM auth; no connection pool issues; works if Aurora is made private | Different driver/params; slower per call (hidden by cache); must retry on "database resuming" |
  | Lambda in VPC + psycopg | Same style as the rest of the repo | Needs a Secrets Manager VPC endpoint (~$7/month/AZ) or an env-var password, because the VPC has no NAT; limited connections at max 1 ACU, so cap concurrency |

  Keep all queries behind one small repository layer so the access method can be swapped later.
- [ ] Local dev: run `uvicorn` against a dev DB; unit tests with fixture data
- [ ] Handle the paused-DB case (retry with backoff; return a friendly error if still resuming)

### 5.4 Phase 4 — Infrastructure (new Terraform modules in `infra/terraform/modules/`)
- [ ] `api`: Lambda, API Gateway HTTP API, IAM (Data API + read-only secret), throttling, reserved concurrency cap
- [ ] `web`: private S3 bucket for the frontend
- [ ] `cdn`: CloudFront with two origins (S3 for `/*`, API Gateway for `/api/*`); cache policy (TTL ~1 hour, `stale-while-revalidate`, serve-stale-on-error); optional ACM cert (must be `us-east-1`), Route 53
- [ ] `monitoring` additions: Lambda error/latency alarms to the existing SNS topic; budget alarm

### 5.5 Phase 5 — Frontend
- Framework **[OPEN]**: Vite + React (simplest static output) vs Next.js static export or Astro (better SEO; product pages are natural SEO targets)
- Charts **[OPEN]**: Recharts (easy) or Apache ECharts (more powerful)
- Pages: home (top deals, categories), category page, product page
- Product page contents: stat cards (7d/30d avg, 25th-percentile cutoff, cheapest), price-over-time chart with 7d/30d toggle, cheapest-prices table, sortable listings table with a window selector (storage and colour are shown as plain columns, not filters)
- UX requirements: "asking prices, not sold prices" note; data-freshness indicator; links out to Facebook, no copied images; loading/error states (including a slow first load when the DB wakes)

### 5.6 Phase 6 — CI/CD and pipeline integration
- [ ] New Step Functions state after `RunTransform`: purge the CloudFront cache and warm top URLs
- [ ] Deploy flow: frontend = build, sync to S3, invalidate; API = package, update Lambda (extend CodePipeline or add GitHub Actions)
- [ ] Deployment ordering: dbt serving models must exist before an API version that queries them

### 5.7 Phase 7 — Hardening and launch
- [ ] API Gateway throttling + Lambda reserved concurrency (protects DB and bill from bots)
- [ ] Structured logging, alarms
- [ ] Privacy/terms pages and a "not affiliated with Facebook" notice
- [ ] Load test cached and uncached paths

### 5.8 Dependency map
```
Phase 0 → Phase 1 (serving models) → Phase 2 (contract) → Phase 3 (API) ─┐
                                                   └──→ Phase 5 (frontend) ─┤→ Phase 4 (infra) → Phase 6 → Phase 7
```
Phases 3 and 5 can proceed in parallel once the contract (Phase 2) is stable. Phase 4 can start early for the bucket/CDN pieces.

### 5.9 Walking skeleton (first milestone)
Prove the riskiest parts end-to-end with the thinnest slice:
1. One product (iPhone 15 Pro Max) through `dim_products` and `mart_product_summary`
2. One endpoint, `GET /v1/products/{slug}`, on Lambda behind CloudFront
3. A bare page that renders the numbers

This validates networking, Data API, caching, and deployment. Widening to more products, charts, and endpoints afterwards is mostly repetition.

---

## 6. Caching strategy
- CloudFront caches `/api/*` GET responses for about 1 hour, with `stale-while-revalidate` and serve-stale-on-error
- Pipeline post-run step purges and then warms the top product URLs, so the first visitor never wakes a cold DB
- Responses carry `Cache-Control` headers set by the API
- Because data only changes per pipeline run, a longer TTL plus explicit purge is better than a short TTL

---

## 7. Security
- **Aurora stays as it is [DECIDED]:** `publicly_accessible = true`, but its security group only allows port 5432 from the ECS tasks and a short allowlist of laptop/office IPs (see `modules/networking/main.tf`); it is not open to the internet. (An earlier version of this doc called this something to "fix before launch"; that overstated it.) The website API uses the RDS Data API (IAM over HTTPS), so it needs no inbound rule and no VPC placement, and the exposure does not widen. Keep the laptop IP allowlist current. Making Aurora private is possible later but would break direct laptop access (needs a bastion/SSM tunnel).
- The Data API needs a Secrets Manager secret in `{"username":...,"password":...}` format for a **read-only DB role** limited to the `serving` schema. The existing secret is a full database URL and cannot be used. Create this in Phase 4.
- Dedicated read-only DB role limited to the `serving` schema; the API never sees `facebook.*`
- No credentials in the frontend; no direct browser-to-DB access
- API Gateway throttling and Lambda concurrency cap
- Validate and whitelist all query parameters; cap page size
- Frontend bucket private, served only through CloudFront

---

## 8. Risks
| Risk | Mitigation |
|---|---|
| Cold-DB first request (10–15 s) | Long cache TTLs, cache-warm step, retry/backoff, UI loading state |
| Poor product naming creates thin/duplicate pages | `dim_products` normalization, minimum-listings threshold per page |
| Dead links / sold listings shown | Active-listing rule in `mart_product_listings` |
| Scraping/ToS exposure grows with traffic | Publish stats, link out, no images or copied text |
| Bot traffic raises cost or wakes the DB | Throttling, concurrency cap, budget alarm |
| Scope creep | v1 = one category, polished, then widen |

---

## 9. Open questions
1. v1 scope: iPhone only, or all categories?
2. Custom domain, or default CloudFront URL for now?
3. Make Aurora private (lose direct laptop access) or keep public temporarily?
4. Frontend: Vite + React, or Next.js/Astro for SEO?
5. Charts: Recharts or ECharts?
6. Will future features need user accounts (watchlists, custom alert thresholds)? This would add an auth layer (e.g. Cognito) in a later phase.

## 10. Decision log
| Date | Decision | Notes |
|---|---|---|
| 2026-10-19 | Architecture = Option 2 (serverless API + CloudFront cache) | Chosen by owner over static JSON, always-on app, Parquet/DuckDB |
| 2026-10-19 | Data API for DB access, one-slice-first build order | PROPOSED only; confirm in Phase 0 |
| 2026-10-19 | v1 scope: categories iphone + macbook; products iPhone 16 Pro Max, iPhone 17 Pro Max, MacBook Air M2, MacBook Air M3 | Category = navigation; stats/endpoints are per `product_model` |
| 2026-10-19 | Product catalog dbt seed = allowlist + product→category mapping + slugs | Chosen over deriving category from listings; listing-derived category used only as a consistency test |
| 2026-10-19 | `fct_products_daily` left unchanged; website served from new `serving.*` models layered on top | Protects the alert path (`fct_deal_candidates`) |
| 2026-10-19 | Active verification of listings (re-checking URLs) **deferred** | Owner wants it as a future pipeline step, not now; see Section 11 |
| 2026-10-19 | v1 ignores sold/age/availability entirely (no `last_seen_at`, no age cutoff, no status) | Check results: `is_sold` always false; scraper only returns last 7 days so last-seen is weak for older listings. UI states availability is unverified. |
| 2026-10-19 | Shared `benchmark_listings` model feeds both `fct_products_daily` and serving models | Keeps chart and table numbers consistent. Requires an output-identical refactor of the fct, verified with a zero-diff check. |
| 2026-10-19 | Serving sources: `dim_classified_listings`, `dim_categories`, `fct_products_daily`, catalog seed, plus `benchmark_listings` | Median and the listings table are computed from listings; everything else comes from the fct |
| 2026-10-19 | Aurora left as is (public endpoint, IP-allowlisted security group) | Website API uses the Data API, so no network exposure change is needed |
| 2026-10-19 | Working method: decide one step, build it, verify, then move on | Later decisions (domain, frontend, charts) made just in time |
| 2026-10-20 | Listings table: population = `benchmark_listings`; last 60 days; title included, no deal score/description/images; columns for 30d and 7d average price and the listing's price difference from each; `days_ago` computed at build time so the frontend can filter by any N days | Stat card counts match table rows for the 30d window |
| 2026-10-20 | Charts: 60-day window; one tall row per product per day; chart d = 3 cheapest listings of the last 7 days per day, with URLs; today's partial day kept (UI labels it "today so far"); one Lambda with a single `series` endpoint per product | Five charts: (a) listings and avg price per day, (b) 3/7/30-day averages, (c) deal8 listings and 7d/30d averages, (d) lowest 3 deals 7d with clickable URLs, (e) 25th-percentile cutoffs 30d/7d. Partial early windows and thin data passed through as is. |
| 2026-10-22 | Top deals: top 10 per product (not per category); eligible = `benchmark_listings` from the last 30 days; rank by gap below the 30d 25th-percentile cutoff; no discount cap, no deal score column | Within one product the cutoff is constant, so this ranking equals cheapest price first. Products with fewer than 10 listings have no cutoff and no deals. |
| 2026-10-23 | API contract decisions: all six endpoints in v1; `data_as_of` in the response body; `null` for missing stats; error shape and status table; `window` 60/30/15/7/3/1 days; `sort` price_asc/price_desc/newest; fixed page size 20; `series` has no parameters (frontend trims days) | See 5.2. `price_diff_30d` sort dropped (same order as price within a product). |
| 2026-10-23 | `data_as_of` = oldest `updated_at` of the serving tables an endpoint reads; every serving table gets an `updated_at` column | Chosen over a one-row freshness model because a failed dbt model leaves its table stale while others update |
| 2026-10-23 | Contract written as Markdown with example JSON (`api_contract.md`); product detail response is flat with all summary columns; category products show 6 headline fields; pagination block beside `data`; page past the end = 200 with empty list; deals grouped per product; `Cache-Control` set by the API (200: `public, max-age=300, s-maxage=21600`; errors: `no-store`) | The API sets the headers because it knows which responses are errors and which endpoint is which; CloudFront honours them within a safety maximum (configured in Phase 4) |
| 2026-10-23 | Phase 3 decisions: API code in a sibling `api/` directory (own `pyproject.toml`, lean dependencies, own `API_*` settings) in the same repo; RDS Data API for AWS; local development with `uvicorn` against the real Aurora over a direct connection (no local Postgres/Docker); retry budget about 20 s for a paused database; zip vs container packaging decided in Phase 4 | One repository layer; queries use named parameters (`:slug`) so the same SQL runs through SQLAlchemy locally and the Data API later. The Data API implementation waits for the Secrets Manager secret (Phase 4). |
| 2026-10-28 | dbt day buckets use Toronto time (option B): `PGOPTIONS` timezone set in `stage3_transform.py`; full refresh of `fct_products_daily` required | See 11.5. Rollout (scratch comparison, full refresh, serving rebuild) not yet run. |
| 2026-10-26 | All API timestamps (`data_as_of`, later `listed_at`) are shown in Toronto time with the UTC offset, not UTC | Implemented once in `schemas.py` (`TorontoDatetime`); needs the `tzdata` package. Day bucketing in dbt is a separate, open decision (Section 11.5). |
| 2026-10-23 | Listings endpoint stays parameterised (option A); the whole-list-per-product alternative (option B) and other caching ideas are parked for later | See 11.2 |
| 2026-10-19 | ~~Add `median_price_30d` to the product summary~~ | Reversed 2026-10-20: no median in v1 |
| 2026-10-19 | Generic "MacBook Air" (unknown chip) bucket excluded from v1 | No catalog row; revisit via re-classification |
| 2026-10-19 | One product page per `product_model`, all storage/colour variants grouped; no storage or colour filters/breakdowns | Owner decision; keeps the fct's grain, avoids splitting thin MacBook data. Averages mix configurations and are labelled "all configurations". |

---

## 11. Future work (not in v1)

### 11.1 Active listing verification step in the pipeline  **[DEFERRED]**
Add a pipeline step (e.g. a new Step Functions state after `RunTransform`, or part of `notify`) that re-checks whether listings are still available and marks them (`sold` / `gone`) in the database.

- **Scope it narrowly:** only listings that would be *displayed* — the lowest 5 per product per window, "cheapest available now", and top deals — not the whole table. This keeps cost bounded.
- **Why:** fixes the most visible problem (dead links in "cheapest" lists) that last-seen tracking (5.1.1, method 2) can only approximate.
- **Open design questions when we pick this up:**
  - How to re-check: a targeted Apify run on specific listing URLs vs. a lightweight HTTP check (Facebook may block or require login).
  - Cost per run and a hard cap on URLs checked per run.
  - Where results are stored (e.g. `verified_at`, `verification_status` columns on a listing-status table) and how the dbt status derivation prefers a verification result over the last-seen heuristic.
  - Re-check cadence (a listing shown for days should be re-verified periodically) and how to treat check failures (unknown ≠ sold).
  - Interaction with cache warming: verify first, then rebuild serving tables, then purge/warm CloudFront.
- **Related deferred work:** last-seen tracking (`last_seen_at`, 5.1.1 method 2) and an age rule. Because the scraper only returns listings from the last 7 days (`days_listed: 7`), last-seen is blind to older listings, so verification is the only reliable check for those. Plan these as one piece of work: last-seen for young listings, verification for displayed and older ones, one dbt status model combining both.
- **Not a prerequisite for v1:** v1 ships with no availability filtering (Section 5.1.1).

### 11.2 Caching and serving alternatives to revisit  **[DEFERRED]**
The v1 design is: parameterised API + CloudFront cache, warmed after each pipeline run, with the API as the fallback for misses. Limits of that design, and ideas to revisit if cold-database requests or cache misses become a problem:

- **Why warming is not a guarantee:** CloudFront has many edge locations, each with its own cache, and warm-up requests only fill the edge near where they run. Objects can also be evicted before their TTL. The number of listings URLs is large too (4 products x 6 windows x 3 sorts x pages). Purge-then-warm leaves a short gap. Aurora pauses soon after the pipeline ends, so the warm-up must run right after dbt.
- **Option B: one whole-list response per product.** Return all 60 days of listings (about 1,000 rows, roughly 50 KB gzipped for the busiest product) and let the frontend do the window, sort and paging. That removes the `window`, `sort` and `page` parameters and leaves one URL per product, which makes pre-rendering trivial. Costs: a larger payload that grows with products and days, and a heavier frontend. This changes the contract, so decide before building the frontend if it looks attractive.
- **Pre-rendered static JSON on S3 (the plan's Option 1, as a hybrid).** The last pipeline step writes the common responses (homepage deals, summaries, series, possibly all listings variants) as JSON files to S3 behind CloudFront. The database is never touched for those pages; the API Lambda stays only for dynamic requests. S3 does not evict objects, which fixes the edge-eviction problem.
- **DynamoDB as a response store.** After each run, write the prepared responses into DynamoDB and have the API read from it instead of Aurora. Single-key reads are fast, the store has no cold start, and Aurora could then stay asleep except during the pipeline. Open questions: item size limits (400 KB per item, which listings for one product might exceed), the cost versus S3 JSON, and whether it is simpler than pre-rendered S3 files.
- **Request-time caching in the Lambda** is not useful (the Lambda is short-lived); CloudFront and the stores above are the right layers.

### 11.3 Listing lifecycle: ended, sold and changed listings  **[DEFERRED]**
Related to 11.1 and 5.1.1. Today a listing that disappears from Facebook keeps `valid_to IS NULL` and is treated as current. Later work to plan together:
- Detect ended/gone/sold listings and stop showing them as current ("cheapest available now" must be active-only; historical averages may keep them).
- Re-check and update existing records by their listing URL, either through a targeted Apify run on specific URLs or a lightweight check, with a cap on URLs per run and a rule that "check failed" is not the same as "sold".
- Track `last_seen_at` (sightings, including unchanged listings), `verified_at` and a status column (`active` / `sold` / `gone` / `unknown`), and derive one status in dbt.
- Update records when a listing changes (price drops, edits) so history and alerts stay correct.
- Interaction with the cache: verify first, rebuild the serving tables, then purge and warm.

### 11.4 Other later ideas
- Add RAM and screen size to the Gemini extraction so laptop stats can be split by configuration
- Re-classify the generic "MacBook Air" bucket to recover listings for M1–M5 pages
- Median price and price vs. days-on-market charts
- Add more categories/products by adding catalog rows
- User accounts (watchlists, custom alert thresholds) if needed

---

## 12. Build log (what exists in the repo, newest last)

| Date | Step | What was built | Verified? |
|---|---|---|---|
| 2026-10-19 | Catalog seed | `transform/seeds/product_catalog.csv` + minimal `seeds/schema.yml` (unique/not_null on `product_model`, `slug`) | Yes (seed + tests passed) |
| 2026-10-19 | Shared filter | `models/transformed/benchmark_listings.sql` (table, wide columns, `benchmark_start_date` var in `dbt_project.yml`); `fct_products_daily` now reads it. Output-identical refactor checked by reading the SQL diff only, not by a build-and-compare. | Not run |
| 2026-10-19 | Pipeline | `stage3_transform.py` runs `dbt seed` before `dbt run`; a seed failure stops the transform | Not run |
| 2026-10-19 | Alerts | `fct_deal_candidates` left-joins `benchmark_listings`; new `skip_reason = 'excluded_from_benchmark'` (after poor/defect, before no_benchmark) | Not run |
| 2026-10-20 | Serving schema | `macros/generate_schema_name.sql` (custom schema used verbatim) and a `serving` folder (`+schema: serving`, tables); `models/serving/dim_products.sql` (enabled catalog rows + `dim_categories`; slug is the key) | Not run |
| 2026-10-20 | Product summary | `models/serving/mart_product_summary.sql`: one row per product from the latest `fct_products_daily` row (joined to `dim_products` first). Columns: slug, display_name, category_key, as_of_date, listings/avg 30d and 7d, deal8 listings/avg 30d and 7d, lowest-5 (all and deal8, 30d and 7d), 25th-percentile cutoffs 30d and 7d, updated_at. | Not run |
| 2026-10-20 | Daily series | `models/serving/mart_product_daily.sql` + `chart_days: 60` var: tall table, last 60 days, columns for charts a–e (see 5.1). | Not run |
| 2026-10-20 | Listings | `models/serving/mart_product_listings.sql` + `listings_days: 60` var (see 5.1). | Not run |
| 2026-10-22 | Top deals | `models/serving/mart_top_deals.sql` + `top_deals_per_product: 10` var + schema entry (see 5.1) | Not run |
| 2026-10-22 | Serving tests | `transform/tests/serving_*.sql` (catalog coverage, min 10 listings, freshness <= 2 days, price 0-10,000, summary count = listings rows); project-wide `data_tests: +severity: warn`; `stage3_transform.py` runs `dbt test` after `dbt run`, logs a warning summary, never changes step status | Not run |
| 2026-10-22 | Read-only role | `alembic/versions/c4e1a7d92f30_add_serving_reader_role.py`: role `web_serving_tables_reader` (LOGIN, no password yet), `CREATE SCHEMA IF NOT EXISTS serving`, USAGE + SELECT on existing tables, `ALTER DEFAULT PRIVILEGES` so dbt rebuilds keep SELECT. Password and Data API secret come in Phase 4. | Not run |
| 2026-10-23 | `updated_at` columns | `current_timestamp as updated_at` added to `dim_products`, `mart_product_daily`, `mart_product_listings`, `mart_top_deals` (`mart_product_summary` already had it) | Not run |
| 2026-10-23 | API contract | `api_contract.md` (draft): conventions, envelope, errors, caching headers, six endpoints with example responses | Awaiting owner review |
| 2026-10-23 | API skeleton (3a/3b) | `api/`: FastAPI app + Mangum handler, settings, one error format with request ids, `Cache-Control` middleware, repository layer (SQLAlchemy, direct connection) and `GET /v1/products/{slug}` | Unit tests were written and passed, then removed on 2026-10-28 (owner decision: no test module for now); not yet run against Aurora |
| 2026-10-28 | dbt timezone | `PGOPTIONS` timezone entry in `stage3_transform.py` | Code only; rollout not run |
| 2026-10-29 | Speed-up of `fct_products_daily` | `listings` CTE is now `as not materialized` (lookups use the `benchmark_listings` index); `benchmark_listings` runs `analyze` as a post-hook. Same results by design. | Not run; verify with the zero-diff comparison (scratch schema) and `EXPLAIN` |
| 2026-10-29 | API endpoint 2: series | `GET /v1/products/{slug}/series` (`SeriesPoint`/`ProductSeries` schemas, `get_product_series` repository method with a shared `_query` helper, route in `routes/products.py`); empty result = 404 `product_not_found` | Checked with a throwaway fake-repository script (shape, Toronto time, null handling, 404); not yet run against Aurora. No test module by owner decision; manual checks later. |

Next up: roll out the timezone change (11.5), run `GET /v1/products/{slug}` against Aurora from the laptop, then the other five endpoints one at a time (3c), the paused-database retry (3e).

### 11.5 Timezone of dbt day buckets  **[DECIDED 2026-10-28: option B, code done, rollout pending]**
The API shows timestamps in Toronto time. dbt had no timezone: `transform/profiles.yml` cannot set one, so `current_date`, `listed_at::date` and therefore `stat_date`, `listed_date`, `days_ago` and the rolling windows used the database session default (probably UTC; check with `show timezone;`). A listing posted at 9 pm Toronto time on Oct 22 landed in Oct 23's bucket.
- **Decision:** dbt sessions use Toronto time. Implemented by setting `PGOPTIONS="-c timezone=America/Toronto"` in the environment `stage3_transform.py` passes to dbt (one entry; no SQL changes, since no model uses a hardcoded timezone). Running dbt by hand requires exporting the same variable, otherwise results differ from the pipeline.
- **Rollout still to do** (not yet run): (1) compare in a scratch schema; (2) `dbt run --full-refresh --select fct_products_daily` so history uses one rule (it is incremental and only rebuilds recent days); (3) rebuild the serving tables and re-run the serving tests. `fct_deal_candidates` is never full-refreshed (`full_refresh=false`), so existing rows keep their old day logic and only new rows follow the new one; this mostly affects recent alerts around the day boundary.
