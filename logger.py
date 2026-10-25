"""
logger.py

Append-only JSONL event logger for StockyWhy pipeline steps.
Each call writes one JSON object per line to logs/<log_file>.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


LOGS_DIR = Path("logs")


def _ensure_logs_dir() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


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
    **kwargs,
) -> None:
    """
    Append a single JSONL event to logs/<log_file>.

    Parameters
    ----------
    log_file       : filename within the logs/ directory (e.g. "run_abc123.jsonl")
    run_id         : unique identifier for this investigation run
    agent_name     : which agent emitted this event
    action         : short verb describing what the agent did
    input_summary  : human-readable summary of inputs
    output_summary : human-readable summary of outputs
    model          : LLM model name used (optional)
    confidence     : 0-1 confidence score (optional)
    status         : "ok", "warning", "error"
    **kwargs       : any extra fields to include in the record
    """
    _ensure_logs_dir()

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "agent_name": agent_name,
        "action": action,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "model": model,
        "confidence": confidence,
        "status": status,
    }
    record.update(kwargs)

    log_path = LOGS_DIR / log_file
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
