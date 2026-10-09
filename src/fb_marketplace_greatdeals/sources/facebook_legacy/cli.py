"""Facebook Marketplace pipeline CLI.

Commands:
    run-facebook from-apify --config iphone --mode initial
    run-facebook from-apify --config iphone --mode periodic
    run-facebook from-file --config iphone --file sample_data/data.json
    run-facebook classify
    run-facebook classify --config iphone
    run-facebook transform
    run-facebook notify [--dry-run]
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from typing import Optional

import click
import yaml
from loguru import logger
from rich.console import Console
from rich.rule import Rule
from rich.table import Table
from sqlalchemy import text

from fb_marketplace_greatdeals.config import settings
from fb_marketplace_greatdeals.db.engine import SessionLocal
from fb_marketplace_greatdeals.sources.facebook_legacy.scraper import ApifyRunner
from fb_marketplace_greatdeals.sources.facebook_legacy.stage1 import run as run_stage1
from fb_marketplace_greatdeals.sources.facebook_legacy.stage1 import run_from_records as run_stage1_from_records
from fb_marketplace_greatdeals.sources.facebook_legacy.stage2_classify import run as run_classify
from fb_marketplace_greatdeals.sources.facebook_legacy.stage3_transform import run as run_transform
from fb_marketplace_greatdeals.sources.facebook_legacy.stage4_notify import run as run_notify

console = Console()

logger.remove()
logger.add(sys.stderr, format="<level>{level: <8}</level> | {message}", level="INFO")

_CONFIGS_DIR = Path.cwd() / "configs"


def _run_migrations() -> None:
    from alembic import command as alembic_command
    from alembic.config import Config
    cfg = Config("alembic.ini")
    alembic_command.upgrade(cfg, "head")


# ── Config helpers ────────────────────────────────────────────────────────────


def _load_config(config_name: str) -> dict:
    config_path = _CONFIGS_DIR / f"{config_name}.yaml"
    if not config_path.exists():
        raise click.BadParameter(
            f"Config file not found: {config_path}", param_hint="'--config'"
        )
    with open(config_path) as fh:
        return yaml.safe_load(fh)


def _resolve_category(config: dict) -> uuid.UUID:
    with SessionLocal() as session:
        session.execute(
            text("""
                INSERT INTO categories (id, category_key, category_name, product_type, brand)
                VALUES (:id, :category_key, :category_name, :product_type, :brand)
                ON CONFLICT (category_key) DO NOTHING
            """),
            {
                "id": str(uuid.uuid4()),
                "category_key": config["category_key"],
                "category_name": config["category_name"],
                "product_type": config.get("product_type"),
                "brand": config.get("brand"),
            },
        )
        session.commit()
        category_id = session.execute(
            text("SELECT id FROM categories WHERE category_key = :key"),
            {"key": config["category_key"]},
        ).scalar()
    return category_id


def _build_run_input(config: dict, mode: str) -> dict:
    legacy_cfg = config["sources"]["facebook_legacy"]
    run_config = legacy_cfg[f"{mode}_run"]

    searches = []
    for term in legacy_cfg["search_terms"]:
        entry: dict = {"searchTerm": term}
        if run_config.get("listings_per_search") is not None:
            entry["listingsPerSearch"] = int(run_config["listings_per_search"])
        if run_config.get("days_listed"):
            entry["daysListed"] = run_config["days_listed"]
        if run_config.get("filter_keywords"):
            entry["filterKeywords"] = run_config["filter_keywords"]
        searches.append(entry)

    cities = run_config["cities"]
    city = cities[0] if isinstance(cities, list) else cities

    run_input: dict = {
        "searchMode": "advanced",
        "location": city,
        "radiusKm": str(legacy_cfg["radius_km"]),
        "searches": searches,
        "useDeduplication": run_config["use_deduplication"],
        "fetchDetailedItems": run_config.get("fetch_detailed_items", False),
        "proxyConfiguration": {
            "useApifyProxy": legacy_cfg["proxy"]["use_apify_proxy"],
            "apifyProxyGroups": legacy_cfg["proxy"]["apify_proxy_groups"],
            "apifyProxyCountry": legacy_cfg["proxy"]["apify_proxy_country"],
        },
    }
    if run_config.get("listings_per_search") is not None:
        run_input["listingsPerSearch"] = int(run_config["listings_per_search"])
    if run_config.get("max_listing_age") is not None:
        run_input["maxListingAge"] = run_config["max_listing_age"]

    return run_input


# ── Formatting helpers ────────────────────────────────────────────────────────


def _print_scrape_result(title: str, result, elapsed: float) -> None:
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]"))
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim", width=26)
    table.add_column()
    table.add_row("Run ID", str(result.run_id))
    table.add_row("Status", result.status)
    table.add_row("Total records", str(result.total))
    table.add_row("[green]✓ Newly added[/green]", f"[green]{result.newly_added}[/green]")
    table.add_row("[cyan]~ Changed version[/cyan]", f"[cyan]{result.change_added}[/cyan]")
    table.add_row("[dim]– Skipped[/dim]", f"[dim]{result.skipped}[/dim]")
    table.add_row("[red]✗ Errors[/red]", f"[red]{result.errors}[/red]")
    console.print(table)
    console.print(f"  [dim]Elapsed: {elapsed:.1f}s[/dim]")
    console.print()


def _print_classify_result(title: str, result, elapsed: float) -> None:
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]"))
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim", width=26)
    table.add_column()
    table.add_row("Run ID", str(result.run_id))
    table.add_row("Status", result.status)
    table.add_row("Total pending", str(result.total))
    table.add_row("[green]✓ Classified[/green]", f"[green]{result.classified}[/green]")
    table.add_row("[red]✗ Errors[/red]", f"[red]{result.errors}[/red]")
    console.print(table)
    console.print(f"  [dim]Elapsed: {elapsed:.1f}s[/dim]")
    console.print()


# ── CLI group ─────────────────────────────────────────────────────────────────


@click.group()
def cli() -> None:
    """FB Marketplace Great Deals — scrape and classify product listings."""
    _run_migrations()


# ── from-apify ────────────────────────────────────────────────────────────────


@cli.command("from-apify")
@click.option("--config", "-c", "config_name", required=True)
@click.option(
    "--mode", "-m",
    type=click.Choice(["initial", "periodic"], case_sensitive=False),
    required=True,
)
@click.option(
    "--stage", "-s",
    type=click.Choice(["scrape", "classify", "all"], case_sensitive=False),
    default="all", show_default=True,
)
def from_apify(config_name: str, mode: str, stage: str) -> None:
    """Fetch listings from Apify for every city in the config and run the pipeline."""
    stage = stage.lower()
    console.print()
    total_start = time.monotonic()

    config      = _load_config(config_name)
    legacy_cfg  = config.get("sources", {}).get("facebook_legacy", {})

    if not legacy_cfg.get("enabled", False):
        console.print(f"[yellow]facebook_legacy is disabled for {config_name!r} — skipping.[/yellow]")
        return

    category_id = _resolve_category(config)

    if stage in ("scrape", "all"):
        run_input    = _build_run_input(config, mode)
        run_cfg      = legacy_cfg[f"{mode}_run"]
        timeout_secs  = run_cfg.get("actor_timeout_secs", 7200)
        memory_mbytes = run_cfg.get("actor_memory_mb", 2048)
        runner        = ApifyRunner(settings.apify_api_token, legacy_cfg["actor_id"])

        logger.info(f"[Apify] Fetching: {run_input['location']!r}")
        all_records = runner.run(run_input, timeout_secs=timeout_secs, memory_mbytes=memory_mbytes)

        source_label = f"{config_name}:{mode}"
        t0      = time.monotonic()
        result1 = run_stage1_from_records(
            all_records,
            source=source_label,
            category_id=category_id,
            category_key=config["category_key"],
            mode=mode,
        )
        _print_scrape_result("STAGE 1 — Fetch & Extract", result1, time.monotonic() - t0)

    if stage in ("classify", "all"):
        t0      = time.monotonic()
        result2 = run_classify(category_id=category_id, category_key=config["category_key"])
        _print_classify_result("STAGE 2 — AI Classify", result2, time.monotonic() - t0)

    console.print(Rule(f"[dim]Done in {time.monotonic() - total_start:.1f}s[/dim]"))
    console.print()


# ── from-file ─────────────────────────────────────────────────────────────────


@cli.command("from-file")
@click.option("--config", "-c", "config_name", required=True)
@click.option(
    "--file", "-f", "source_file",
    required=True,
    type=click.Path(path_type=Path, exists=True),
)
@click.option(
    "--stage", "-s",
    type=click.Choice(["scrape", "classify", "all"], case_sensitive=False),
    default="all", show_default=True,
)
def from_file(config_name: str, source_file: Path, stage: str) -> None:
    """Load listings from a saved Apify JSON file and run the pipeline."""
    stage = stage.lower()
    console.print()
    total_start = time.monotonic()

    config      = _load_config(config_name)
    category_id = _resolve_category(config)

    if stage in ("scrape", "all"):
        t0      = time.monotonic()
        result1 = run_stage1(
            source_file,
            category_id=category_id,
            category_key=config["category_key"],
        )
        _print_scrape_result("STAGE 1 — Extract & Load", result1, time.monotonic() - t0)

    if stage in ("classify", "all"):
        t0      = time.monotonic()
        result2 = run_classify(category_id=category_id, category_key=config["category_key"])
        _print_classify_result("STAGE 2 — AI Classify", result2, time.monotonic() - t0)

    console.print(Rule(f"[dim]Done in {time.monotonic() - total_start:.1f}s[/dim]"))
    console.print()


# ── classify ──────────────────────────────────────────────────────────────────


@cli.command("classify")
@click.option("--config", "-c", "config_name", required=False, default=None)
def classify_cmd(config_name: Optional[str]) -> None:
    """Run AI classification on unclassified raw listings.

    Without --config, classifies all unclassified listings across every category.
    """
    console.print()
    t0 = time.monotonic()

    category_id  = None
    category_key = None
    if config_name:
        config       = _load_config(config_name)
        category_id  = _resolve_category(config)
        category_key = config["category_key"]

    result = run_classify(category_id=category_id, category_key=category_key)
    _print_classify_result("STAGE 2 — AI Classify", result, time.monotonic() - t0)
    console.print(Rule(f"[dim]Done in {time.monotonic() - t0:.1f}s[/dim]"))
    console.print()


@cli.command("transform")
def transform_cmd() -> None:
    """Rebuild mart tables by running dbt models (dim_category, dim_product, fct_listings, fct_listing_history)."""
    console.print()
    t0 = time.monotonic()

    result = run_transform()

    console.print(Rule("[bold cyan]STAGE 3 — dbt Transform[/bold cyan]"))
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim", width=26)
    table.add_column()
    table.add_row("Status", result.status)
    table.add_row("Return code", str(result.returncode))
    console.print(table)
    console.print(f"  [dim]Elapsed: {time.monotonic() - t0:.1f}s[/dim]")
    console.print(Rule(f"[dim]Done in {time.monotonic() - t0:.1f}s[/dim]"))
    console.print()

    if result.returncode != 0:
        raise SystemExit(result.returncode)


@cli.command("notify")
@click.option("--dry-run", is_flag=True, help="Print the email that would be sent; write and send nothing.")
def notify_cmd(dry_run: bool) -> None:
    """Add passing deal candidates to deal_alerts and send one email digest."""
    console.print()
    t0 = time.monotonic()

    result = run_notify(dry_run=dry_run)

    console.print(Rule("[bold cyan]STAGE 4 — Deal Notify[/bold cyan]"))
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim", width=26)
    table.add_column()
    table.add_row("Status", result.status)
    table.add_row("New alerts", str(result.new_alerts))
    table.add_row("Listings in email" if not dry_run else "Listings that would be emailed", str(result.emailed))
    if result.error:
        table.add_row("Error", result.error)
    console.print(table)
    console.print(Rule(f"[dim]Done in {time.monotonic() - t0:.1f}s[/dim]"))
    console.print()

    if result.status != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
