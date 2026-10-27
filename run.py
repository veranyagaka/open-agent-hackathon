"""
run.py

StockyWhy CLI entry point.
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stockywhy",
        description="StockyWhy - Drug Stockout Investigation System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python run.py --dataset data/sample "
            "--facility FAC-011 --commodity 'ORS sachet' --month 2026-03\n"
            "  python run.py --case data/cases/normal/case_01\n"
            "  SAMPLE_MODE=true python run.py --facility FAC-011 "
            "--commodity 'ORS sachet' --month 2026-03\n"
            "  python run.py --serve\n"
        ),
    )

    parser.add_argument(
        "--dataset",
        help="Path to dataset directory (CSV/JSON files). "
             "Defaults to STOCKWHY_DATASET. Overridden by SAMPLE_MODE=true.",
    )
    parser.add_argument("--facility", help="Facility ID, e.g. FAC-011")
    parser.add_argument(
        "--commodity",
        help="Medicine name, e.g. 'ORS sachet'",
    )
    parser.add_argument("--month", help="Reporting month YYYY-MM, e.g. 2026-03")
    parser.add_argument(
        "--case",
        help="Path to a case directory (contains stock.csv etc.) "
             "OR a row from data/cases/questions.csv",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start HTTP server on port 8000 with /run endpoint",
    )
    parser.add_argument(
        "--no-review",
        action="store_true",
        help="Skip interactive pharmacist review step",
    )
    parser.add_argument(
        "--output",
        help="Write full JSON result to this file",
    )
    parser.add_argument(
        "--log-file",
        help="JSONL log filename (written to logs/ directory)",
    )

    # Legacy / compat arguments
    parser.add_argument("--input", help=argparse.SUPPRESS)
    parser.add_argument("--scenario-seed", type=int, default=42, help=argparse.SUPPRESS)
    parser.add_argument("--plant-cause", help=argparse.SUPPRESS)

    return parser


def _resolve_case(case_path: str) -> dict:
    """
    Resolve a --case argument to {dataset, facility_id, commodity, month}.

    Accepts:
    - A case directory path (contains stock.csv etc.)
    - A row from data/cases/questions.csv matched by dataset path prefix
    """
    project_root = Path(__file__).resolve().parent
    questions_csv = project_root / "data" / "cases" / "questions.csv"
    case_p = Path(case_path)

    if questions_csv.exists():
        with open(questions_csv, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row_dataset = project_root / row["dataset"]
                if (
                    row_dataset.resolve() == case_p.resolve()
                    or row["dataset"].replace("\\", "/").endswith(
                        case_path.replace("\\", "/").rstrip("/")
                    )
                ):
                    return {
                        "dataset": str(row_dataset),
                        "facility_id": row["facility_id"],
                        "commodity": row["commodity"],
                        "month": row["month"],
                    }

    if case_p.is_dir():
        return {
            "dataset": str(case_p),
            "facility_id": None,
            "commodity": None,
            "month": None,
        }

    return {"dataset": case_path, "facility_id": None, "commodity": None, "month": None}


def _print_results(result: dict) -> None:
    """Print a nicely formatted summary of the investigation result."""
    print("\n" + "="*60)
    print("  STOCKYWHY INVESTIGATION RESULTS")
    print("="*60)
    print(f"  Facility  : {result.get('facility_id', '')}")
    print(f"  Commodity : {result.get('commodity', '')}")
    print(f"  Month     : {result.get('month', '')}")
    print(f"  Run ID    : {result.get('run_id', '')}")

    if "error" in result:
        print(f"\n  WARNING: ERROR: {result['error']}")
        return

    print(f"\n  Most Likely Cause: {result.get('most_likely_cause', 'Unknown')}")

    ranked = result.get("ranked_hypotheses", [])
    if ranked:
        print("\n  Ranked Hypotheses:")
        for h in ranked:
            print(
                f"    [{h.get('likelihood','?').upper():6}] "
                f"{h.get('hypothesis_id','?')} {h.get('hypothesis_name','')}"
                f" - {h.get('verdict','?')}"
            )

    actions = result.get("approved_actions") or result.get("actions", [])
    if actions:
        print(f"\n  Proposed Actions ({len(actions)}):")
        for a in actions:
            flag = " [AMENDED]" if "pharmacist_amendment" in a else ""
            print(
                f"    {a.get('action_id','?')} [{a.get('priority','?').upper()}]{flag}"
                f" - {a.get('action','')}"
            )
            print(f"         Owner: {a.get('proposed_owner','')}  "
                  f"By: {a.get('timeframe','')}")

    rejected = result.get("rejected_actions", [])
    if rejected:
        print(f"\n  Rejected Actions: {len(rejected)}")

    strategist = result.get("steps", {}).get("action_strategist", {})
    comm = strategist.get("communication_draft", "")
    if comm:
        print("\n  Communication Draft:")
        for line in comm.strip().split("\n"):
            print(f"    {line}")

    print(f"\n  Log: {result.get('log_file', 'N/A')}")
    print("="*60)


def _serve(port: int = 8000) -> None:
    """Start a minimal HTTP server exposing a /run endpoint."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    print(f"StockyWhy HTTP server starting on port {port}...")
    print(f"POST /run with JSON body: {{dataset, facility_id, commodity, month}}")
    print("Press Ctrl+C to stop.\n")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # suppress default access log
            pass

        def do_GET(self):
            if self.path == "/health":
                body = json.dumps({"status": "ok", "service": "stockywhy"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path != "/run":
                self.send_response(404)
                self.end_headers()
                return

            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                payload = json.loads(body)
            except Exception as exc:
                self._error(400, f"Invalid JSON: {exc}")
                return

            dataset = payload.get("dataset")
            facility_id = payload.get("facility_id")
            commodity = payload.get("commodity")
            month = payload.get("month")

            if not all([dataset, facility_id, commodity, month]):
                self._error(400, "Required: dataset, facility_id, commodity, month")
                return

            try:
                from orchestrator import StockyWhy
                agent = StockyWhy()
                result = agent.run(
                    dataset_dir=dataset,
                    facility_id=facility_id,
                    commodity=commodity,
                    month=month,
                    interactive=False,
                )
                response_body = json.dumps(result, default=str).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)
            except Exception as exc:
                self._error(500, str(exc))

        def _error(self, code: int, msg: str) -> None:
            body = json.dumps({"error": msg}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("0.0.0.0", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    argv = sys.argv[1:]

    # Display the custom help screen for bare "help" command
    if argv == ["help"]:
        from cli_help import show_help
        show_help()
        return

    parser = build_parser()
    parsed = parser.parse_args(argv)

    # --serve mode
    if parsed.serve:
        _serve(port=8000)
        return

    # Resolve SAMPLE_MODE
    sample_mode = os.environ.get("SAMPLE_MODE", "false").lower() == "true"

    # Resolve dataset/facility/commodity/month from --case or direct args
    dataset = parsed.dataset
    facility_id = parsed.facility
    commodity = parsed.commodity
    month = parsed.month

    if parsed.case:
        resolved = _resolve_case(parsed.case)
        dataset = dataset or resolved.get("dataset")
        facility_id = facility_id or resolved.get("facility_id")
        commodity = commodity or resolved.get("commodity")
        month = month or resolved.get("month")

    if not dataset:
        dataset = os.getenv("STOCKWHY_DATASET")

    if sample_mode:
        dataset = os.path.join(os.path.dirname(__file__), "data", "sample")

    # Validate required args
    missing = []
    if not dataset and not sample_mode:
        missing.append("--dataset")
    if not facility_id:
        missing.append("--facility")
    if not commodity:
        missing.append("--commodity")
    if not month:
        missing.append("--month")

    if missing:
        print(f"\nError: missing required arguments: {', '.join(missing)}")
        print("\nRun 'python run.py help' for usage examples.")
        sys.exit(1)

    # Run the pipeline
    try:
        from orchestrator import StockyWhy
        agent = StockyWhy()
        result = agent.run(
            dataset_dir=dataset,
            facility_id=facility_id,
            commodity=commodity,
            month=month,
            log_file=parsed.log_file,
            interactive=not parsed.no_review,
        )
    except KeyboardInterrupt:
        print("\nInvestigation cancelled.")
        sys.exit(0)
    except Exception as exc:
        print(f"\nError: {exc}")
        print("Run with PYTHONTRACEBACK=1 for details.")
        if os.environ.get("PYTHONTRACEBACK"):
            raise
        sys.exit(1)

    # Print results
    _print_results(result)

    # Optionally write full JSON result
    if parsed.output:
        out_path = Path(parsed.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\nFull result written to: {parsed.output}")

    # Exit with error code if pipeline failed
    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
