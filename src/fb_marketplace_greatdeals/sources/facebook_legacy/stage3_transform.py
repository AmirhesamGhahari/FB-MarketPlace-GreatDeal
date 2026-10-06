from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from fb_marketplace_greatdeals.config import settings


@dataclass
class TransformResult:
    status: str
    returncode: int


def run() -> TransformResult:
    """Run dbt models to rebuild mart tables."""
    logger.info("[Transform] Starting dbt run")

    env = {
        **os.environ,
        "DBT_S3_STAGING_DIR": f"s3://{settings.s3_bucket}/athena-results/",
        "DBT_REGION": settings.aws_region,
        "DBT_DATABASE": "fb_marketplace_greatdeals",
        "DBT_SCHEMA": "transformed",
        "DBT_WORKGROUP": settings.athena_workgroup,
    }

    project_dir = str(Path.cwd() / "transform")
    cmd = ["dbt", "run", "--project-dir", project_dir, "--profiles-dir", project_dir, "--no-use-colors"]

    logger.info(f"[Transform] dbt project: {project_dir}")
    proc = subprocess.run(cmd, env=env)

    status = "completed" if proc.returncode == 0 else "failed"
    logger.info(f"[Transform] Finished — status={status} returncode={proc.returncode}")
    return TransformResult(status=status, returncode=proc.returncode)
