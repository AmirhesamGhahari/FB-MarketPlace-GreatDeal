# API & Front End — Design and Development Guide

Status: **IN PROGRESS.** Phases 0 to 3 code is written (dbt serving models, catalog seed, reader-role migration, API contract, all six endpoints). Phase 4 (infra: api, web, cdn, monitoring) is written and committed; 4c/4d were applied by the owner and answer through API Gateway and CloudFront, 4e (monitoring, tags, concurrency) is committed and its apply is owner-run. Rollouts and runs against Aurora (dbt serving build, timezone full refresh, Alembic migration, `uvicorn` checks) are owner-run and may still be pending; see the build log (Section 12) for "Not run" items. **Next: Phase 5 (frontend), starting with the framework/chart decisions (Section 5.5).** Phases 6 and 7 (CI/CD, hardening) have not started.
Last updated: 2026-11-06

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
| `mart_product_listings` | one row per listing passing `benchmark_listings`, last 30 days (`listings_days` var; was 60 until 2026-11-09) | slug, listing id, URL, title, price, condition, storage_gb, color, city, `listed_at`, `days_ago` (any "last N days" filter is `days_ago < N`), `avg_price_30d`/`avg_price_7d` (from `mart_product_summary`), `price_diff_30d`/`price_diff_7d` (price minus average; negative = cheaper). No deal score, description or images. Indexed on `(slug, price)` and `(slug, listed_at)`. No availability filtering in v1. |
| `mart_top_deals` | top 10 listings per product (`top_deals_per_product` var) | Homepage deals. Source: `mart_product_listings` + `mart_product_summary`; listings from the last 30 days (`days_ago < 30`), ranked by gap below `cutoff_price_cheapest_25pct_30d` (largest gap first). Columns: slug, display_name, category_key, deal_rank, title, price, listing_url, location_city, listed_at, condition, avg_price_30d, price_diff_30d, cutoff_price_cheapest_25pct_30d. Products with no 30d cutoff (<10 listings) get no rows. |

Work items:
- [x] **DONE** Product catalog seed built and verified: `transform/seeds/product_catalog.csv` (+ a minimal `seeds/schema.yml` with `unique`/`not_null` tests on `product_model` and `slug`). The four `product_model` spellings were checked against Gemini's output and match exactly. **[DECIDED]** no extra singular tests (listing-existence and category-mismatch checks were removed to keep tests minimal); a misspelled `product_model` in the catalog would silently give an empty page, so re-check spelling by query when adding products.
- [x] **DONE (code only, not run)** Replace the hardcoded `'2026-08-01'` date (now the `benchmark_start_date` var)
- [x] **DONE (code only; zero-diff comparison not run)** Create the shared **`benchmark_listings`** model (**[DECIDED]**, see 5.1.2) and refactor `fct_products_daily` to read from it, proving the output is unchanged
- [ ] No sold/age/availability filter in v1 (**[DECIDED]**, see 5.1.1)
- [x] **DONE (code only, not run)** Add dbt tests: unique slugs, not-null keys, price sanity ranges, minimum listings per product page (`transform/tests/serving_*.sql`, see build log 2026-10-22)
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
| `GET /v1/products/{slug}/listings?window=15d&sort=price_asc&page=1` | Paginated listings (windows 30d/15d/7d/3d/1d, default 15d; revised 2026-11-09) | `mart_product_listings` |
| `GET /v1/products/{slug}/listings/all` | Whole list, last 30 days, newest first, no parameters (added 2026-11-09; the product page uses this one) | `mart_product_listings` |
| `GET /v1/deals/{category_key}/top` | Top 10 deals per product of one category (grouped per product); replaces the earlier global `/v1/deals/top` | `mart_top_deals` |

**[DECIDED]** conventions:
- Version prefix `/v1`; JSON; `snake_case` field names; prices are numbers in CAD (stated once, not per row); dates are ISO 8601; slugs use hyphens (`iphone-16-pro-max`: hyphens are the web/SEO convention).
- Envelope: every response is `{"data_as_of": "<ISO timestamp>", "data": ...}` (`data_as_of` in the body, not a header).
- "Not enough data": return `null` (for example `cutoff_price_cheapest_25pct_30d: null`) and let the frontend render "Not enough data". No extra flag.
- Whitelisted query values only; anything else gets `422`:
  - `window`: `30d`, `15d`, `7d`, `3d`, `1d` (`60d` removed 2026-11-09; default `15d`; filter is `days_ago < N`; `1d` means listed today so far, not the last 24 hours)
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
- **Database access [DECIDED 2026-11-02: Lambda in the VPC + psycopg with the password in an environment variable; the Data API option in the table was considered and dropped]:**

  | Option | Pros | Cons |
  |---|---|---|
  | RDS Data API (already enabled) | Lambda stays outside the VPC; IAM auth; no connection pool issues; works if Aurora is made private | Different driver/params; slower per call (hidden by cache); must retry on "database resuming" |
  | Lambda in VPC + psycopg | Same style as the rest of the repo | Needs a Secrets Manager VPC endpoint (~$7/month/AZ) or an env-var password, because the VPC has no NAT; limited connections at max 1 ACU, so cap concurrency |

  Keep all queries behind one small repository layer so the access method can be swapped later.
- [ ] Local dev: run `uvicorn` against a dev DB; unit tests with fixture data
- [x] **DONE (not yet run against a sleeping cluster)** Handle the paused-DB case (retry with backoff; return a friendly error if still resuming), see the 2026-11-02 decision

### 5.4 Phase 4 — Infrastructure (new Terraform modules in `infra/terraform/modules/`)
- [x] **DONE (4c, applied and tested by the owner)** `api`: Lambda, API Gateway HTTP API, VPC config + security group (plus one inbound rule on Aurora's group), `API_DATABASE_URL` environment variable, throttling, reserved concurrency cap (10)
- [x] **DONE (4d, applied and tested by the owner)** `web`: private S3 bucket for the frontend
- [x] **DONE (4d, applied and tested by the owner)** `cdn`: CloudFront with two origins (S3 for `/*`, API Gateway for `/api/*`); cache policy (TTL ~1 hour, `stale-while-revalidate`, serve-stale-on-error); optional ACM cert (must be `us-east-1`), Route 53
- [x] **DONE (4e, not yet applied)** `monitoring`: rewritten for the website: new SNS topic + email subscription, four API alarms (Lambda errors, Lambda p95 duration, API Gateway 5xx, API Gateway 4xx). No new budget (account-level AWS Budgets already exist)

### 5.5 Phase 5 — Frontend
- **SEO is the top design priority** (owner wants to earn from search traffic): every choice here (rendering, markup, speed, metadata, sitemap, structured data) is judged by SEO first.
- Framework **[DECIDED 2026-11-09]**: Astro + TypeScript, static HTML pages, React islands for charts and the listings table. (Vite + React and Next.js were considered and rejected: weaker SEO and more complexity.)
- Charts **[DECIDED 2026-11-09]**: Recharts (details in 5.5.2 and the F4 log row)
- Pages: home (top deals, categories), category page, product page
- Product page contents: stat cards (7d/30d avg, 25th-percentile cutoff, cheapest), price-over-time chart with 7d/30d toggle, cheapest-prices table, sortable listings table with a window selector (storage and colour are shown as plain columns, not filters)
- UX requirements: "asking prices, not sold prices" note; data-freshness indicator; links out to Facebook, no copied images; loading/error states (including a slow first load when the DB wakes)

#### 5.5.1 Site map and page plan  **[DECIDED 2026-11-09 after the owner's answers below; images step still open]**

**Owner's answers (2026-11-09), these override the proposals below where they differ:**
1. **URLs [DECIDED]:** `/` , `/{category}/` , `/{category}/{product-slug}/` , `/{category}/{product-slug}/listings/` (for example `/iphone/iphone-16-pro-max/`).
2. **Full-listings page [DECIDED, assistant's choice]:** `noindex, follow`, left out of `sitemap.xml`, with only a small stats header (no duplicate charts). Do not also set a canonical link to another page (conflicting signals); the product page is the page that ranks.
3. **Listing titles [DECIDED]:** Facebook listing titles may be displayed. Titles in the listings table and the first-30 rows load in the browser from `/listings/all`; top deals and the 5 cheapest (with title, price, link) may be written into the HTML at build time. No listing images, no descriptions. The ToS risk noted in Section 3 item 8 is accepted by the owner for titles only.
4. **Extra pages [DECIDED]:** About / how it works, Methodology, Privacy, Terms, not-affiliated notice, 404, `sitemap.xml`, `robots.txt`, plus **Contact** and anything else a monetised site needs (FAQ; cookie notice only if analytics or ads are added). Contact needs an email address from the owner (a `mailto:` link first; a form would need a backend).
5. **Images [OPEN]:** the owner asked the assistant to find safe images. Plan: prefer generic, brand-neutral photos (no Apple logo, no identifiable products) from sources with clear licences (for example Unsplash/Pexels) or own SVG illustrations; record the source, author and licence of every image in one file (`web/IMAGES.md`); owner reviews before launch. Decide at the design step.
6. **Design system first [DECIDED]:** build fonts, colours, spacing and reusable components before the pages; every later page step uses them.
7. **Sparse home page [DECIDED]:** the home page's weight comes from benefit copy, how-it-works, top deals and trust sections, not from a category grid.

Owner's outline:
- **Home:** what the site is, what it does, how it helps users (benefit-focused copy); the product categories as links; best deals.
- **Category page:** category intro, a card per product (the `CategoryProductCard` fields) linking to the product page, and some top deals per product.
- **Product page:** the product's card/stat cards, the charts, the full top-deals list, the first 30 listings, and a link to a separate full-listings page.
- **Full-listings page** (per product): all listings plus some general stats/charts.
- Visual goal: a polished, professional look (images, typography, layout templates, user-friendly).

Refinements proposed:
- **URLs (open):** `/` , `/iphone/` , `/iphone/iphone-16-pro-max/` , `/iphone/iphone-16-pro-max/listings/` (hierarchical, shallow, readable). Needs the category in the build; the API slug stays the key.
- **SEO risk on the listings page:** repeating the product page's charts and stats makes near-duplicate content. Keep only a small stats header there, and either `noindex` it or set a canonical link to the product page; the product page is the page to rank.
- **First 30 listings on the product page:** render in the browser from `/listings/all` (island), not baked into the HTML; listing text is Facebook's content (Section 3, item 8), and the rows add little ranking value. The baked HTML keeps the stats, the 5 cheapest (links) and the top deals.
- **Pages needed beyond the outline** (trust, SEO, and required before any ads/affiliate income): About / how it works, **Methodology** (how averages and the 25th-percentile cutoff are computed, "asking prices, not sold prices"), Privacy, Terms, "not affiliated with Facebook/Apple" notice, a 404 page, `sitemap.xml`, `robots.txt`, per-page title/meta/Open Graph, structured data.
- **Images:** no Facebook listing images; own illustrations/icons, or properly licensed images (Apple product photos are copyrighted).
- **Home with two categories** will look sparse; plan the layout so it still reads well (benefit sections, deals, how-it-works) and grows as products are added.
- **Design system first:** one font pair, colour palette, spacing and a small set of reusable components, so every page looks consistent. Styling choice (Tailwind vs plain CSS) is still open.
- The `/deals/{category}/top` endpoint already gives top deals per product, so the category page and the home page can reuse it at build time.

#### 5.5.2 Design decisions  **[round 1 DECIDED 2026-11-09]**
- **Styling [DECIDED]:** Tailwind CSS.
- **Look and feel [DECIDED]:** clean minimal (white space, thin borders, one accent colour; trustworthy, Stripe/Linear feel), with a data-dashboard touch for numbers.
- **Accent colour [DECIDED]:** blue (green and red stay reserved for "cheaper than average" / "pricier").
- **Fonts [DECIDED]:** one font, Inter, self-hosted (no third-party font requests).
- **Round 2 [DECIDED 2026-11-09]:** light mode only (dark mode can be added later); Recharts for charts; price signal = coloured badges (green pill for cheaper than average, red for pricier, e.g. "-$235 vs avg"); working site name "Great Deals" (`web/src/lib/site.ts`). Assistant defaults: mobile-first, content column about 1100 px (`max-w-5xl`), wide tables scroll sideways on small screens.

#### 5.5.3 Category page decisions  **[DECIDED 2026-11-13; built the same day, see build log]**
- Route `src/pages/[category]/index.astro` (`/iphone/`, `/macbook/`): breadcrumb, heading and intro text (drafted by the assistant, reviewed by the owner), a card per product (`CategoryProductCard` fields), and **3 top deals per product** (`GET /v1/deals/{category}/top`, up to 10 available). No mini charts on the cards for now. A product without data shows an unlinked card (per `api_contract.md` 2.2).
- New pieces: `ProductCard.astro`, `PriceBadge.astro` (green/red), deal row component, `getTopDeals()` and types in `api.ts`, a price-difference formatter in `format.ts`.
- **Open data issue (2026-11-13), full write-up in Section 13.1:** the top deals for iPhone 16 Pro Max include listings from US cities (Louisville, Cape Coral, Lafayette) at the cheapest ranks, while the newest 100 listings are almost all Canadian (Toronto area, Ottawa, Quebec). `dim_toronto_area_cities` (cities under 90 km from Toronto) is used **only** by `fct_deal_candidates` (email alerts, `within_90km_toronto`); `benchmark_listings` and the serving models have no location filter, so website averages, cutoffs and deals can include non-Canadian listings. Not changed; owner to decide where/whether to filter (note: the iphone config also searches Vancouver, which the 90 km Toronto list would exclude).

#### 5.5.4 Site structure and navigation design  **[DECIDED 2026-11-18 after a long discussion with the owner; supersedes the URL list in 5.5.1 item 1; nothing built yet]**

**Goals:** attractive and memorable, strong SEO, and room for money (ads, affiliate, later email alerts).

**Top bar (not a sidebar):** Products, Market Insights, Top Deals, All Listings, a search icon, "How it works", and later a "Get alerts" button. Everything else goes in the footer.
- **Products** = full two-level mega menu (category, then product) leading to the product overview page.
- **Market Insights / Top Deals / All Listings** = a short menu of categories only; each category leads to a **hub page** that shows a card for every product of that category, and each card leads to that product's page of that kind. Keeps the header light (10 categories x 10 products would be about 400 links in every page header if all four menus were full) and the hubs are useful internal-linking pages. Owner may switch to full menus in all four later.
- **Desktop vs touch:** the same HTML; CSS `@media (hover: hover)` decides. Desktop: menus and card extras open on hover (also on keyboard focus). Touch: hamburger drawer with tap-to-expand rows; card extras are shown as a compact block or behind a tap ("Details"); deals as a swipe row. Nothing important may depend on hover. Product cards always show name, avg 30d price and listing count (SEO text); hover only adds the mini chart and top 3 deals.
- **Search box [DECIDED, build later]:** static, in-browser search over category and product names (for example Pagefind), no server.

**Routes (Way 2: one separate page per section, owner chose this over a single page with `#` anchors):**

| Page | URL | Indexed |
|---|---|---|
| Home | `/` | yes |
| Categories overview | `/categories/` (decided 2026-11-18) | yes |
| Category | `/{category}/` | yes |
| Product overview | `/{category}/{slug}/` | yes |
| Product market insights | `/{category}/{slug}/market-insights/` | yes |
| Product top deals | `/{category}/{slug}/top-deals/` | yes |
| Product all listings | `/{category}/{slug}/listings/` | **no** (`noindex, follow`, not in sitemap, not blocked in robots.txt) |
| Insights hub and category hub | `/market-insights/`, `/market-insights/{category}/` | yes |
| Deals hub and category hub | `/top-deals/`, `/top-deals/{category}/` | yes |
| Listings hubs | `/all-listings/`, `/all-listings/{category}/` | **no** (`noindex, follow`) |

**Anti-duplication rules (the pages share data, not content):**
1. Each page owns one main thing: overview = stat cards, written summary, short buying guide and FAQ, plus only a small taste (one fixed 15-day chart, top 3 deals) with links; insights = all five charts (a-e of the 2026-10-20 decision) with period filters; deals = the full top-deals list; listings = the full table.
2. Each page has its own generated text (a few paragraphs from its own numbers), title, description and H1, and is its own canonical.
3. No big block (a whole chart set or table) is copied between pages.
4. Different title/heading/URL alone is **not** enough if the body is mostly the same; Google compares the main content.
5. Filters on the insights/listings pages run in the browser (React islands); the default view is baked into the HTML so Google can read it.

**Why the listings pages are `noindex, follow`:** mostly a table of Facebook listing titles (no original text, low quality for Google), data changes daily so results go stale, rows load in the browser so the HTML is nearly empty. `follow` keeps link value flowing to product pages. Do not also disallow them in `robots.txt`, or Google cannot see the `noindex`.

**Home page:** full-screen sections using **CSS scroll-snap** (no JavaScript scroll takeover); on touch screens gentle "proximity" snap or normal scroll; subtle fade-in animations only. Real HTML text (H1, H2) in every section. Order: name and promise with a main button; what the site does and 3-step how it works; categories (scrolling reveals products, all links); best deals vs average price (**biggest discounts**, not random) with one or two charts loaded lazily; trust numbers (listings tracked, data updated at); FAQ; email-alert signup placeholder (feature itself is future work). Hero uses gradient or own illustration until the images step.

**Category pages:** a card per product; mini 7-day chart as a build-time inline SVG (no JavaScript), reversing the 2026-11-13 "no mini chart for now"; needs the `series` endpoint per product at build (to verify). Top 3 deals on hover or tap.

**Product overview extras:** a data-generated summary sentence block, FAQ, methodology note, related products, `BreadcrumbList` structured data, visible "last updated".

**Money design [DECIDED]:** ad slots reserved in the layout but rendered only when a settings flag is on (no empty boxes, no layout shift later); no ads on the home page or above the first screen; an affiliate "compare with new/refurbished" placeholder on product pages (visible disclosure required); email alerts and sponsors are later.

**Launch pages:** About, How it works / Methodology (with a short FAQ), Contact (needs the owner's email), Privacy, Terms, Disclosure (not affiliated with Facebook, asking prices, affiliate/ads), 404, `sitemap.xml`, `robots.txt`. Later: separate FAQ, glossary, guides/blog, alerts page.

**Other decisions:** custom domain will be bought soon, so keep the site address as one setting (`site` in `astro.config.mjs`) and use the CloudFront address until then; English only; the product charts are the five already agreed (decision log 2026-10-20), no new chart choice needed.

**Impact on built pages:** product page `[category]/[slug].astro` becomes the overview and loses nothing it has now; new routes for insights, deals, listings, hubs, search, nav, footer, home snap sections; `Base.astro` gets the nav and footer; category cards get the hover/tap panel and sparkline. Build order is decided step by step, decisions first.

#### 5.5.5 Frontend build steps (planned 2026-11-18; one step at a time: explain, owner decides, build, verify, log)

Order logic: data layer, then shared pieces, then pages from the most reused to the least, home last (it reuses everything), then plumbing and polish.

| Step | What | Owner decides | Concept taught |
|---|---|---|---|
| F1 | **Data foundations:** extend `api.ts` (`series`, `listings/all`, types); one build-time `catalog.ts` that loads categories and products once (nav, hubs, sitemap, search use it); `site.ts` gets nav labels, `ADS_ENABLED` flag, reserved-slug list (the planned reserved-name check was dropped on 2026-11-18: category keys come from the owner's own catalog seed, so a clash is very unlikely) | Nothing big (reserved names) | Module-level caching, why pages share one fetch |
| F2 | **Header, footer, mobile drawer** in `Base.astro`: Products mega menu, three category-level menus, hover vs touch (`@media (hover: hover)`), search icon placeholder, footer link groups, skip link | Menu look (flyout layout, drawer style), footer columns | CSS-only interactions, small client scripts vs React, accessibility basics |
| F3 | **Shared components:** `SectionHeading`, `LastUpdated`, `Disclosure`, `AdSlot` (renders nothing unless flag on), product sub-tab bar (Overview / Market insights / Top deals / Listings), `JsonLd` helper, `generated text` helpers (summary sentences from numbers) | Tone of generated text | Component props, slots, why generated text matters for SEO |
| F4 | **Chart toolkit:** add `@astrojs/react` + Recharts; the five charts (a-e of 2026-10-20), 7d/30d/period filter, sparkline as build-time inline SVG; chart colours via the dataviz guidance; mobile behaviour; text fallback under each chart | Chart look (colours, line vs area), default periods | What an island is, `client:visible`, build-time vs browser rendering |
| F5a | **Product overview** (`[category]/[slug]/index.astro`; moves the current `[slug].astro`): stat cards, generated summary, one fixed 15-day chart, top 3 deals, FAQ, methodology note, related products, breadcrumb schema | Section order, FAQ wording | Nested dynamic routes |
| F5b | **Market insights page** (all five charts, filters, own intro text) | Chart order | Filters as browser-side state |
| F5c | **Top deals page** (full list with `DealRow`, own intro text) | Columns shown | Reusing components with different data |
| F5d | **Listings page** (`noindex, follow`): table from `/listings/all`, sort and filter in the browser; **needs 13.2 deployed first** | Table columns, default sort | Client-side fetching, loading and error states, `noindex` |
| F6 | **Category page upgrade** (cards with hover/tap panel, sparkline, top 3 deals) and the **Categories overview** `/categories/` | Card layout, panel contents | Progressive enhancement |
| F7 | **Hubs:** `/market-insights/`, `/top-deals/`, `/all-listings/` and their `{category}` pages (cards linking to each product's page of that kind; listing hubs `noindex`) | Card content per hub | Reusing one card component in three hubs |
| F8 | **Home page:** snap sections, categories reveal, biggest-discount deals, trust numbers, FAQ, alert signup placeholder | Section copy, animation level | CSS scroll-snap, lazy loading |
| F9 | **Trust pages:** About, How it works (Methodology + FAQ), Contact (needs owner's email), Privacy, Terms, Disclosure, 404 | Wording review | Why Google and ad networks check these |
| F10 | **SEO plumbing:** `@astrojs/sitemap` (excluding noindex pages), `robots.txt`, canonical/OG checks, BreadcrumbList and FAQ JSON-LD, `astro check`, link check | Nothing big | How to verify SEO output |
| F11 | **Search** (Pagefind, built after the site build; header search box) | Result look | Static search index |
| F12 | **Images pass:** gradients/own SVGs first, then licensed or generic images with `web/IMAGES.md` | Which images | Licences, image performance (size, `loading=lazy`, dimensions) |
| F13 | **Quality pass:** Lighthouse (speed, accessibility, SEO) on mobile and desktop, fixes | Nothing | Core Web Vitals |

**Dependencies outside the frontend:** 13.2 (deploy `/listings/all`) before F5d; **13.1 (non-Canadian listings) should be decided before F8**, because the home page puts deals and averages up front and the numbers change after the fix; 13.3 (CloudFront `index.html` function) and the pipeline rebuild automation belong to Phase 6; the Apify secret (13.6) is unrelated to the frontend.

**Existing pages:** `index.astro` placeholder is replaced in F8; `[category]/index.astro` is upgraded in F6; `[category]/[slug].astro` moves into `[slug]/index.astro` in F5a; `Base.astro` is extended in F2.

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

This validates networking, database access, caching, and deployment. Widening to more products, charts, and endpoints afterwards is mostly repetition.

---

## 6. Caching strategy
- CloudFront caches `/api/*` GET responses for about 1 hour, with `stale-while-revalidate` and serve-stale-on-error
- Pipeline post-run step purges and then warms the top product URLs, so the first visitor never wakes a cold DB
- Responses carry `Cache-Control` headers set by the API
- Because data only changes per pipeline run, a longer TTL plus explicit purge is better than a short TTL

---

## 7. Security
- **Aurora stays as it is [DECIDED]:** `publicly_accessible = true`, but its security group only allows port 5432 from the ECS tasks and a short allowlist of laptop/office IPs (see `modules/networking/main.tf`); it is not open to the internet. (An earlier version of this doc called this something to "fix before launch"; that overstated it.) The website API uses the RDS Data API (IAM over HTTPS), so it needs no inbound rule and no VPC placement, and the exposure does not widen. Keep the laptop IP allowlist current. Making Aurora private is possible later but would break direct laptop access (needs a bastion/SSM tunnel).
- The API connects as a **read-only DB role** limited to the `serving` schema (`web_serving_tables_reader`). Its password is passed to the Lambda as an environment variable (Section 5.3 decision); the existing Secrets Manager secret holds the admin database URL and must not be used by the API. Set the role's password in Phase 4b.
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
| 2026-10-30 | Listings endpoint: two queries (meta + page), `page` capped at 30 (total_pages capped too), known product with no listings = 200 empty, unknown slug = 404 | Cap means 600 listings reachable per sort order; raise `MAX_PAGE` in `routes/products.py` if needed. `data_as_of` comes from `mart_product_listings` alone (falls back to `dim_products` only if that table is empty); `dim_products` is just the existence check |
| 2026-10-30 | Category endpoints are catalog-based: categories, counts and product cards come from `serving.dim_products` (the catalog seed), products without data appear with null stats; unknown category = 404; `data_as_of` = `dim_products` build time (changed from the summary table's on 2026-10-30, to keep the SQL simple); order by `category_key` / `display_name` | The API role can only read `serving`, so it reads `dim_products` (the seed, enabled rows) instead of the seed table. A card for a product without data would link to a 404 page, so the frontend must handle null stats. |
| 2026-10-30 | Deals: flat rows grouped into per-product objects in Python; `data_as_of` from `mart_top_deals` only; products without deals omitted; one endpoint, `GET /v1/deals/{category_key}/top` (no global `/v1/deals/top`); unknown category = 404; a category with no deals = 200 with `[]` while other categories have deals, 503 if the whole table is empty | Path chosen over `?category_key=` by the owner; the global route and the fallback timestamp were dropped on 2026-10-30. A path parameter is part of the CDN cache key automatically. The homepage makes one request per category. |
| 2026-11-02 | Paused-database handling (3e): retry **connection** attempts inside the request up to 3 attempts with a fixed 4 s pause (worst case 23 s, under API Gateway's 30 s); query failures are not retried; if the budget runs out, `503 database_resuming` with `Retry-After: 15`; per-attempt `connect_timeout` lowered from 30 s to 5 s | Owner chose in-API retry (option B) over fail-fast (A) so most visitors see a slow page instead of an error. Every connection failure is labelled `database_resuming` (a truly down database looks the same after 20 s). Attempt count fixed instead of a time budget (simpler; same pattern as `MAX_RETRIES` in stage2). 4 attempts would need up to 32 s and break API Gateway's 30 s limit. |
| 2026-11-02 | **Database access reversed: Lambda in the VPC with psycopg (SQLAlchemy `NullPool`), not the RDS Data API** (supersedes the 2026-10-23 Data API decision). The Lambda joins the existing VPC, gets its own security group, and Aurora's security group gets one inbound rule for it (no NAT, no VPC endpoint; $0 extra). The reader password is passed as a Lambda environment variable (`API_DATABASE_URL`), set by Terraform from `terraform.tfvars` (password also ends up in Terraform state; accepted because the role is SELECT-only on `serving`); reserved concurrency capped at about 5 to respect Aurora's connection limit at 1 ACU. Other decisions: Lambda packaged as a **zip** (deps installed for Linux); Phase 4 before the frontend | Chosen after comparing: less code than a Data API adapter, no unverified Data API assumptions (error codes, timestamp timezone), and the retry logic stays as tested locally. Costs accepted: password readable in the Lambda console by account admins; Aurora's inbound rules grow by one; a later Lambda call to S3 or another AWS service would need a gateway/interface endpoint or NAT. `NullPool` so a warm Lambda never holds an idle connection that would stop Aurora from auto-pausing (to confirm in 3c). Phase 4 split: 4a code cleanup (done), 4b Lambda environment/password handling, 4c Lambda + API Gateway + security group, 4d S3 + CloudFront, 4e monitoring + budget alarm. |
| 2026-11-02 | Phase 4b: reader password handling | The password of `web_serving_tables_reader` is set **by hand once** (`ALTER ROLE web_serving_tables_reader PASSWORD '...'`) and the same value goes into `terraform.tfvars` as the new sensitive variable `api_reader_password`; it is not set inside the Alembic migration. In 4c Terraform builds `API_DATABASE_URL` for the Lambda from the Aurora endpoint, database name, role name and this variable, wrapping the password in `urlencode()` so special characters are safe. | Keeps the secret out of the repo and the migration. Needs the variable present in `terraform.tfvars` before the next `terraform plan`. |
| 2026-11-02 | Phase 4c decisions: Lambda in both **private** subnets (free; Aurora's subnet group needs 2 AZs anyway; public vs private only differs by route table); `python3.12` on `arm64`, **512 MB**, **28 s**; API Gateway **HTTP API** with one `$default` catch-all route, throttle **2 req/s, burst 5**; `reserved_concurrency` is an optional variable (default unreserved) because the account's Lambda concurrency quota is **10** (nothing can be reserved, and the 10 are shared with the fanout Lambda); `sslmode=require` in `API_DATABASE_URL`; 14-day logs; IAM = `AWSLambdaVPCAccessExecutionRole` only. Zip built by `api/build_lambda.sh` before `terraform apply`. **Deployment automation (Phase 6): the same CodePipeline with a second CodeBuild project (`api-build`) as a parallel action in the Build stage**; it hashes `api/src` + `api/pyproject.toml` and skips if the hash stored on the Lambda (tag) is unchanged, so no `git diff` is needed; the Lambda then gets `lifecycle { ignore_changes = [filename, source_code_hash] }` | Why: with a quota of 10, a throttle of 10 req/s could occupy every slot while Aurora wakes (about 23 s per request) and starve the fanout Lambda that starts the pipeline; request a quota increase (Service Quotas) before reserving concurrency. Noted for Phase 6: the existing buildspec uses `git diff HEAD~1 HEAD` but the source action has no full clone, so its skip logic probably never triggers (check a CodeBuild log). The fanout Lambda is deployed by Terraform (`archive_file`), not by the pipeline. |
| 2026-11-03 | Phase 4d decisions: default `*.cloudfront.net` address for now (custom domain later: certificate in `us-east-1` + alias record); `/api` is a path convention CloudFront uses to pick the origin (`/api/*` = API Gateway, everything else = private S3), the full path is forwarded and **Mangum strips it** (`api_gateway_base_path="/api"`); API cache policy: lifetime from the API's header, CloudFront **max TTL 24 h** (a ceiling against bad headers, not an override), min and default 0, all query strings in the cache key; success header is now **`public, max-age=120, s-maxage=21600, stale-if-error=86400`** (browser 2 min, CDN 6 h, expired copy served for up to 24 more hours on a 5xx or unreachable origin; errors stay `no-store`); **no `stale-while-revalidate`**; Price Class 100; no origin lockdown for now; placeholder `index.html` in the bucket | Why no `stale-while-revalidate`: browsers honour it too, so returning visitors could see up to a day old data first (there is no CDN-only version). Cost of leaving it out: when a CDN copy has expired, no pipeline has run for 6+ h and Aurora is asleep, one visitor waits up to about 23 s and then gets the stale copy instead of an error. The 4xx responses are never served stale. A stale copy served by CloudFront carries an `Age` header, so browsers treat it as already expired. The lockdown (secret header from CloudFront checked by the app, about 20 lines) would protect the data but not the shared throttle bucket (HTTP APIs cannot use WAF, as far as known); deferred to Phase 7 if bots appear. |
| 2026-11-06 | Phase 4e decisions: **Lambda concurrency quota is now 1000** (was 10); the API gets **reserved concurrency 10** (`api_reserved_concurrency`, default now 10) as a cap protecting Aurora's connections and a guarantee; AWS keeps 100 unreserved, so the fanout Lambda is no longer at risk. **Monitoring**: `modules/monitoring` (a leftover of the forked ticket project, never wired into the root `main.tf`) is rewritten to hold only website alarms plus a new SNS topic `<app>-alerts` subscribed to `alert_email` (separate from the `deal_alerts` topic); the old pipeline alarms were deleted as dead code. Four alarms on the API, each needing **2 five-minute windows in a row**: Lambda `Errors` > 0, Lambda p95 `Duration` > 20 s, API Gateway `5xx` > 0, API Gateway `4xx` > 20. No CloudFront alarm; no new budget (the account already has AWS Budgets alerts). **Tagging**: provider `default_tags` `App = <app_name>` and `ManagedBy = terraform` on every taggable resource; no per-component tags (names already carry the component); activate `App` as a cost allocation tag in Billing; find resources with Tag Editor, `terraform state list` and the `fb-marketplace-greatdeals-` name prefix | Why 4xx and not 429: HTTP APIs publish no separate 429 metric (as far as known), so throttling is counted inside `4xx` together with the API's own 404/422; an exact 429 alarm would need stage access logs plus a metric filter. Alarm 3 (5xx) is the one that catches `database_resuming`/`database_unavailable`: the app returns them on purpose, so the Lambda `Errors` metric does not count them. The `Stage = "$default"` metric dimension is unverified until the first apply (check the metric exists in the console). Pipeline alarms (scraper failures, Step Functions) are a separate piece of work if wanted later. The first apply sends a confirmation email to `alert_email` that must be clicked once. |
| 2026-11-09 | Phase 5 decisions: **SEO is a top priority and must drive every frontend design choice** (the owner plans to earn money from search traffic); framework = **Astro + TypeScript**, React only for interactive islands; pages are static HTML built after each pipeline run (SEO text and headline numbers baked into the HTML), interactive parts (charts, listings table) load data in the browser; listings: a **new endpoint `GET /v1/products/{slug}/listings/all`** returns the whole list per product (option B of 11.2) and the existing parameterised `/listings` stays; both are limited to the **last 30 days** (60d window removed, `mart_product_listings` `listings_days` 60 to 30) and the parameterised default window is now **15d**. Contract (`api_contract.md` 2.5, 2.5.1) and code updated 2026-11-09 (see build log). Earlier note: contract change pending: `api_contract.md`, the listings route and `mart_product_listings` consumers must be updated before the product page is built. Details of the build-after-pipeline mechanism (CodeBuild/Step Functions) belong to Phase 6. Charts library and styling still open. |
| 2026-11-09 | Site plan decisions (see 5.5.1): URLs `/{category}/{product-slug}/` and `/{category}/{product-slug}/listings/`; listings page `noindex, follow` and out of the sitemap; listing titles may be shown (browser-loaded in tables, build-time for top deals and 5 cheapest); trust pages plus Contact; design system before pages; images via licensed/generic sources with a licence record (open) | Owner's answers to the assistant's seven proposals; Node 26 installed and Astro project created the same day |
| 2026-11-18 | Site structure and navigation design (see 5.5.4): top bar with Products (full menu) and three category-level menus leading to hub pages; **separate pages per product section** (overview, market-insights, top-deals, listings) instead of one page with `#` anchors; listings pages and hubs `noindex, follow`; hover only as an extra, touch gets tap/drawer patterns; CSS scroll-snap home; search box; ad slots behind a flag and affiliate placeholder; launch trust pages; domain later | Owner's design discussion. Rule: pages share data, never main content. Supersedes the URL list in 5.5.1 item 1. |
| 2026-11-18 | F1 decisions: categories overview URL is **`/categories/`**; ~~a clash check for reserved page names~~ (dropped 2026-11-18, not needed); the ads switch is a **constant in `site.ts`** (`ADS_ENABLED`); one shared build-time catalog (`catalog.ts`) used by all pages | Owner's answers; replaces the 'name to confirm' note in 5.5.4 |
| 2026-11-18 | F2 decisions: Products menu = two-pane flyout; mobile menu = slide-in drawer; header sticky; footer = three link columns plus notice; menus list only products that have data | Owner's answers (all the recommended options) |
| 2026-11-18 | F3 decisions: product tabs = underline style, not sticky; generated text = neutral and factual (no buying advice); build an internal `/styleguide/` page | Owner's answers (all recommended). Generated text states what numbers say, since the data are asking prices. |
| 2026-11-18 | URL order confirmed: **product-first** (`/{category}/{slug}/{section}/`); each page has exactly one URL; the hub trees (`/market-insights/`, `/market-insights/{category}/`, and the same for top-deals and all-listings) stop at the category and their product cards link to the product-first URLs; the affiliate `Disclosure` variant is kept (unused until the first affiliate link) | Owner's answers. A second URL for the same page (section-first) would be duplicate content and is not planned. |
| 2026-11-19 | F4 decisions: chart data baked in at build time (not fetched in the browser); two-measure charts as two stacked panels (no dual axis, per dataviz rules); period buttons 10/20/30/60 days, default 30; overview chart = daily average plus 7-day average over a fixed 15 days; categorical colours = first three validated palette slots, legend plus data table on every chart | Owner's answers (all recommended). The chart `a` and `c` of the 2026-10-20 decision are each split in two panels (price line, count columns). |
| 2026-11-19 | F5a decisions: H1 = "Used {name} Price in Canada"; the 5-cheapest block is replaced by the 5 best deals (owner chose 5, not 3); 6 stat cards in two rows; extras = related products only (no FAQ and no methodology note on the overview for now) | Owner's answers. Also noted: Google shows FAQ rich results only for well-known government and health sites since 2023, so no FAQ markup is planned. |
| 2026-11-19 | F5b decisions: H1 "Used {name} Price History in Canada"; 4 generated key takeaways above the charts; a visible 14-day daily table (not only the folded tables under the charts) | Owner's answers (all recommended). The page is different from the overview because it owns the full charts, takeaways and daily table, while the overview only samples one chart. |
| 2026-11-19 | F5c and F5d decisions: deals as a ranked list of deal rows (not a table) with a generated intro and a "How deals are chosen" section; listings table with the full column set; controls = sort and period (default 15 days), 25 rows per page with page buttons, no title search | Owner's answers (all recommended). Built together at the owner's request. |
| 2026-11-19 | F6 decisions: card extras open as a hover panel on mouse devices and are shown inline on touch devices; extras = two 7-day sparklines (price, listings) plus the top 3 deals; the "Best current deals" section below the cards is removed; /categories/ = large gradient cards in a grid (hover list of models on mouse devices, inline on touch) | Owner's answers (all recommended). Supersedes the mini-chart exclusion of 5.5.3. |
| 2026-11-19 | F7 decisions: section root pages show category cards only; Market Insights cards show the 30-day trend plus the 7-day charts on hover (inline on touch); hub text is generated from the numbers | Owner's answers (all recommended). Defaults chosen by the assistant: deals cards show the best deal with the top 3 on hover; listings cards show count and average. |
| 2026-11-19 | F8 decisions: benefit headline with the site name small above it; categories as cards with their models fading in (one section, not a screen per category); one chart (the most-listed model's price trend); extras = trust numbers strip, FAQ and a "deal alerts coming soon" note (no email box) | Owner's answers. The owner chose to build F8 before deciding 13.1. |
| 2026-11-20 | F9 and F10 decisions: Contact email is a placeholder until the owner has an address; Privacy describes today's reality (no analytics, cookies or ads) and will be updated when that changes; About presents an independent project without a name; the style guide exists only in `npm run dev`. Defaults chosen by the assistant: default share image made now, WebSite and Organization structured data only (no Product or Dataset markup), `astro check` and a link/SEO checker added | Owner's answers (all recommended). |
| 2026-11-20 | F11 decisions: search is a magnifier icon in the header that opens a search panel (with the `/` shortcut); it finds models, categories and the two info pages only; the panel is Pagefind's ready-made one in the site's colours | Owner's answers (all recommended). |
| 2026-11-20 | Catalog expansion decisions: the owner supplied the list of 69 product models and asked the assistant to assign categories (done by name; all fit existing categories); hyphenated category URLs and the "show only the most-listed models" limits were the assistant's choices to keep URLs search-friendly and pages short | No minimum-listings threshold for pages yet (see 13.5). |
| 2026-11-23 | Owner's design requests (round 1): product types under every header menu (done), carousel of tall columns with 5 visible and the centre one in focus on the four hub root pages, `/categories/` and the category-level pages (pending decisions), Facebook links in new tabs (done), more than 10 deals and a days filter on the model deals page (pending), combined charts, dots and chart removal on the insights page (partly done) | The owner will keep asking for changes after browsing the site and wants, for any page, the full list of data columns available (assistant provides it, owner selects what to show). |
| 2026-11-23 | Answers to the design questions: carousel shows 5 columns on desktop, 3 on tablets and 1 with peeking neighbours on phones; the model deals page keeps the top 10 and gets an explorer built from all listings below it; price and listings per day are two aligned panels in one card (no dual axis); the daily table follows the period buttons with more columns and pages | Owner chose all recommended options. Assistant's assumptions to confirm: the owner's "total_number" is the rolling total of listings in the last 30 days; the high-scoring-listings-per-day chart is kept; column contents are the current information until the owner picks columns from the lists given in chat. |
| 2026-11-24 | Owner's round-2 requests and the assistant's readings | "30 and 50 and 7 days" (all-listings columns) was read as 7, 15 and 30 days; "count" of the cheapest 25% is about a quarter of the 30-day listings; "5 cheapest price avg for that day" uses the daily 5 cheapest listings (new backend field) and "top 3 deals" on `/[category]/` was kept at 3 while the deals hub shows 4 as requested | To confirm with the owner. |
| 2026-11-24 | Round 3 requests and the assistant's readings | The old "best discounts" home section and the charts were merged into one third section (the owner asked for charts and the deal carousel on page 3, with Browse by category moved to 4); the deals carousel mixes iPhone and MacBook deals one after the other and starts in the middle; the removed 30-day line applies to every deal tile, also on `/[category]/` | To confirm with the owner. |
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
| 2026-10-30 | API endpoint 3: listings | `GET /v1/products/{slug}/listings`: `window` (6 values) / `sort` (price_asc, price_desc, newest) / `page` (1 to 30, fixed size 20) as validated query parameters; fixed sort-name-to-ORDER-BY mapping; a meta query (product exists, total, build times) plus a page query; `PagedEnvelope`; 422 `allowed` is now a real list | Checked with a throwaway fake-repository script (defaults, params, caps, empty and unknown cases); not yet run against Aurora |
| 2026-10-30 | API endpoints 4 and 5: categories | `GET /v1/categories` and `GET /v1/categories/{category_key}/products` in the new `routes/categories.py` (included in `main.py`); `CategorySummary`, `CategoryProductCard`, `CategoryProducts` schemas; `get_categories` and `get_category_products` repository methods | Checked with a throwaway fake-repository script; not yet run against Aurora |
| 2026-10-30 | API endpoint 6: deals | `GET /v1/deals/{category_key}/top` in the new `routes/deals.py`; `DealRow`/`ProductDeals` schemas; `get_top_deals(category_key)` repository method (meta query + one deals query; grouping by product in Python) | Checked with a throwaway fake-repository script; not yet run against Aurora |

| 2026-11-02 | Paused-DB retry (3e) | `repository.py`: `_connect_with_retry()` (3 connection attempts, fixed 4 s pause, failures logged with loguru, `database_resuming` + `Retry-After: 15`), `_query` uses it; `settings.py` `db_connect_timeout` default 30 to 5; `.env.example` updated | Not run; needs a sleeping cluster (3c) |
| 2026-11-02 | Phase 4a: Data API repository, built then **reverted the same day** | A `DataApiRepository` was written and checked with a fake client, then removed after the decision above: `repository.py` is back to one `SqlAlchemyRepository`, plus `NullPool` in the engine and the 3-attempt connection retry; no `data_api_*` settings, no `boto3`; `.env.example` back to `API_DATABASE_URL` and the connect timeout | Not run against Aurora |
| 2026-11-02 | Phase 4b: reader password variable | `infra/terraform/variables.tf`: `api_reader_password` (sensitive, no default); `terraform.tfvars.example` entry. Not yet used by any module (4c wires it into the Lambda). Alembic migration `c4e1a7d92f30` unchanged. | Not run |
| 2026-11-02 | Phase 4c: Lambda, API Gateway, network | `modules/networking`: `aws_security_group.api_lambda` (egress 5432 to the VPC CIDR) + one more inline `ingress` on the Aurora SG for it; new module `modules/api` (zip via `archive_file` of `api/build/lambda`, IAM role, log group, Lambda in the private subnets with `API_DATABASE_URL` built with `urlencode()`, HTTP API + `$default` route + stage throttling + invoke permission); root `main.tf` wiring, `api_reserved_concurrency` variable, outputs `api_url` and `api_lambda_name`; `api/build_lambda.sh` (prebuilt arm64 wheels, no Docker) | Script run on the laptop: builds, 57 MB unzipped / 15 MB zipped, native modules are aarch64. Terraform not run (`terraform` is not installed in the assistant's shell; no `fmt`/`validate` either) |
| 2026-11-03 | Phase 4d: S3 + CloudFront | New `modules/web` (private bucket `<app>-web-<account id>`, public access blocked, placeholder `index.html` with `ignore_changes`) and `modules/cdn` (origin access control, API cache policy, distribution with two origins and the `/api/*` behavior, Price Class 100, HTTPS redirect, bucket policy allowing only this distribution); `modules/api` output `api_domain`; root wiring and outputs `site_url`, `cloudfront_distribution_id`, `web_bucket_name`; `errors.py` header `CACHE_OK` changed; `main.py` `Mangum(..., api_gateway_base_path="/api")`; `api_contract.md` 1.3 updated; `.gitignore` gets `api.zip` | Mangum path stripping checked locally with fake API Gateway events (`/api/health` and `/health` return 200, `/api/v1/nope` returns the 404 error body). Terraform not run (not installed in the assistant's shell) |
| 2026-11-06 | Phase 4e: monitoring, tags, concurrency | `modules/monitoring` rewritten (SNS topic `<app>-alerts` + email subscription, alarms `api-lambda-errors`, `api-lambda-slow`, `api-5xx`, `api-4xx-high`; variables `api_function_name`, `api_id`; output `alerts_topic_arn`); `modules/api` output `api_id`; root `main.tf` calls `module "monitoring"`; `providers.tf` `default_tags` (`App`, `ManagedBy`); redundant `App` tag removed from the DynamoDB table in `modules/scheduler`; `api_reserved_concurrency` default 10 and the stale "quota is 10" descriptions in `variables.tf` and `modules/api/variables.tf` fixed; the owner already set `api_reserved_concurrency = 10` in `terraform.tfvars` | Terraform not run (not installed in the assistant's shell). The 4c/4d apply was done by the owner and the API checked through both the API Gateway and CloudFront URLs (all endpoints answered). A first apply failed once because a changed Aurora security group `description` forces replacement; reverted. |
| 2026-11-09 | Phase 5 prep: listings endpoints | `GET /v1/products/{slug}/listings/all` (route, `get_product_listings_all` repository method and `LISTINGS_ALL_SQL`, reuses `ListingRow`; `Envelope[list[ListingRow]]`, no pagination); `Window` loses `60d`; default window 15d in `routes/products.py`; dbt var `listings_days` 60 to 30; `api_contract.md` 2.5 / 2.5.1 updated | Checked with a throwaway fake-repository script (all-list shape, empty list 200, unknown slug 404, paged default window 15, `window=60d` gives 422 with the new allowed list). **Pending owner-run:** rebuild `mart_product_listings` (`dbt run --select mart_product_listings`), redeploy the Lambda zip (`api/build_lambda.sh` + `terraform apply`), measure the real size of `/listings/all` for the busiest product; not yet run against Aurora. |
| 2026-11-09 | Phase 5, step 1: Astro project | `web/` created with `npm create astro@latest` (minimal template, TypeScript strict, Astro 7.4.8, Node >= 22.23.4 in `engines`); installed Node 26.13.0 by `.pkg` and removed the old nvm Node 14 entry from `~/.zshrc` PATH (backup `~/.zshrc.bak-before-node-fix`). `web/.gitignore` already ignores `node_modules/`, `dist/`, `.astro/`. Template also generated `AGENTS.md`, `README.md`, `.vscode/`. | `npm run build` passes (1 page, `dist/index.html`). Dev server not opened yet. Site plan recorded in 5.5.1. |
| 2026-11-09 | Phase 5, step 2: API client and bare product page | `web/src/lib/api.ts` (TypeScript types mirroring the API schemas for categories, category products and product summary; `get()` helper with a 45 s timeout and 4 attempts with a 10 s pause on 503/network errors, no retry on 404/422; base URL from `API_BASE_URL`, default the live CloudFront `/api/v1`); `web/src/pages/[category]/[slug].astro` (`getStaticPaths` lists every category and product with data, skips products with null stats; unstyled page with title, stats, 5 cheapest with Facebook links; null shown as "Not enough data") | `npm run build` against the live API built 5 pages: `/iphone/iphone-16-pro-max/`, `/iphone/iphone-17-pro-max/`, `/macbook/macbook-air-m2/`, `/macbook/macbook-air-m3/` plus the placeholder home; numbers are in the generated HTML. The first API call took 22 s (Aurora waking), a live proof of the retry/timeout need. Not yet done: dev server look, type-check (`astro check`), `Base.astro` layout, real meta tags, `data_as_of` formatting. |
| 2026-11-09 | Phase 5, step 3: shared layout and formatting | `web/src/layouts/Base.astro` (props `title`, `description`, `noindex`; sets `lang`, viewport, title, meta description, canonical URL, optional `robots noindex, follow`, favicon, Open Graph tags); `web/src/lib/format.ts` (`money()` with thousands separators and "Not enough data" for null, `formatDateTime()` in Toronto time); `astro.config.mjs` now has `site` (CloudFront URL for now) and `trailingSlash: 'always'`; product page and home page use `Base`; product titles/descriptions include the real numbers | Build passes; generated HTML checked for title, description, canonical and Open Graph. **Gap found for Phase 6:** the CloudFront distribution only has `default_root_object = "index.html"`; with a private S3 origin, a request for `/iphone/iphone-16-pro-max/` will not serve `index.html` from the folder. Needs a CloudFront Function (viewer request: append `index.html` to paths ending in `/`) in `modules/cdn` before the real site is uploaded. |
| 2026-11-09 | Phase 5, step 4: design foundation | Tailwind CSS v4 (`astro add tailwind`, `@tailwindcss/vite` plugin in `astro.config.mjs`); Inter self-hosted via `@fontsource-variable/inter` (woff2 files bundled in `dist/_astro`); `src/styles/global.css` (design tokens in `@theme`: font, brand blue, good/bad colours; base link style); `src/lib/site.ts` (`SITE_NAME`, `SITE_TAGLINE`); `Base.astro` now has header, footer with the asking-price/not-affiliated notice, container width, and appends the site name to titles; `src/components/StatCard.astro`; product page restyled (stat cards grid, cheapest-listings card; title shortened to `Name Price in Canada ($X avg) \| Great Deals`, about 60 characters); `moneyShort()` in `format.ts`. Decisions in 5.5.2 | `npm run build` passes (5 pages, CSS and fonts bundled); dev server answers 200 (started with `astro dev --background`, see `web/AGENTS.md`). Owner has not yet looked at the pages in a browser. |
| 2026-11-13 | Phase 5, step 5: category page | New `web/src/pages/[category]/index.astro` (`/iphone/`, `/macbook/`: breadcrumb, h1 `Used {name} Prices in Canada`, two intro paragraphs drafted by the assistant, product cards, 3 top deals per product); new components `Breadcrumb.astro`, `ProductCard.astro` (unlinked "No data yet" card when stats are null), `PriceBadge.astro` (green/red/grey pill, nothing when null), `DealRow.astro`; `api.ts` gained `Deal`, `ProductDeals` types and `getTopDeals()`, and the retry delay was removed earlier the same day; `format.ts` gained `formatPriceDiff()` and `formatDate()` | `npm run build` passes: 7 pages (`/iphone/`, `/macbook/`, four product pages, home). Generated text and CSS checked (title, description, cards, deals, badge classes). The deals list visibly shows US cities (Louisville, Cape Coral, Lafayette, Houston): see Section 13.1. Not yet looked at in a browser; no structured data (BreadcrumbList JSON-LD) yet. |
| 2026-11-18 | Phase 5, step F1: data foundations | `web/src/lib/api.ts`: types and functions `getSeries` and `getListingsAll` (`SeriesPoint`, `ProductSeries`, `ListingRow`); new `web/src/lib/catalog.ts` (`getCatalog()` fetches categories and products once per build and caches the promise; `hasData()`); `site.ts` gets `ADS_ENABLED = false`, `NAV_SECTIONS`; `[category]/[slug].astro` and `[category]/index.astro` now read the catalog instead of calling the API themselves | `npm run build` passes, same 7 pages; live `/series` returns 60 days with exactly the typed fields; `/listings/all` still 404 (13.2, not deployed). A reserved-name clash check was written and then removed the next day at the owner's request (over-engineering). Verified that the catalog loads once per build (temporary log). Note: the Bash tool's shell has Node 14 first on PATH; run builds with `PATH=/usr/local/bin:$PATH`. |
| 2026-11-18 | Phase 5, step F2: header, footer, mobile menu | New `web/src/components/SiteHeader.astro` (sticky top bar; Products two-pane flyout and three category-level menus on `lg`+ using CSS hover/focus-within, Tailwind's `hover:` variants only apply on devices that can hover; slide-in drawer below `lg` with `<details>` accordions and a ~15-line script for open/close/Escape/backdrop; skip link), new `SiteFooter.astro` (Explore / Company / Legal columns, not-affiliated notice, data-updated line), `Base.astro` uses both and `<main id="main">`, `site.ts` gets `NAV_LINKS` (How it works). The header tagline moved to the footer. | `npm run build` passes; screenshots with headless Chrome of the hover flyout (both categories), hub menu, mobile drawer open/closed and the footer looked right; drawer opens and closes with Escape. Links to hubs (F7), the trust pages (F9) and `/categories/` (F6) show the 404 page until those steps. Fixed two text bugs found in the footer (missing space, double period). |
| 2026-11-18 | Phase 5, step F3: shared components | New in `web/src/components/`: `SectionHeading`, `LastUpdated` (`<time datetime>`), `Disclosure` (prices / affiliate), `AdSlot` (renders nothing unless `ADS_ENABLED` or `preview`; fixed min-height per size), `ProductTabs` (underline tabs, `aria-current`, scrolls sideways on phones); `Breadcrumb` now also writes BreadcrumbList JSON-LD; new `lib/text.ts` (neutral generated sentences, null-safe: listings, average, 7d vs 30d trend, cutoff, `productSummary`); `PRODUCT_TABS` and `ProductTabKey` in `site.ts`; product page now has breadcrumb, tabs, summary paragraph, last-updated and disclosure; new `/styleguide/` page (`noindex`, must be excluded from the sitemap in F10 and removed or hidden before launch); `PriceBadge` no longer wraps | `npm run build` passes (8 pages); JSON-LD checked in the built HTML; no ad slot on real pages; screenshots of the product page and the style guide looked right. The three non-overview tabs show the 404 page until F5. |
| 2026-11-19 | Phase 5, step F4: chart toolkit | `web/package.json`: `@astrojs/react`, `react`, `react-dom`, `recharts`, dev `@types/react`, `@types/react-dom`, `typescript`; `astro.config.mjs` adds `react()`, `tsconfig.json` sets `jsx: react-jsx`. New `web/src/components/charts/`: `theme.ts` (the first three slots of the dataviz palette `#2a78d6`, `#eb6834`, `#1baf7a`, validated: all checks pass, aqua under 3:1 so legend + table are required), `parts.tsx` (`ChartCard` with title, legend for 2+ series and a collapsible data table that is in the HTML; `TooltipBox`; the chart waits for the browser before drawing), `LinePanel`, `ColumnPanel`, `DealsPanel` (dots are real links to Facebook, 24px hit area), `ProductCharts` (all seven panels with the 10/20/30/60 day filter, default 30), `OverviewChart` (fixed 15 days: daily and 7-day average). New `Sparkline.astro` (build-time SVG). `lib/format.ts` gets `formatShortDate`, `compactNumber`; `api.ts` series data is fetched at build and passed to the islands as props (`client:visible`). Product overview now has a "Price trend" section; the style guide shows all charts. | `npx tsc --noEmit` clean; `npm run build` passes; headless Chrome screenshots of the overview chart (with hover tooltip) and all insight charts looked right; period buttons work. Two-measure charts are split into two panels (no dual axis). Y-axis labels showed `$1.1K` repeated for narrow ranges, fixed to full numbers. `astro check` is still not set up (F10). |
| 2026-11-19 | Phase 5, step F5a: product overview page | `web/src/pages/[category]/[slug].astro` moved to `[category]/[slug]/index.astro` (same URL; the folder will hold `market-insights/`, `top-deals/`, `listings/`). Page now has: H1 "Used {name} Price in Canada", breadcrumb, tabs, generated summary, 6 stat cards in two rows (30d and 7d average, cheapest 25% under, listings 30d and 7d, high-scoring listings with their 30d average), "Price trend" with the 15-day chart and a link to the insights page, "Best deals right now" (5 `DealRow`s from `/deals/{category}/top`, plus links to top deals and all listings), "Other {category} models" (`ProductCard`s), disclosure. `catalog.ts` gets `getCategoryDeals()` (one deals request per category and build, shared by the category page and every product page); `format.ts` gets `count()`. | `npx tsc --noEmit` clean; `npm run build` passes (8 pages); screenshots of the whole page looked right. Links to the insights, top-deals and listings pages show the 404 page until F5b-d. The deals list still shows US cities (for example Lafayette), see 13.1. |
| 2026-11-19 | Phase 5, step F5b: market insights page | New `web/src/pages/[category]/[slug]/market-insights/index.astro` (`/{category}/{slug}/market-insights/`): breadcrumb with the product link, H1 "Used {name} Price History in Canada", title "{name} Price History in Canada", description = name plus first takeaway (about 150 characters), tabs with Market insights current, own intro, "Key takeaways" (4 generated points), `ProductCharts` with the period filter, "Daily numbers" table (last 14 days), links back to the overview and to top deals, disclosure. New `DailyTable.astro`; `text.ts` gets `insightPoints()` (change of the 7-day average, of the cheapest-25% cutoff and of the deal-8 average over the last 30 days, busiest and quietest full day); `catalog.ts` gets `getProductPaths()` shared by the product pages. | `npx tsc --noEmit` clean; `npm run build` passes (12 pages); the generated text differs per product and no point is shown when its numbers are missing; screenshots looked right. The link to top deals shows the 404 page until F5c. |
| 2026-11-19 | Phase 5, steps F5c and F5d: top deals and all listings | **F5c** `[slug]/top-deals/index.astro`: H1 "Used {name} Deals in Canada", title "{name} Deals in Canada", description = name plus the best-deal sentence, generated intro (`dealsSentences()` in `text.ts`: best deal and its gap to the 30d average, price range, "all below the cheapest-25% price" only when true), numbered `DealRow` list (`DealRow` got a `showRank` prop), "How deals are chosen" section, links back and to listings, empty-state text. **F5d** `[slug]/listings/index.astro` (`noindex, follow`) with three stat cards and the new React island `components/listings/ListingsTable.tsx`: loads `/listings/all` in the browser, period buttons 1/3/7/15/30 days (default 15, `days_ago < N`), sort (newest, lowest price, highest price, biggest saving), 25 rows per page with page buttons, full columns (listing, price, vs 30-day average badge, condition, storage, city, listed date and age, link), loading text that mentions the 30-second wake-up, error state with retry. `api.ts`: in the browser the API base is `/api/v1` (same address as the site behind CloudFront), in `npm run dev` it is `/_api/v1`, which `astro.config.mjs` forwards to the live API (`API_PROXY_TARGET=http://localhost:8000` for a local API). `astro.config.mjs` also pre-bundles `react-dom/client` for dev (without it every React island failed to hydrate in `npm run dev`; the production build was fine). Dev dependency `@types/node`. | `npx tsc --noEmit` clean; `npm run build` passes (16 pages). Top deals page checked in a browser. **The listings table was tested only against a throwaway mock API with made-up rows**, because `/listings/all` is not deployed (13.2) and the local API's `.env` still has the placeholder database host: loading state, sort, period, pagination, 1-day view and the error state (mock stopped) all behaved correctly. Real data still to check after deployment. The top deals list shows US cities at ranks 2 to 4 (13.1). |
| 2026-11-19 | Disclosure cleanup | The page-body `Disclosure` box was removed from the four product pages (overview, market insights, top deals, listings) because the footer already carries the same notice on every page; the footer notice now ends with the link "How we calculate the numbers" (to `/how-it-works/`, built in F9). The `Disclosure` component stays for the affiliate variant (next to affiliate links) and the style guide. | Build passes. |
| 2026-11-19 | Phase 5, step F6: category page upgrade and /categories/ | `ProductCard.astro` now has an optional preview (`last7` = last 7 full days of the series, `deals`): two `Sparkline`s (average price per day, listings per day) and the best 3 deals (`DealRow compact`). On mouse devices it is a panel under the card that opens on hover or focus (`group-hover`, `group-focus-within`, no layout shift); on touch screens (`@media (hover: hover)` false) it is shown inline under the stats. `[category]/index.astro` passes the previews and no longer has the "Best current deals" section. New `CategoryCard.astro` and `pages/categories/index.astro` (`/categories/`, breadcrumb, intro text, grid of large gradient cards with model count and 30-day average range; on hover the models list covers the card, on touch it is inline; photos replace the gradients in F12). `catalog.ts` gets `getProductSeries()` (one series request per product and build, shared by the overview, insights and category pages). `DealRow` has a `compact` option. | `npx tsc --noEmit` clean; `npm run build` passes (17 pages); screenshots with headless Chrome of the hover panel on a category card, the categories hover overlay, and both pages in touch mode (Chrome started with `--blink-settings` hover none; the DevTools `setEmulatedMedia` does not change hover) looked right. The deal previews show US cities (13.1). |
| 2026-11-19 | Phase 5, step F7: hub pages | Six pages from shared parts: `/market-insights/`, `/top-deals/`, `/all-listings/` (root: category cards, via `CategoryCard` with new `href`, `modelPath`, `blurb` options) and `/{hub}/{category}/` (a `HubCard` per model leading to the model's page of that section). Route files are 10 lines each (`pages/{hub}/index.astro`, `pages/{hub}/[category]/index.astro`) and use `components/hubs/HubRoot.astro` and `HubCategory.astro`; a dynamic `[hub]` route was not possible because it would clash with `[category]`. `HubCard` variants: insights (30-day change of the 7-day average as a coloured badge, a 30-day sparkline, 30-day average, listings; extra panel with the two 7-day sparklines), top deals (best deal price, badge, title, count; extra panel with the top 3 deals), all listings (listings in 30 days, 30-day average). The panel logic moved out of `ProductCard` into `CardPreview.astro` (charts and/or deals; hover on mouse devices, inline on touch). `site.ts` gets `HUBS`; `text.ts` gets `trend30`, `formatPct`, `insightsCategorySentences`, `insightsRootSentences`, `dealsHubSentences` (generated text; `plural` exported). All-listings pages are `noindex, follow`; the other four are indexed. | `npx tsc --noEmit` clean; `npm run build` passes (23 pages); titles, noindex flags and generated text checked in the built HTML; hover panels and cards checked with screenshots. Found and fixed a double period after "p.m." in the intros. The top-deals text shows a $500 iPhone 17 deal ($1,004 below average), see 13.1. |
| 2026-11-19 | Phase 5, step F8: home page | New `pages/index.astro` with five full-screen sections (`min-h-[calc(100svh-4rem)]`, `snap-start`): hero (small site name, H1 "Know what a used iPhone or MacBook is really worth in Canada" built from the category names, sentence, two buttons, trust strip: listings in 30 days, models, categories, prices updated), "How Great Deals helps you buy smarter" (3 steps, link to /how-it-works/), "Browse by category" (a card per category with its models), "Today's biggest discounts" (each model's best deal ranked by percent below its own 30-day average, top 3 as new `DealCard`s, plus the `OverviewChart` of the most-listed model with an optional `title`, links to top deals and that model's price history), FAQ (5 questions, visible) and a "Deal alerts by email are coming soon" note. Scroll-snap: `proximity` by default, `mandatory` only on screens at least 1024 px wide and 900 px tall; subtle fade-in (`data-reveal`, a 10-line IntersectionObserver script, off without JavaScript and with reduced motion). `Base.astro` got a `fullWidth` option. `catalog.ts` got `getProductSummary()` (memo, now used by the product pages) and `getPricesUpdatedAt()`; the footer now says "Prices updated" with the oldest product update time (13.5 note fixed). | `npx tsc --noEmit` clean; `npm run build` passes (30 pages); screenshots of all five sections at 1280x1000 looked right. The discount cards show a $500 iPhone 17 from Houston and a $300 MacBook (13.1 and odd prices): fix 13.1 before launch. Mobile sections were rendered but only briefly checked. |
| 2026-11-20 | Phase 5, step F9: trust pages | New `layouts/TextPage.astro` (breadcrumb, H1, intro, optional "Last updated", plain styling for headings, lists and definition lists) and pages `about`, `how-it-works` (where the data comes from, which listings count, the numbers explained, how deals are ranked, limits), `contact`, `privacy` (today's reality: no accounts, cookies, analytics or ads; AWS logs; will be updated if that changes), `terms`, `disclosure` and `404` (noindex, links to home, categories, top deals and every model). `CONTACT_EMAIL` placeholder in `site.ts`. | `npx tsc --noEmit` and `astro check` clean; build passes; screenshots of How it works and the 404 page looked right. Wording is a draft for the owner to review (13.5). |
| 2026-11-20 | Phase 5, step F10: SEO plumbing | `@astrojs/sitemap` with a filter (sitemap leaves out all-listings, listings, styleguide and 404 pages; 28 of 36 pages are listed); `src/pages/robots.txt.ts` (allow all, sitemap address from `site`; noindex pages are not blocked here so Google can see their tag); `Base.astro` adds `og:locale`, `og:image` (+ size) and `twitter:card` with `public/og-default.png`; home page has WebSite and Organization JSON-LD (BreadcrumbList already on every page with a breadcrumb); `/styleguide/` is now a dynamic route that lists no pages in a production build (dev only); `@astrojs/check` added (`npm run check`; TypeScript pinned to 6.x because `@astrojs/check` does not accept 7); new `scripts/check-site.mjs` (`npm run check:site`, run after the build): broken internal links, sitemap entries that do not exist, noindex pages in the sitemap, indexable pages missing from it, and per page title, description, canonical and exactly one H1, with warnings for long titles and descriptions. | `astro check`: 0 errors, 0 warnings, 0 hints (60 files); `npm run build` passes (36 pages); `check:site` passes; deliberately broken link was caught. The checker found four hub descriptions that were too long (shortened). |
| 2026-11-20 | Phase 5, step F11: search | `pagefind` added (dev dependency); `npm run build` is now `astro build && pagefind --site dist` and writes the index to `dist/pagefind/` (8 pages indexed: the 4 model overview pages, the 2 category pages, About and How it works). Only marked content is indexed (`data-pagefind-body` on the model summary text, the category intro and, through the new `searchable` option of `TextPage`, the two info pages; the H1 is the result title via `data-pagefind-meta="title"`), so Facebook listing titles and other pages never appear in results. `SiteHeader.astro`: a magnifier button (always visible, desktop and phone) and a native `<dialog>` search panel; opens from the button or the `/` key, closes with Escape, the X or a click outside; Pagefind's own script and stylesheet are loaded the first time it opens; the panel is themed with Pagefind CSS variables in `global.css`; in `npm run dev` (no index) it shows a note to build first. | `astro check` 0 errors; build passes; `check:site` passes; headless Chrome test: `/` opens the panel, "macbook" finds the two MacBook model pages and the category page, "how" finds How it works and About, Escape closes it. Found a stray word (`developin`) at the end of `web/tsconfig.json` in the working copy, which broke the build; removed it (the committed version was fine). |
| 2026-11-20 | Catalog expansion to 69 products in 8 categories | `transform/seeds/product_catalog.csv` rewritten (iphone 17, macbook 9, ipad 10, apple_watch 12, airpods 7, gaming_console 11, samsung_galaxy 2, smart_rings 1; slugs generated from the names, the four old slugs unchanged; category chosen from the product name and the category configs); `transform/seeds/schema.yml` gets a `relationships` test from `category_key` to `dim_categories`. Frontend changes so everything scales: category URLs use hyphens (`/apple-watch/`, `/gaming-console/`, `/smart-rings/`) because the API keys have underscores (`toUrlKey` and `toApiKey` in `catalog.ts`; only API calls use the underscore form); `CATEGORY_NAME_OVERRIDES` (smart_rings shown as "Smart Ring"); `byPopularity` helper; the mega menu is wider (40 rem, models in two columns); `CategoryCard` and the home page list the 6 and 4 most-listed models and link to "All N models"; category grids use 3 columns on large screens; related products on a model page are the 4 most-listed others plus a link to all; the 404 page lists categories instead of models; the home hero, title and texts say "tech" instead of listing the category names when there are more than 3; "not affiliated" statements use `BRAND_OWNERS` (Facebook, Meta, Apple, Samsung, Sony, Microsoft, Nintendo, Oura) in the footer, home FAQ, About, Disclosure and Terms; `fitTitle()` shortens model titles that would exceed about 56 characters; share image regenerated ("Used tech prices in Canada"). | `astro check` clean. **Tested against a throwaway mock API with made-up data for all 69 products (about 1 in 7 without data):** the build made 280 pages in about 4 s, `check:site` passed (211 pages in the sitemap, no long titles), 69 pages indexed for search, screenshots of the mega menu, categories page, home categories section looked right. Not tested with real data because the serving tables still hold the 4 old products until the owner-run steps in 13.5. |
| 2026-11-23 | Build fix for the larger catalog | A build against the real API failed with "API unreachable after 4 attempts" for `products/airpods-3rd-generation`: the footer's `getPricesUpdatedAt()` and the pages ask for dozens of products at once, and API Gateway's throttle (about 2 requests/s) answered 429/503. `lib/api.ts` now limits requests to 3 in flight with 600 ms between starts, waits and retries on 429 (honouring `Retry-After`), keeps retrying 503 without a pause and allows 6 attempts. | Real data now shows all 69 products with data: `npm run build` made 320 pages in 1 min 41 s (two 429 answers were retried automatically), 79 pages indexed for search, `check:site` passed (241 pages in the sitemap), `astro check` 0 errors. |
| 2026-11-23 | Design round 1 after the owner's browsing (applied part) | (1) All four header menus (Products, Market Insights, Top Deals, All Listings) are now two-level: category, then its models, each model leading to its own page of that section; the Top Deals and All Listings panels open towards the left so they stay on screen; the mobile drawer has the same nesting (`SiteHeader.astro`, `sections` list). Cost: the header makes every page about 250 KB uncompressed (about 20 KB gzipped, 744 links), see the note in 13.5. (2) Every Facebook link opens in a new tab (`target="_blank" rel="nofollow noopener noreferrer"` in `DealRow`, `DealCard`; the listings table and chart dots already did). (3) Market insights page: the "Average price of high-scoring listings" chart is removed; the "Cheapest listings by day" dots are interactive (hover or keyboard focus shows day, price and the gap to that day's 30-day average; a click or tap pins the card, which has "Open on Facebook" in a new tab; Escape or a click elsewhere closes it): hovering and clicking use the dots' positions (nearest dot within 20 px) instead of the small shapes, and a mouse press no longer moves focus, because the redraw that followed replaced the dot before the click was sent. | `astro check` clean; build passes (320 pages); headless Chrome: hover card, real click pins and shows the new-tab link, the All Listings menu fits the screen. **Still open from the same message** (waiting for the owner's answers): carousel layout for the hub and category pages, more than 10 deals and a days filter on the deals page, combined charts and the daily table on the insights page, per-page lists of available data columns (given in chat), and the listings page error. |
| 2026-11-23 | Design round 1 (second part: carousel, combined charts, explorer) | **Carousel** (`components/Carousel.astro`): a full-width row of tall columns made with scroll-snap (about 5 visible on large screens, 3 on tablets, 1 with neighbours peeking on phones), the middle column sharp and the others faded (opacity 1 down to 0.35, slight scale, set by a small script on scroll), arrow buttons, swipe and the left and right keys, the third column in the middle at the start (the first on phones), all links in the page HTML, still scrollable without JavaScript. Used on `/categories/` and the three section roots (a `CategoryCard` column per category: counts, price range, text, the 8 most-listed models) and on `/[category]/` and the three section category pages (a `ProductCard` or `HubCard` column per model, sorted by listings; the former hover panel is now the always-visible lower part of the column via `CardPreview inline`). The home page keeps its grid. **Insights page:** "Average asking price and listings per day" is one card with two aligned panels (price line on top, listing columns below) sharing the date axis and one tooltip (`StackedPanel.tsx`, Recharts `syncId`); "30-day average, cheapest 25% and listings" is a second such card with the two 30-day lines and a rolling 30-day listing total (the total needs 30 days of history, so it starts on day 30 of the 60); the 3/7/30-day and the separate cheapest-25% charts are gone; the high-scoring-per-day chart stays; the "Daily numbers" table is now `DailyTable.tsx` inside the island: follows the period buttons, 15 rows per page, columns day, daily, 7-day and 30-day average, cheapest 25%, lowest listing that day, listings, high-scoring listings. **Deals page:** below the baked-in top 10 an "Explore more deals" section (the listings table with default sort lowest price, 30 days, 10 rows, plus a new "Rows per page" 10/25/50/100 control, also on the listings page). **`api.ts`:** requests start without a gap until the first 429, then 600 ms apart (cached builds now take about 6 seconds instead of 100). | `astro check` 0 errors, `tsc` clean, build passes (320 pages), `check:site` passed; headless Chrome: carousel screenshots (categories, a model page, the top-deals hub), arrow buttons and fading, combined cards with shared hover, daily table paging (2 pages at 30 days, 4 at 60), explorer against a throwaway mock listings API (10, 50 rows, 3-day filter). The explorer and the listings page show an error against the real API until `/listings/all` is deployed (13.2). |
| 2026-11-24 | Design round 2 after the owner's browsing | **Backend:** `top_deals_per_product` 10 to 25 (`dbt_project.yml`, contract 2.6); `mart_product_daily` gets `lowest_5_avg_1d` (average price of the up to 5 cheapest listings posted that day, from `lowest_5_deals_1d`), added to the API query, `SeriesPoint` and contract 2.4 (optional in the frontend type until deployed). **Section roots** (`/categories/`, `/market-insights/`, `/top-deals/`, `/all-listings/`): `CategoryCard` has a `variant`; each column shows the category text, then the number of models and the listings of the last 7 and 30 days (no averages), then its 8 most-listed models with per-page numbers (categories and insights: 30-day average, listings, cheapest 25%; top deals: number of deals, average of the top deals, 30-day average, listings; all listings: 30-day average, listings). **Category-level pages:** new `ModelColumn.astro` replaces `HubCard` and the old preview panel: bigger model name; insights columns have the 30-day trend with sparkline, four numbers and three 7-day charts (price, listings, cheapest 25%) with soft fills; top-deals columns merge the two deal sections into 4 separate `DealTile`s (title, price with comparison, listed date and place, "See it on Facebook Marketplace" in a new tab) and a link to all deals; all-listings columns explain the period, sort and rows-per-page options and show listings, average and cheapest 25% for 7, 15 and 30 days (the 15-day average and count come from the daily numbers; the API has no 15-day cheapest-25% price, shown as a dash); `/[category]/` columns combine the insights content with the 3 best deals. **Model deals page:** `PagedList.astro` (items all in the HTML, 5 per page with page buttons) shows up to 25 deals as separate tiles. **Model overview:** four `StatPanel`s (30-day average and listings; 7-day average, listings and change against 30 days; cheapest 25% price with about a quarter of the listings below it and the 7-day price; average of the 5 cheapest listings for 30 and 7 days), the high-scoring card is gone, and the chart is the insights chart for 15 days with the average of the day's 5 cheapest listings as a second line. **Listings page:** the same panels (first three), and a clearer message when the API does not have the listings endpoint yet. **Insights page:** the high-scoring chart and takeaway are gone; chart cards have a gradient frame, key-number tiles, a soft fill under the main line, rounder columns; the dots chart has a 30-day average reference line, bigger dots with a halo, and key numbers. Removed unused `HubCard`, `CardPreview`, `ColumnPanel`. | `astro check` 0 errors, build passes (320 pages), `check:site` passed, screenshots of all carousel pages and the four model pages; against a throwaway mock API with 25 deals and `lowest_5_avg_1d`: 25 deals in 5 pages of 5, the second line and shared hover on the overview chart. The explorer and listings page still need the API redeploy (13.2). |
| 2026-11-24 | Design round 3 (visual pass, ordering, home page) | **Section roots and category columns** (`CategoryCard`): three clear total rows with icons (models, listings 7 days, listings 30 days) in a glass panel, and each model as a white card with label and value rows, a thin bar for listings relative to the busiest model, and on the deals page a "top deals average" with a green pill ("51% below the 30-day average"); the deals count is removed from each model; new variant `home` (30-day average and listings only). **Ordering:** `aroundCenter()` in `catalog.ts` puts the item with the most listings in the middle and the others around it in order ([e, c, a, b, d] for a > b > c > d > e); used on `/categories/`, the three section roots (categories sorted by listings with `sortCategoriesByListings`), `/[category]/` and the three section category pages (models by listings); `Carousel` starts on the column marked `data-carousel-start`; category colours follow the catalog order so they stay the same on every page. **`ModelColumn`:** the 30-day average line is removed from `DealTile` (everywhere), all-listings columns show three period cards with a pill, a big listings number, a bar and two tiles (average, cheapest 25%). **Model overview** (`/iphone/iphone-15-pro/`): a gradient header with the title, update time, summary text and a 30-day average panel with trend and sparkline; the four stat panels have sparklines (`StatPanel` `spark`, `Sparkline` `ring`); deals in a rounded card with ranks; "Other models" are new `ModelSummaryCard`s (average with trend badge, chart, three numbers) in four columns. **Home page:** 1 hero with a live example card of the most-listed model and glass number tiles; 2 "How it works" with three step cards (icons, numbers, longer text) and four feature tiles; 3 "The market at a glance": the two most-listed models' price and listings charts, and below them a carousel of the best iPhone and MacBook deals (5 per category mixed, middle of the carousel); 4 "Browse by category" as a carousel of category columns with each model's name, 30-day average and 30-day listings; 5 FAQ. Chart key-number tiles show prices without "CAD" so they do not wrap. Removed `DealCard`. | `astro check` 0 errors, build passes (320 pages), `check:site` passed; screenshots of the home sections (desktop and phone), the four section roots, the category-level pages and the overview. The deal carousel on the home page shows very cheap old MacBook listings because they are far below their model's average: a data-quality point for the pipeline (13.1). |
| 2026-11-24 | Design round 4 | `CategoryCard` lists at most 6 models (5 on the home page) and links to the rest ("All N models") on `/categories/` and the three section roots; `ModelColumn` has colour themes: top-deals columns are emerald/teal (gradient header with white title, tinted body and footer), all-listings columns are indigo/blue (period pills and bars in indigo); the category and market-insights columns stay light. | `astro check` 0 errors, build passes (320 pages), `check:site` passed; screenshots of both coloured pages and the home categories. |
| 2026-11-24 | Text pass | New wording on every page: the section roots, category pages, `/categories/`, the four product pages and the home page. The sentences that named one model (biggest gap, moved the most) were replaced by counts (models that fell, rose or held steady; typical gap of the cheapest listing below its average; models with a listing 25%+ under). Every section now points to the cheapest listings as the yardstick for a good price. The home title says "and find the cheapest deals", the hero card is no longer tilted, the two home charts are two random models (different after every build), the deals text is generic and "several times a day" was removed. Tip: the shell's default Node is 14, use `/usr/local/bin` (Node 26) for npm commands. | `astro check` 0 errors, build passes, `check:site` passed; rendered text of the key pages checked in `dist`. |
| 2026-11-02 | API local env file | `api/.env.example` (`API_DATABASE_URL` for the read-only role, optional `API_DB_CONNECT_TIMEOUT`); owner copies to `api/.env` | n/a |

Owner-run and pending (the owner does these later, not the assistant): roll out the timezone change (11.5, no code change needed; `PGOPTIONS` is already set in `stage3_transform.py`), build the serving tables, apply the Alembic migration and set the reader password, then run the six endpoints with `uvicorn` against Aurora (3c).
Owner to-do before 4c/4d can be applied: (1) 4b items (Alembic migration, `ALTER ROLE web_serving_tables_reader PASSWORD '...'`, `api_reader_password` in `terraform.tfvars`); (2) run `api/build_lambda.sh` (also after this Mangum/header change); (3) `terraform init` (new modules), `terraform plan`, review, `terraform apply`; (4) open `<site_url>/` (placeholder page) and `<site_url>/api/health` and `<site_url>/api/v1/categories`; (5) optionally request a Lambda concurrency quota increase. To verify after the first deploy: that CloudFront does not cache a 5xx from the API (errors carry `no-store`), and the `stale-if-error` behavior. Next design step: Phase 4e (monitoring and the budget alarm), then Phase 5 (frontend) or Phase 6 (deploy automation).
Owner to-do for 4e: `terraform plan` (expect many in-place tag updates from `default_tags`, new monitoring resources, the Lambda reserved concurrency; **no** `-/+` replacement of any resource, check especially the Aurora cluster and security groups), `terraform apply`, click the SNS confirmation email, then in the console: Billing, Cost allocation tags, activate `App`; check that the four alarms show data (the `Stage = $default` dimension is unverified). Next design step: Phase 5 (frontend) or Phase 6 (deploy automation).

### 11.5 Timezone of dbt day buckets  **[DECIDED 2026-10-28: option B, code done, rollout pending]**
The API shows timestamps in Toronto time. dbt had no timezone: `transform/profiles.yml` cannot set one, so `current_date`, `listed_at::date` and therefore `stat_date`, `listed_date`, `days_ago` and the rolling windows used the database session default (probably UTC; check with `show timezone;`). A listing posted at 9 pm Toronto time on Oct 22 landed in Oct 23's bucket.
- **Decision:** dbt sessions use Toronto time. Implemented by setting `PGOPTIONS="-c timezone=America/Toronto"` in the environment `stage3_transform.py` passes to dbt (one entry; no SQL changes, since no model uses a hardcoded timezone). Running dbt by hand requires exporting the same variable, otherwise results differ from the pipeline.
- **Rollout still to do** (not yet run): (1) compare in a scratch schema; (2) `dbt run --full-refresh --select fct_products_daily` so history uses one rule (it is incremental and only rebuilds recent days); (3) rebuild the serving tables and re-run the serving tests. `fct_deal_candidates` is never full-refreshed (`full_refresh=false`), so existing rows keep their old day logic and only new rows follow the new one; this mostly affects recent alerts around the day boundary.

---

## 13. Known issues and deferred fixes (the list to come back to)

When the owner asks "what issues are left", start here. Newest first. Mark an item **FIXED** (with the date and where it is recorded in Section 12) instead of deleting it.

### 13.1 Non-Canadian listings in website statistics and deals  **[OPEN, found 2026-11-13, owner chose to deal with it later]**

**What was seen.** `GET /v1/deals/iphone/top` returned top deals for iPhone 16 Pro Max in **Louisville, Cape Coral and Lafayette** (US cities) at the cheapest ranks (for example $465 to $500 against a 30-day average of about $1,121). A sample of the 100 newest iPhone 16 Pro Max listings (`/listings?window=30d&sort=newest`, pages 1 to 5) was almost entirely Canadian (Toronto 28, Brampton 8, Mississauga 8, Hamilton 6, Barrie 5, Ottawa 4, and so on). So US listings look rare overall but concentrate in the cheapest lists, which is where top deals, the 25th-percentile cutoff and the "cheapest 5" lists look. The prices may be in USD, but the site labels everything CAD and "in Canada".

**Why it happens (checked in the code).** `dim_toronto_area_cities` (cities under 90 km from downtown Toronto) is used **only** by `fct_deal_candidates` (`within_90km_toronto`, the email alerts). `benchmark_listings` and all `serving.*` models have **no location filter**, so averages, cutoffs, charts, listings and top deals use every city that Apify returned. `configs/iphone.yaml` searches Toronto and Vancouver, so a Toronto-only list would also exclude legitimate Vancouver listings.

**Not measured yet.** How many listings are outside Canada, and how much they move the averages and cutoffs. Suggested read-only checks on Aurora:
```sql
-- cities by listing count for one product (look for non-Canadian cities)
select location_city, count(*) from transformed.benchmark_listings
where product_model = 'iPhone 16 Pro Max' group by 1 order by 2 desc;

-- effect on the 30-day average: all listings vs. a candidate "Canada only" list
-- (needs a decided definition of "Canadian"; the data has city names only, no country/province column unless the raw payload has one: check raw_payload keys first)
```

**Options (undecided).**
1. Filter in dbt, inside `benchmark_listings`, so the statistics, charts, listings and deals all follow it (consistent, one place; requires deciding how to define "Canadian": a city allowlist table/seed, a province/country field if the raw payload has one, or the Toronto and Vancouver areas only). Rollout: rebuild `benchmark_listings`, **full refresh** of `fct_products_daily`, rebuild serving, re-run serving tests. Check effect on `fct_deal_candidates` (it joins `benchmark_listings`, new `excluded_from_benchmark` skip reason).
2. Filter only in the API or the website (cheaper, but averages and cutoffs stay mixed, so numbers and lists can disagree).
3. Keep the data as is and change the wording ("North America", currency note). Probably wrong for a Canada-focused SEO site.
4. Fix at the source: restrict the Apify searches (location/radius) so non-Canadian listings are not scraped at all (also reduces cost).

**Why it matters.** Top deals are the most eye-catching part of the site; a US listing presented as a Canadian deal is misleading and hurts trust. Resolve before the site goes public (Phase 7 launch checklist).

### 13.2 `/listings/all` is not deployed  **[OPEN, confirmed 2026-11-23: the live API answers `route_not_found`; the listings pages show "could not be loaded" until the Lambda is redeployed]**
Code and contract are done (2026-11-09) but the live Lambda still has the old code (`GET /v1/products/{slug}/listings/all` answers `route_not_found`). Owner-run: rebuild `mart_product_listings` (`listings_days` is now 30), run `api/build_lambda.sh`, `terraform apply`, then measure the real response size.

### 13.3 CloudFront does not serve `index.html` inside folders  **[OPEN, needed before the first real upload]**
`modules/cdn` only sets `default_root_object = "index.html"`. A private S3 origin will not serve `/iphone/iphone-16-pro-max/` as `.../index.html`. Needs a CloudFront Function (viewer request: append `index.html` to paths ending in `/`) and a decision on the 404 page (`custom_error_response`).

### 13.4 Owner-run rollouts still pending (see Section 12)
Timezone rollout (11.5: scratch comparison, `fct_products_daily` full refresh, serving rebuild), `benchmark_listings` zero-diff comparison, Alembic migration and reader password, 4e `terraform apply` and SNS confirmation, running the endpoints against Aurora, CloudFront 5xx/`stale-if-error` checks, `Stage = $default` alarm dimension check.

### 13.5 Smaller notes
- **Rollout of the 2026-11-24 changes, owner-run, in this order:** (1) `dbt run --select path:models/serving` from `transform/` (`top_deals_per_product` is now 25 so `mart_top_deals` keeps up to 25 deals per model, and `mart_product_daily` has the new column `lowest_5_avg_1d`); (2) redeploy the API Lambda (`api/build_lambda.sh`, then `terraform plan` and `terraform apply` in `infra/terraform`): this also deploys `/listings/all` (13.2) and the new `lowest_5_avg_1d` field of the series (the new API code selects that column, so do step 1 first); (3) invalidate `/api/*` in CloudFront or wait up to 6 hours for the cached answers to expire; (4) rebuild the site (`npm run build`). Until then the site still works: the deals pages show the 10 deals the API has, and the overview chart simply has no "average of the 5 cheapest" line. The category deals answer grows to about 25 deals x the number of models (about 425 for iPhone, roughly 150 to 200 KB): fine for builds, watch it if a category gets much bigger.
- **API throttle and big builds (2026-11-23):** API Gateway allows about 2 requests a second (burst 5, Phase 4c decision, variables `throttle_rate_limit` and `throttle_burst_limit` in `modules/api`), so a site build with 69 products (about 135 distinct API calls) first failed with "API unreachable after 4 attempts" (answers 429 and 503). `web/src/lib/api.ts` now sends requests politely (at most 3 at a time, 600 ms between starts, a pause and retry on 429, up to 6 attempts), so a cold build takes about 1 min 40 s (320 pages); builds that find answers in CloudFront's cache (6 h) are faster. If builds become too slow when more products are added, raise the throttle in Terraform (for example 10 per second, burst 20) together with the reserved Lambda concurrency, and apply it (owner-run).
- **Catalog expansion rollout (2026-11-20), owner-run:** `transform/seeds/product_catalog.csv` now lists 69 products in 8 categories, but the website only shows them after the serving tables are rebuilt. From `transform/`: `dbt seed --select product_catalog`, then `dbt run --select path:models/serving`, then `dbt test --select product_catalog dim_products` (or just let the pipeline run: `stage3_transform.py` runs `dbt seed` before `dbt run`). The API needs no redeploy; CloudFront may serve the old category lists for up to 6 hours (invalidate `/api/*` to see the change at once), then rebuild the site (`npm run build`). The product names in the seed must equal the classifier's `product_model` text exactly (spelling, brackets); a misspelt one just shows as "No data yet".
- **Catalog expansion, things to know:** (1) the seed now also contains the generic buckets "MacBook Air" and "MacBook Pro" (catch-alls for listings where the chip or size was not recognised), which reverses the 2026-10-19 decision to exclude the generic MacBook Air bucket; (2) products with very few listings still get pages (a page needs at least one listing in 30 days; deals and the cheapest-25% price need at least 10), consider a minimum if thin pages appear; (3) `windows_laptop` has a config but no product in the seed, so it is not on the site; (4) the home, hub and category pages show only the 4 to 6 most-listed models per category and link to the rest.
- **Before launch (F9 and F10, 2026-11-20):** (1) replace `CONTACT_EMAIL` in `web/src/lib/site.ts` (placeholder `contact@your-domain.example`, used on the Contact, About, Privacy and Terms pages); (2) have the Privacy, Terms and Disclosure drafts reviewed (plain-language drafts, not legal advice; Terms mention no governing law yet; Privacy says there are no cookies, analytics or ads and must be updated when that changes); (3) the How it works page says listings are collected "several times a day" and describes the deal score as an AI-assisted score: check both are accurate; (4) when the custom domain exists, change `site` in `astro.config.mjs` (canonicals, sitemap, robots.txt and the share image follow it); (5) the default share image `web/public/og-default.png` was made with headless Chrome and is replaced in F12; (6) serve `404.html` for missing pages (CloudFront, Phase 6).
- **Dev server quirks (2026-11-19):** after installing React, `npm run dev` needed `optimizeDeps.include: ['react-dom/client']` (now in `astro.config.mjs`); if islands ever show "Error hydrating" in the browser console, stop the dev server and delete `web/node_modules/.vite`. A background dev server started on 2026-11-17 was stopped on 2026-11-19 to test config changes: restart with `npm run dev`.
- **Listings table needs real-data check (2026-11-19):** it was built and tested against a mock; after 13.2 is deployed, open `/iphone/iphone-16-pro-max/listings/` in `npm run dev` and check the real rows, the 30-day window and the response size.
- `api.ts` recognises "the API said no" by the error text starting with `"API "`; a small error class would be cleaner.
- `api.ts` derives nothing from `site`; the API base URL could be built from `import.meta.env.SITE` so the CloudFront address is written once.
- No type-check step (`astro check`) yet; types in `api.ts` are copied by hand from the Pydantic schemas (could be generated from the OpenAPI spec).
- Product facts to improve later: generic "MacBook Air" bucket excluded (11.4), listing availability unverified (11.1), many listings have `condition = "Unknown"`.
- Free-text listing titles can be low quality (for example "iPhone 16 pro max for sell"); decide if any cleanup or filtering is wanted for displayed titles.
- Contact page needs the owner's email address; images need sourcing and `web/IMAGES.md` (5.5.1).
- **Footer date (2026-11-18) [FIXED 2026-11-19 in F8]:** the footer now shows "Prices updated" with the OLDEST `data_as_of` among all product summaries (`getPricesUpdatedAt()` in `catalog.ts`), not the product catalog's build time.

### 13.6 Apify token for this project  **[CODE DONE 2026-11-17, apply pending]**
The 2026-11-17 pipeline run failed at the scrape step with `UnauthorizedError: User was not found or authentication token is not valid` (Apify HTTP 401): the ECS task read the token from a secret shared with another AWS project. This repo now has its own secret: `modules/secrets` creates `<app>/apify-api-token` from the new sensitive variable `apify_api_token` (root `variables.tf`, `terraform.tfvars`), and the ECS module reads its ARN from `module.secrets.apify_token_secret_arn`. The variable `apify_token_secret_arn` was removed. Owner-run: replace the `apify_token_secret_arn = ...` line in `terraform.tfvars` with `apify_api_token = "<new token>"`, `terraform plan` (expect: 2 new secret resources, an updated ECS execution-role policy, a new task definition revision, nothing replaced), `terraform apply`, put the token in the local `.env` as `APIFY_API_TOKEN`, then trigger a pipeline run. The token ends up in Terraform state (same trade-off as the Gemini key). Not run: Terraform is not installed in the assistant's shell.
