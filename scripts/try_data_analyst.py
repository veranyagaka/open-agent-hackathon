"""
scripts/try_data_analyst.py

Manual smoke check for the Data Analyst agent (formerly test_agent.py at the
repo root, which called the LLM at import time and broke pytest).

    python scripts/try_data_analyst.py            # uses llm_enabled() rule
    SAMPLE_MODE=true python scripts/try_data_analyst.py   # rule-based, offline
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))



def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

def main() -> None:
    _utf8_stdio()
    from agents.data_analyst import analyze

    profile = {
        "Monthly_Summary": {
            "columns": ["month", "forecast_demand_units", "actual_demand_units"],
            "row_count": 2,
            "sample_records": [
                {"month": "2026-03", "forecast_demand_units": 90, "actual_demand_units": 92},
                {"month": "2026-06", "forecast_demand_units": 95, "actual_demand_units": 158},
            ],
        }
    }
    question = "Investigate whether stockouts are associated with late orders or demand surges."
    print(json.dumps(analyze(profile, question), indent=2, default=str))


if __name__ == "__main__":
    main()
