"""Pipeline task_producer Lambda.

Called once per Step Functions execution (TaskProducer state).

1. Reads CATEGORY_CONFIGS env var — JSON list of config names (e.g. ["iphone", "macbook"]).
2. Batch-reads DynamoDB to get mode (initial | periodic) per config.
3. Returns {run, tasks: {facebook_legacy: [...]}}.

DynamoDB state keys
───────────────────
"{config_name}#facebook_legacy"  →  mode: "initial" | "periodic"
Written to "periodic" by the SetPeriodicFL Step Functions state after each successful ECS task.
On the next scheduled run the same config uses periodic mode automatically.

Manual override
───────────────
Invoke the Step Functions state machine from the AWS console with custom input to override:

  Force a specific config to run in initial mode:
    {"tasks": {"facebook_legacy": [{"command": ["run-facebook", "from-apify", "--config", "iphone", "--mode", "initial", "--stage", "all"], "state_key": "iphone#facebook_legacy", "mode": "initial"}]}}

  Force all configs to run (scheduled logic bypassed):
    {"run": "manual"}
"""
from __future__ import annotations

import json
import os

import boto3

dynamodb = boto3.resource("dynamodb")


def lambda_handler(event, context):
    return _task_producer(event)


def _task_producer(event: dict) -> dict:
    # Full passthrough: tasks are fully specified in input — skip generation entirely.
    # Useful for forcing a specific config/mode from the AWS console.
    if "tasks" in event:
        run = event.get("run", "manual")
        print(f"[PASSTHROUGH] run={run} tasks={event['tasks']}")
        return {"run": run, "tasks": event["tasks"]}

    run = event.get("run", "scheduled")

    category_configs: list[str] = json.loads(os.environ["CATEGORY_CONFIGS"])

    if not category_configs:
        print("[WARN] CATEGORY_CONFIGS is empty — no tasks to run")
        return {"run": run, "tasks": {"facebook_legacy": []}}

    # Batch-read DynamoDB to get initial/periodic mode for each config
    state_keys = [f"{name}#facebook_legacy" for name in category_configs]
    states = _batch_get_states(state_keys)

    tasks: list[dict] = []
    for name in category_configs:
        state_key = f"{name}#facebook_legacy"
        mode = states.get(state_key, {}).get("mode") or "initial"
        tasks.append({
            "command":   _build_command(name, mode),
            "state_key": state_key,
            "mode":      mode,
        })
        print(f"[QUEUE] {name}/facebook_legacy mode={mode}")

    print(f"[PLAN] run={run} configs={len(tasks)}")
    return {"run": run, "tasks": {"facebook_legacy": tasks}}


def _build_command(config_name: str, mode: str) -> list[str]:
    return ["run-facebook", "from-apify", "--config", config_name, "--mode", mode, "--stage", "all"]


def _batch_get_states(state_keys: list[str]) -> dict[str, dict]:
    table_name = os.environ["STATE_TABLE_NAME"]
    try:
        response = dynamodb.batch_get_item(
            RequestItems={table_name: {"Keys": [{"pk": k} for k in state_keys]}}
        )
        if response.get("UnprocessedKeys"):
            print("[WARN] DynamoDB UnprocessedKeys — some items may default to initial mode")
        return {item["pk"]: item for item in response.get("Responses", {}).get(table_name, [])}
    except Exception as exc:
        print(f"[WARN] batch_get_states failed: {exc} — defaulting all to initial mode")
        return {}
