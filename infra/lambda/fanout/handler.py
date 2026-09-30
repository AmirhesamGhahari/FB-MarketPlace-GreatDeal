"""Pipeline dispatcher Lambda — TaskProducer for Step Functions.

Called by the SFN TaskProducer state. Reads DynamoDB to determine the
run mode (initial vs periodic) for each category config, then returns
a task list that SFN uses to drive the RunFBLegacy Map state.

Manual override: pass {"tasks": {"facebook_legacy": [...]}} as SFN input
to bypass DynamoDB lookup and run specific tasks directly.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import boto3

dynamodb = boto3.client("dynamodb")


def lambda_handler(event, context):
    # Manual override: caller passes {"tasks": {...}} directly in SFN input
    if "tasks" in event:
        return event

    configs: list[str] = json.loads(os.environ["CATEGORY_CONFIGS"])
    state_table = os.environ["STATE_TABLE_NAME"]

    # Batch-read current mode for each config
    keys = [{"pk": {"S": f"{c}#facebook_legacy"}} for c in configs]
    response = dynamodb.batch_get_item(
        RequestItems={state_table: {"Keys": keys}}
    )
    items = {
        item["pk"]["S"]: item.get("mode", {}).get("S", "initial")
        for item in response.get("Responses", {}).get(state_table, [])
    }

    run_id = str(uuid.uuid4())
    now = datetime.now(ZoneInfo("America/Toronto")).isoformat()

    facebook_legacy_tasks = []
    for config in configs:
        state_key = f"{config}#facebook_legacy"
        mode = items.get(state_key, "initial")
        command = ["run-facebook", "from-apify", "--config", config, "--mode", mode, "--stage", "all"]
        facebook_legacy_tasks.append({
            "command": command,
            "state_key": state_key,
            "mode": mode,
        })

    return {
        "run": {"id": run_id, "started_at": now},
        "tasks": {"facebook_legacy": facebook_legacy_tasks},
    }
