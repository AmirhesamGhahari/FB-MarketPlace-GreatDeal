# FB Marketplace Great Deals

An intelligent data pipeline that scrapes Facebook Marketplace listings for consumer electronics (iPhone, iPad, MacBook, etc.), detects great deals using AI classification, tracks price history over time, and surfaces results on a web dashboard.

## How it works

The pipeline runs in two stages:

**Stage 1 — Scrape & Extract:** Fetches listings from Facebook Marketplace via Apify actors and loads them into a raw table using Change Data Capture (CDC). Each listing is tracked over time — when price, title, or location changes, the old version is closed and a new one is inserted, preserving the full price history.

**Stage 2 — Classify:** Reads new raw records and uses Gemini AI to classify listings: product condition, deal quality score, whether it is a genuine deal vs. spam/overpriced, and extracted structured attributes (storage, colour, model variant, etc.).

Both stages are idempotent — re-running them is always safe.

```
Apify scraper (FB Marketplace)
            │
            ▼
  facebook.raw  (CDC — full price history per listing)
            │
            ▼
  facebook.classified  (AI-enriched, analytics-ready)
```

## Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| Database | PostgreSQL |
| ORM / migrations | SQLAlchemy 2.x, Alembic |
| Scraper | Apify actors (raider-api & datavoyantlab) |
| AI Classification | Google Gemini |
| Config | YAML + `.env` via Pydantic Settings |
| CLI | Click + Rich |
| Infra | AWS (ECS, Aurora, ECR, Lambda, Step Functions) |

## Project structure

```
├── configs/                    # One YAML file per product category search
├── src/fb_marketplace_greatdeals/
│   ├── config.py               # Settings loaded from .env
│   ├── db/
│   │   ├── engine.py
│   │   └── models/
│   │       ├── event.py                               # Category/search registry
│   │       ├── facebook_listings_legacy_raw.py        # Raw CDC table (legacy actor)
│   │       ├── facebook_listings_legacy_classified.py # Classified table (legacy actor)
│   │       ├── facebook_listings_new_raw.py           # Raw CDC table (new actor)
│   │       ├── facebook_listings_new_classified.py    # Classified table (new actor)
│   │       └── pipeline_tables.py                     # Pipeline run audit log
│   └── sources/
│       ├── facebook_legacy/    # Scraping via raider-api actor
│       └── facebook_new/       # Scraping via datavoyantlab actor
└── alembic/                    # Database migrations
```

## Setup

### Prerequisites

- Python 3.12+
- PostgreSQL 14+
- An [Apify](https://apify.com) account (required for live scraping)
- A [Google Gemini](https://ai.google.dev) API key (required for AI classification)

### Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Environment variables

Copy `.env.example` to `.env` and fill in your values:

```dotenv
DATABASE_URL=postgresql://user:password@localhost:5432/fb_marketplace_greatdeals
APIFY_API_TOKEN=your_apify_token
GEMINI_API_KEY=your_gemini_key
```

### Database setup

```bash
alembic upgrade head
```

To generate a new migration after model changes:

```bash
alembic revision --autogenerate -m "describe_the_change"
alembic upgrade head
```

## Usage

### Scrape FB Marketplace and classify listings

```bash
# Full initial scrape — gets all available listings
run-facebook-new from-config --config iphone_toronto --mode initial

# Periodic update — recent listings only, with deduplication
run-facebook-new from-config --config iphone_toronto --mode periodic

# Scrape only (no AI classification)
run-facebook-new from-config --config iphone_toronto --mode periodic --stage scrape

# Classify previously scraped listings
run-facebook-new classify --config iphone_toronto
```

### Legacy actor commands

```bash
run-facebook-legacy from-apify --config macbook_toronto --mode initial
run-facebook-legacy from-file --config macbook_toronto --file sample_data/dump.json
run-facebook-legacy classify
```

## Adding a new product category search

1. Create a YAML config in `configs/`:

```yaml
# configs/iphone_toronto.yaml
event_key: "iphone_toronto"
event_name: "iPhone — Toronto"

sources:
  facebook_new:
    enabled: true
    actor_id: "datavoyantlab/facebook-marketplace-scraper"
    filter_keywords:
      - "iphone"
    marketplace_urls:
      - "https://www.facebook.com/marketplace/toronto/search?query=iphone+14"
      - "https://www.facebook.com/marketplace/toronto/search?query=iphone+15"
    initial_run:
      max_items: 200
      fetch_item_details: false
      deduplicate_across_runs: false
      stop_on_first_page_all_duplicates: false
    periodic_run:
      max_items: 50
      fetch_item_details: false
      deduplicate_across_runs: true
      stop_on_first_page_all_duplicates: true
```

2. Run the pipeline:

```bash
run-facebook-new from-config --config iphone_toronto --mode initial
```

The category is automatically registered in the database on first run.

## Database schema

| Table | Purpose |
|-------|---------|
| `events` | Registry of tracked product searches — auto-populated on first run |
| `facebook.raw` | Raw CDC records from scrape runs. One row per version of a listing. `valid_to IS NULL` = current version |
| `facebook.classified` | AI-enriched records with deal quality scores, extracted attributes |
| `pipeline_runs` | Audit log for every Stage 1 and Stage 2 execution with record counts |

### CDC (Change Data Capture)

Stage 1 tracks listing changes over time:

- **New listing** → insert with `valid_from = now()`, `valid_to = NULL`
- **Existing listing, no change** → skip
- **Existing listing, price/title/location changed** → close old row (`valid_to = now()`), insert new row

## Infrastructure

AWS infrastructure is managed with Terraform in `infra/terraform/`. It provisions ECS (container runs), Aurora PostgreSQL, ECR (Docker images), Lambda + Step Functions (scheduling), Secrets Manager, and CloudWatch monitoring.

See `infra/terraform/README.md` for full deployment instructions.
