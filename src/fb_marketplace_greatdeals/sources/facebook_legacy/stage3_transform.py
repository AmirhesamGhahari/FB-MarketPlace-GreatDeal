from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from fb_marketplace_greatdeals.config import settings


@dataclass
class TransformResult:
    status: str
    returncode: int


def _run_tests(dbt_args: list[str], env: dict[str, str], results_path: Path) -> None:
    """Run dbt tests after the build. Tests only warn, so the outcome is logged and never changes the step status."""
    subprocess.run(["dbt", "test", *dbt_args], env=env)
    try:
        results = json.loads(results_path.read_text())["results"]
    except (OSError, ValueError, KeyError):
        logger.warning("[Transform] dbt test results unavailable")
        return
    problems = sorted(r["unique_id"].split(".")[2] for r in results if r["status"] in ("warn", "fail", "error"))
    if problems:
        logger.warning(f"[Transform] dbt test: {len(problems)} warning(s): {', '.join(problems)}")
    else:
        logger.info(f"[Transform] dbt test: all {len(results)} tests passed")


def run() -> TransformResult:
    """Run dbt models to rebuild mart tables (dim_category, dim_product, fct_listings, fct_listing_history)."""
    logger.info("[Transform] Starting dbt run")

    url = urlparse(str(settings.database_url))
    env = {
        **os.environ,
        "DBT_DB_HOST": url.hostname or "",
        "DBT_DB_PORT": str(url.port or 5432),
        "DBT_DB_NAME": (url.path or "").lstrip("/"),
        "DBT_DB_USER": url.username or "",
        "DBT_DB_PASSWORD": url.password or "",
        # dbt's profile has no timezone option; libpq reads this, so current_date and ::date mean Toronto days
        "PGOPTIONS": "-c timezone=America/Toronto",
    }

    project_dir = str(Path.cwd() / "transform")

    dbt_args = [
        "--project-dir", project_dir,
        "--profiles-dir", project_dir,
        "--no-use-colors",
    ]

    logger.info(f"[Transform] dbt project: {project_dir}")
    proc = subprocess.run(["dbt", "seed", *dbt_args], env=env)
    if proc.returncode != 0:
        logger.info(f"[Transform] Finished — status=failed returncode={proc.returncode} (dbt seed)")
        return TransformResult(status="failed", returncode=proc.returncode)

    proc = subprocess.run(["dbt", "run", *dbt_args], env=env)

    if proc.returncode == 0:
        _run_tests(dbt_args, env, Path(project_dir) / "target" / "run_results.json")

    status = "completed" if proc.returncode == 0 else "failed"
    logger.info(f"[Transform] Finished — status={status} returncode={proc.returncode}")
    return TransformResult(status=status, returncode=proc.returncode)
