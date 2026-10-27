"""
scripts/trace_view.py

Print a run's JSONL trace as one readable line per event: which agent did
what, who it handed to, which model produced it, its confidence, retries
and status.

    python scripts/trace_view.py                 # latest run in logs/
    python scripts/trace_view.py logs/run_x.jsonl
    python scripts/trace_view.py --only evaluator,scout
    python scripts/trace_view.py --actions memory_recall,plan_waves
    python scripts/trace_view.py --actions 'contract.*'   # prefix match
    python scripts/trace_view.py --list-events
"""

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Short plain-language labels for events whose names are not self-explanatory.
EVENT_LABELS = {
    "zetaris_query": "SQL sent to Zetaris",
    "stockout_check": "was there a stock-out at all?",
    "record_check": "stock record consistency check",
    "transfer_candidates": "nearby facilities with surplus",
    "verify_transfer": "transfer re-checked against the rows",
    "scrub_free_text": "free text limited to verified rows",
    "contract.issued": "Scout contract issued",
    "contract.verified": "Scout contract checked",
    "contract.expired": "Scout contract expired",
    "contract.refused": "Scout contract refused a capability",
    "scout_gate": "Scout screened the request",
    "memory_recall": "case memory recalled",
    "memory_store": "finding stored (pending approval)",
    "memory_feedback": "pharmacist decision recorded",
    "escalate_to_pharmacist": "no verified cause: escalated",
}


def _matches(action: str, wanted: set) -> bool:
    return any(action == w or (w.endswith("*") and action.startswith(w[:-1])) for w in wanted)


def latest_log() -> Path:
    logs = Path(os.getenv("STOCKWHY_LOGS_DIR") or REPO_ROOT / "logs")
    runs = sorted(logs.glob("run_*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not runs:
        sys.exit(f"No run logs in {logs}/")
    return runs[-1]


def _model_tag(e: dict) -> str:
    served = e.get("served_model") or e.get("model")
    requested = e.get("requested_model")
    if served and requested and served != requested:
        return f"[{served} via {requested}]"
    return f"[{served or requested or 'model?'}]"


def _confidence_tag(e: dict) -> str:
    c = e.get("confidence")
    if isinstance(c, (int, float)) and not isinstance(c, bool):
        return f" conf={c:.2f}"
    return ""


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Readable view of a StockWhy run trace (JSONL).")
    ap.add_argument("log", nargs="?", help="JSONL trace (default: latest in logs/)")
    ap.add_argument("--only", help="comma-separated agent names to show")
    ap.add_argument("--actions", help="comma-separated actions to show")
    ap.add_argument("--width", type=int, default=110, help="summary width")
    ap.add_argument("--list-events", action="store_true", help="list the events this viewer labels")
    args = ap.parse_args()
    if args.list_events:
        for name, label in EVENT_LABELS.items():
            print(f"{name:24} {label}")
        return 0

    path = Path(args.log) if args.log else latest_log()
    only = set(args.only.split(",")) if args.only else None
    actions = set(args.actions.split(",")) if args.actions else None
    print(f"trace {path.name}")
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            print(f"(skipped a line that is not JSON: {line[:60]!r})")
            continue
        if only and e.get("agent_name") not in only:
            continue
        if actions and not _matches(str(e.get("action")), actions):
            continue
        retry = f" retry={e['retry_count']}" if e.get("retry_count") else ""
        status = e.get("status", "")
        flag = "" if status == "ok" else f" [{status.upper()}]"
        summary = str(e.get("output_summary", ""))[:args.width]
        label = EVENT_LABELS.get(str(e.get("action")))
        if label:
            summary = f"({label}) {summary}"[:args.width + len(label) + 3]
        print(f"{str(e.get('timestamp', ''))[11:19]}  {str(e.get('agent_name', '?')):>21} -> "
              f"{str(e.get('target_agent')):<22} {e.get('action', '?')} {_model_tag(e)}"
              f"{_confidence_tag(e)}{retry}{flag}")
        print(f"{'':31}{summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
