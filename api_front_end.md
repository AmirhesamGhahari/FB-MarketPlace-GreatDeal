# API & Front End — Design and Development Guide

Status: **PLANNING — nothing in this document has been implemented yet.**
Last updated: 2026-10-19

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
- **[DECIDED]** The generic "MacBook Air" bucket (chip unknown) is **left out of v1**: no catalog row, no page. Recovering those listings is a later re-classification task (Section 11.2).
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
| `mart_product_daily` | product × day | Time series for charts (`fct_products_daily` joined to the catalog; same grain, no regrouping) |
| `mart_product_listings` | one row per listing passing `benchmark_listings` | price, condition, storage, city, URL, `listed_at`; indexed on `(product_id, listed_at)` and `(product_id, price)`. No availability filtering in v1. |
| `mart_top_deals` | one row per top deal | Cross-category deals for the homepage |

Work items:
- [x] **DONE** Product catalog seed built and verified: `transform/seeds/product_catalog.csv` (+ a minimal `seeds/schema.yml` with `unique`/`not_null` tests on `product_model` and `slug`). The four `product_model` spellings were checked against Gemini's output and match exactly. **[DECIDED]** no extra singular tests (listing-existence and category-mismatch checks were removed to keep tests minimal); a misspelled `product_model` in the catalog would silently give an empty page, so re-check spelling by query when adding products.
- [ ] Replace the hardcoded `'2026-08-01'` date
- [ ] Create the shared **`benchmark_listings`** model (**[DECIDED]**, see 5.1.2) and refactor `fct_products_daily` to read from it, proving the output is unchanged
- [ ] No sold/age/availability filter in v1 (**[DECIDED]**, see 5.1.1)
- [ ] Add dbt tests: unique slugs, not-null keys, price sanity ranges, minimum listings per product page
- [ ] Optional: a `product_page_payload (slug, payload jsonb)` table so the main product endpoint is a single primary-key lookup (decide after seeing real payload sizes)
- [ ] Add the read-only Postgres role with `SELECT` on `serving` only

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
**[PROPOSED]** endpoints:

| Endpoint | Returns |
|---|---|
| `GET /v1/categories` | Categories with product counts |
| `GET /v1/categories/{key}/products` | Products with headline stats |
| `GET /v1/products/{slug}` | Summary stats: 7d/30d average, 25th-percentile cutoff, cheapest |
| `GET /v1/products/{slug}/series?window=30d` | Chart time series |
| `GET /v1/products/{slug}/listings?window=7d&sort=price&page=1` | Paginated listings |
| `GET /v1/deals/top` | Homepage deals |

Conventions:
- Version prefix `/v1`
- Every response includes `data_as_of` (so the UI can show "updated 2 hours ago")
- One consistent error shape; pagination via `page`/`page_size` with a hard maximum page size
- Whitelisted query values only (`window` in `1d|3d|7d|30d`, `sort` in a fixed set) to avoid arbitrary queries
- OpenAPI spec generated by FastAPI doubles as the contract for the frontend

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

### 11.2 Other later ideas
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

Next up: `mart_product_daily` (per-product daily series for the charts), then `mart_product_listings`, then the read-only DB role and the API (Phases 2–4).
