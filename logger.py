"""
logger.py

Append-only JSONL event logger for StockWhy pipeline steps.
Each call writes one JSON object per line to <logs dir>/<log_file>.
The logs directory is STOCKWHY_LOGS_DIR (default "logs"), read on every call.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


LOGS_DIR = Path("logs")


def logs_dir() -> Path:
    """Directory for JSONL logs: STOCKWHY_LOGS_DIR if set, else ./logs."""
    configured = os.getenv("STOCKWHY_LOGS_DIR")
    if configured and configured.strip():
        return Path(configured.strip())
    return LOGS_DIR


def _ensure_logs_dir() -> Path:
    directory = logs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def log_event(
    log_file: str,
    run_id: str,
    agent_name: str,
    action: str,
    input_summary: str,
    output_summary: str,
    model: str = None,
    confidence: float = None,
    status: str = "ok",
    target_agent: str = None,
    retry_count: int = 0,
    requested_model: str = None,
    served_model: str = None,
    **kwargs,
) -> None:
    """
    Append a single JSONL event to <logs dir>/<log_file>.

    Parameters
    ----------
    log_file       : filename within the logs directory (e.g. "run_abc123.jsonl")
    run_id         : unique identifier for this investigation run
    agent_name     : which agent emitted this event
    action         : short verb describing what the agent did
    input_summary  : human-readable summary of inputs
    output_summary : human-readable summary of outputs
    model          : model that produced the output ("rule-based" offline)
    confidence     : 0-1 confidence score (optional)
    status         : "ok", "warning", "error"
    target_agent   : agent this event is addressed to (delegation/critique)
    retry_count    : how many retries this step needed
    requested_model: model/lane asked for (e.g. "meterless/deep"); recorded when given
    served_model   : model the provider reported serving; recorded when given
    **kwargs       : any extra fields to include in the record
    """
    directory = _ensure_logs_dir()

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "agent_name": agent_name,
        "action": action,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "target_agent": target_agent,
        "model": model,
        "confidence": confidence,
        "retry_count": retry_count,
        "status": status,
    }
    if requested_model:
        record["requested_model"] = requested_model
    if served_model:
        record["served_model"] = served_model
    record.update(kwargs)

    log_path = directory / log_file
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
