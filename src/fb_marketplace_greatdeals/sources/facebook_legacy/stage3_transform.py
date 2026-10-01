from __future__ import annotations

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
    }

    project_dir = str(Path.cwd() / "transform")

    cmd = [
        "dbt", "run",
        "--project-dir", project_dir,
        "--profiles-dir", project_dir,
        "--no-use-colors",
    ]

    logger.info(f"[Transform] dbt project: {project_dir}")
    proc = subprocess.run(cmd, env=env)

    status = "completed" if proc.returncode == 0 else "failed"
    logger.info(f"[Transform] Finished — status={status} returncode={proc.returncode}")
    return TransformResult(status=status, returncode=proc.returncode)
