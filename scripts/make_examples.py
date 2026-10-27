"""
scripts/make_examples.py

Regenerate output_examples/ from input_examples/ in SAMPLE_MODE (offline,
rule-based). Inputs run in file order against one fresh case memory, so
05_memory_recall.json recalls the finding stored by 01. Keys starting with
"_" are comments; "_env" sets environment variables for that one run.

    python scripts/make_examples.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["SAMPLE_MODE"] = "true"
os.environ.pop("STOCKWHY_USE_LLM", None)

from engines.hmem import CaseMemory  # noqa: E402
import orchestrator  # noqa: E402

StockWhy = orchestrator.StockWhy
from run import execute_request  # noqa: E402



def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

def main() -> int:
    _utf8_stdio()
    out_dir = ROOT / "output_examples"
    out_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        agent = StockWhy(memory=CaseMemory(Path(tmp) / "hmem.json"))
        for path in sorted((ROOT / "input_examples").glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            env = payload.get("_env", {})
            os.environ.update(env)
            try:
                result, _ = execute_request(payload, interactive=False, agent=agent)
            finally:
                for key in env:
                    os.environ.pop(key, None)
            (out_dir / path.name).write_text(json.dumps(result, indent=2, default=str) + "\n",
                                             encoding="utf-8")
            cause = (result.get("verified_cause") or {}).get("hypothesis_name", "")
            print(f"{path.name:32s} {result.get('status'):12s} {cause}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
