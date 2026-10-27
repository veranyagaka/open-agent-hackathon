"""
scripts/trace_view.py

Print a run's JSONL trace as one readable line per event: which agent did
what, who it handed to, retries and status.

    python scripts/trace_view.py                 # latest run in logs/
    python scripts/trace_view.py logs/run_x.jsonl
    python scripts/trace_view.py --only evaluator,scout
    python scripts/trace_view.py --actions memory_recall,plan_waves
"""

import argparse
import json
import os
import sys
from pathlib import Path


def latest_log() -> Path:
    logs = Path(os.getenv("STOCKWHY_LOGS_DIR") or "logs")
    runs = sorted(logs.glob("run_*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not runs:
        sys.exit(f"No run logs in {logs}/")
    return runs[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log", nargs="?", help="JSONL trace (default: latest in logs/)")
    ap.add_argument("--only", help="comma-separated agent names to show")
    ap.add_argument("--actions", help="comma-separated actions to show")
    ap.add_argument("--width", type=int, default=110, help="summary width")
    args = ap.parse_args()

    path = Path(args.log) if args.log else latest_log()
    only = set(args.only.split(",")) if args.only else None
    actions = set(args.actions.split(",")) if args.actions else None
    print(f"trace {path.name}")
    for line in path.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if only and e.get("agent_name") not in only:
            continue
        if actions and e.get("action") not in actions:
            continue
        retry = f" retry={e['retry_count']}" if e.get("retry_count") else ""
        status = e.get("status", "")
        flag = "" if status == "ok" else f" [{status.upper()}]"
        summary = str(e.get("output_summary", ""))[:args.width]
        print(f"{e['timestamp'][11:19]}  {e['agent_name']:>21} -> {str(e.get('target_agent')):<22} "
              f"{e['action']}{retry}{flag}")
        print(f"{'':31}{summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
