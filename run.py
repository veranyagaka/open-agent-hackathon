"""
run.py

StockyWhy CLI entry point.

Three ways in, one result shape out:
  python run.py --facility FAC-011 --commodity "ORS sachet" --month 2026-03
  python run.py --question "Why did FAC-009 run out of magnesium sulphate in March 2026?"
  python run.py --input request.json --json
and POST /run on the --serve HTTP server (same JSON as --input).

Exit code is non-zero only for system or data errors (status "error").
A clarify / refuse / block / insufficient-evidence result exits 0.
"""

import argparse
import calendar
import contextlib
import csv
import json
import os
import re
import sys
import uuid
from pathlib import Path

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sample")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stockywhy",
        description="StockyWhy — Drug Stockout Investigation System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python run.py --dataset data/sample "
            "--facility FAC-011 --commodity 'ORS sachet' --month 2026-03\n"
            "  python run.py --case data/cases/normal/case_01\n"
            "  SAMPLE_MODE=true python run.py --facility FAC-011 "
            "--commodity 'ORS sachet' --month 2026-03\n"
            "  python run.py --question \"Why did FAC-009 run out of magnesium "
            "sulphate in March 2026?\"\n"
            "  python run.py --input request.json --json\n"
            "  python run.py --serve\n"
        ),
    )

    parser.add_argument(
        "--dataset",
        help="Path to dataset directory (CSV/JSON files). "
             "With SAMPLE_MODE=true it defaults to data/sample.",
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

    parser.add_argument(
        "--question",
        help="Ask in plain words, e.g. \"Why did FAC-009 run out of magnesium "
             "sulphate in March 2026?\"",
    )
    parser.add_argument(
        "--input",
        help="JSON request file: {question} or {facility_id, commodity, month}, "
             "optional dataset and role",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the JSON result (no progress output, no prompts)",
    )
    parser.add_argument(
        "--role",
        default="pharmacist",
        help="Who is asking (checked by the Scout gate). Default: pharmacist",
    )

    # Legacy / compat arguments
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
    questions_csv = Path("data/cases/questions.csv")
    case_p = Path(case_path)

    # A case listed in questions.csv carries its facility, medicine and month.
    if questions_csv.exists():
        wanted = case_path.rstrip("/").replace("\\", "/")
        with open(questions_csv, newline="") as f:
            for row in csv.DictReader(f):
                if row["dataset"].rstrip("/") == wanted or wanted.endswith(row["dataset"].rstrip("/")):
                    return {
                        "dataset": case_path,
                        "facility_id": row["facility_id"],
                        "commodity": row["commodity"],
                        "month": row["month"],
                    }

    # If it looks like a directory that exists, use it directly
    if case_p.is_dir():
        # Try to load manifest.json for metadata, else require explicit args
        manifest = case_p / "manifest.json"
        if manifest.exists():
            with open(manifest) as f:
                m = json.load(f)
        return {"dataset": str(case_p), "facility_id": None, "commodity": None, "month": None}

    # Try matching against questions.csv
    if questions_csv.exists():
        with open(questions_csv, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (
                    row["dataset"] == case_path
                    or row["dataset"].endswith(case_path)
                    or case_path in row["dataset"]
                ):
                    return {
                        "dataset": row["dataset"],
                        "facility_id": row["facility_id"],
                        "commodity": row["commodity"],
                        "month": row["month"],
                    }

    # Treat the path as a dataset directory
    return {"dataset": case_path, "facility_id": None, "commodity": None, "month": None}


# ---------------------------------------------------------------------------
# Plain-language questions
# ---------------------------------------------------------------------------

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTHS["sept"] = 9
_GENERIC_WORDS = {"inj", "injection", "tab", "tabs", "tablet", "tablets", "sachet", "sachets",
                  "dispersible", "caps", "capsule", "capsules", "syrup", "iu"}


def _norm(text: str) -> str:
    text = (text or "").lower().replace("sulfate", "sulphate")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return f" {' '.join(text.split())} "


def _known_commodities(dataset_dir: str = None) -> list:
    """Medicine names present in the dataset's stock.csv (falls back to data/sample)."""
    for folder in (dataset_dir, SAMPLE_DIR):
        if not folder:
            continue
        path = Path(folder) / "stock.csv"
        if path.exists():
            with open(path, newline="", encoding="utf-8") as f:
                names = {row.get("commodity", "").strip() for row in csv.DictReader(f)}
            return sorted(n for n in names if n)
    return []


def _aliases(name: str) -> set:
    full = _norm(name).strip()
    words = [w for w in full.split() if w not in _GENERIC_WORDS and not re.search(r"\d", w)]
    out = {full}
    if words:
        out.add(" ".join(words))
        out.add(words[0])
    return {a for a in out if a}


def parse_question(question: str, dataset_dir: str = None) -> dict:
    """
    Turn "Why did FAC-009 run out of magnesium sulphate in March 2026?" into
    {"facility_id", "commodity", "month"}. Anything missing or ambiguous comes
    back as {"status": "clarify", "message", "missing", "candidates"}.
    """
    q = question or ""
    found, missing, candidates = {}, [], {}

    fac = re.search(r"\bfac(?:ility)?[\s_-]*0*(\d{1,3})\b", q, re.IGNORECASE)
    if fac:
        found["facility_id"] = f"FAC-{int(fac.group(1)):03d}"
    else:
        missing.append("facility")

    iso = re.search(r"\b(20\d{2})[-/](0[1-9]|1[0-2])\b", q)
    mmyy = re.search(r"\b(0?[1-9]|1[0-2])/(20\d{2})\b", q)
    named = re.search(r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?\s*,?\s*(20\d{2})?\b",
                      q, re.IGNORECASE)
    if iso:
        found["month"] = f"{iso.group(1)}-{iso.group(2)}"
    elif mmyy:
        found["month"] = f"{mmyy.group(2)}-{int(mmyy.group(1)):02d}"
    elif named and named.group(2):
        found["month"] = f"{named.group(2)}-{_MONTHS[named.group(1).lower()]:02d}"
    elif named:
        missing.append("year")
    else:
        missing.append("month")

    nq = _norm(q)
    scored = []
    for name in _known_commodities(dataset_dir):
        hits = [a for a in _aliases(name) if f" {a} " in nq]
        if hits:
            scored.append((max(hits, key=len), name))
    if scored:
        # Two medicines named -> ambiguous, unless one match is just part of the other.
        top = [name for hit, name in scored
               if not any(hit != other and f" {hit} " in f" {other} " for other, _ in scored)]
        if len(top) == 1:
            found["commodity"] = top[0]
        else:
            missing.append("commodity")
            candidates["commodity"] = top
    else:
        missing.append("commodity")
        candidates["commodity"] = _known_commodities(dataset_dir)

    if missing:
        parts = []
        if "facility" in missing:
            parts.append("which facility (e.g. FAC-011)")
        if "month" in missing:
            parts.append("which month (e.g. March 2026)")
        if "year" in missing:
            parts.append("which year for that month")
        if "commodity" in missing:
            opts = candidates.get("commodity") or []
            parts.append("which medicine" + (f" ({', '.join(opts)})" if opts else ""))
        return {"status": "clarify", "message": "Please say " + "; ".join(parts) + ".",
                "missing": missing, "candidates": candidates, "parsed": found}
    return found


def _clarify_result(question: str, parsed: dict) -> dict:
    return {
        "status": "clarify",
        "question": question,
        "message": parsed["message"],
        "error": f"Clarify: {parsed['message']}",
        "hint": "Ask again with the facility id, medicine and month.",
        "missing": parsed["missing"],
        "candidates": parsed["candidates"],
        "parsed": parsed.get("parsed", {}),
    }


def _invalid(message: str) -> dict:
    return {"status": "invalid_request", "error": message,
            "hint": "Send {question} or {facility_id, commodity, month}; dataset is optional."}


def _screen_request(payload: dict):
    """
    Scout Intent screens the raw request text before anything parses it, so an
    injection or out-of-scope ask is blocked or refused rather than met with a
    clarifying question. Returns a result dict to stop on, or None to continue.
    """
    try:
        from engines.scout_intent import gate
    except ImportError:
        return None
    text = " ".join(str(v) for k, v in payload.items()
                    if isinstance(v, str) and k not in ("dataset", "role"))
    if not text.strip():
        return None
    decision = gate({"question": text, "role": str(payload.get("role") or "pharmacist")}, None)
    if decision.get("decision") not in ("block", "refuse"):
        return None
    from logger import log_event
    run_id = uuid.uuid4().hex[:8]
    log_event(
        log_file=f"run_{run_id}_screen.jsonl", run_id=run_id, agent_name="scout",
        action="scout_gate", input_summary="request text (not logged)",
        output_summary=f"{decision['decision']}: {decision.get('reason', '')}",
        target_agent="user", model="deterministic", confidence=1.0,
        status=decision["decision"],
    )
    return {
        "status": decision["decision"],
        "run_id": run_id,
        "message": decision.get("reason", ""),
        "error": f"Scout Intent {decision['decision']}ed the request: {decision.get('reason', '')}",
        "hint": "Ask why a facility ran out of a medicine in a given month.",
        "scout": {k: v for k, v in decision.items() if k != "contract"},
    }


def execute_request(payload: dict, interactive: bool = False, log_file: str = None,
                    agent=None) -> tuple:
    """
    Run one JSON request (shared by --input, --question and POST /run).

    payload: {"question"} or {"facility_id"/"facility", "commodity", "month"},
             plus optional "dataset" and "role".
    Returns (result, http_status). http_status is 400 for a malformed request,
    otherwise 200 (the result's own "status" says what happened).
    """
    if not isinstance(payload, dict):
        return _invalid("Request must be a JSON object"), 400
    for key, value in payload.items():
        if value is not None and not isinstance(value, (str, int, float, bool)):
            return _invalid(f"Field '{key}' must be a plain value"), 400
        if isinstance(value, str) and len(value) > 500:
            return _invalid(f"Field '{key}' is too long"), 400

    dataset = payload.get("dataset") or None
    if not dataset and os.environ.get("SAMPLE_MODE", "false").lower() == "true":
        dataset = SAMPLE_DIR
    dataset = dataset or SAMPLE_DIR
    question = (payload.get("question") or "").strip() or None
    facility_id = payload.get("facility_id") or payload.get("facility")
    commodity = payload.get("commodity")
    month = payload.get("month")

    screened = _screen_request(payload)
    if screened is not None:
        return screened, 200

    if question and not all([facility_id, commodity, month]):
        parsed = parse_question(question, dataset)
        if parsed.get("status") == "clarify":
            return _clarify_result(question, parsed), 200
        facility_id = facility_id or parsed["facility_id"]
        commodity = commodity or parsed["commodity"]
        month = month or parsed["month"]

    if not all([facility_id, commodity, month]):
        return _invalid("Required: question, or facility_id, commodity and month"), 400

    if agent is None:
        from orchestrator import StockyWhy
        agent = StockyWhy()
    result = agent.run(
        dataset_dir=dataset,
        facility_id=str(facility_id).strip(),
        commodity=str(commodity).strip(),
        month=str(month).strip(),
        log_file=log_file,
        interactive=interactive,
        question=question,
        role=str(payload.get("role") or "pharmacist"),
    )
    return result, 200


def exit_code(result: dict) -> int:
    """Non-zero only for system or data errors."""
    return 1 if result.get("status") in ("error", "invalid_request") else 0


def _print_results(result: dict) -> None:
    """Print a nicely formatted summary of the investigation result."""
    print("\n" + "="*60)
    print("  STOCKYWHY INVESTIGATION RESULTS")
    print("="*60)
    print(f"  Facility  : {result.get('facility_id', '')}")
    print(f"  Commodity : {result.get('commodity', '')}")
    print(f"  Month     : {result.get('month', '')}")
    print(f"  Run ID    : {result.get('run_id', '')}")

    print(f"  Status    : {result.get('status', '')}")

    if "error" in result:
        print(f"\n  ⚠️  {result['error']}")
        if result.get("hint"):
            print(f"  Hint: {result['hint']}")
        print(f"\n  Log: {result.get('log_file', 'N/A')}")
        return

    print(f"\n  Most Likely Cause: {result.get('most_likely_cause', 'Unknown')}")
    cause = result.get("verified_cause") or {}
    if cause.get("citations"):
        print(f"  Verified rows    : {', '.join(cause['citations'])}")
    if result.get("escalation"):
        print(f"  Escalated to pharmacist: {result['escalation'].get('reason', '')}")
    drill = result.get("fault_drill")
    if drill:
        print(f"  Fault drill ({drill.get('target')}): injected={drill.get('injected')} "
              f"caught={drill.get('caught')} recovered={drill.get('recovered')}")
    for d in result.get("dropped_claims", []) or []:
        print(f"  Dropped claim {d.get('hypothesis_id')}: {d.get('reason')}")

    ranked = result.get("ranked_hypotheses", [])
    if ranked:
        print("\n  Ranked Hypotheses:")
        for h in ranked:
            print(
                f"    [{h.get('likelihood','?').upper():6}] "
                f"{h.get('hypothesis_id','?')} {h.get('hypothesis_name','')}"
                f" — {h.get('verdict','?')}"
            )

    actions = result.get("approved_actions") or result.get("actions", [])
    if actions:
        print(f"\n  Proposed Actions ({len(actions)}):")
        for a in actions:
            flag = " [AMENDED]" if "pharmacist_amendment" in a else ""
            print(
                f"    {a.get('action_id','?')} [{a.get('priority','?').upper()}]{flag}"
                f" — {a.get('action','')}"
            )
            print(f"         Owner: {a.get('proposed_owner','')}  "
                  f"By: {a.get('timeframe','')}")
            if a.get("verified_citations"):
                print(f"         Rows : {', '.join(a['verified_citations'])}")

    rejected = result.get("rejected_actions", [])
    if rejected:
        print(f"\n  Rejected Actions: {len(rejected)}")

    strategist = result.get("steps", {}).get("action_strategist", {})
    comm = strategist.get("communication_draft", "")
    if comm:
        print("\n  Communication Draft:")
        for line in comm.strip().split("\n"):
            print(f"    {line}")

    print(f"\n  {result.get('medical_disclaimer', '')}")
    print(f"\n  Log: {result.get('log_file', 'N/A')}")
    print("="*60)


def _get_facilities() -> list:
    """Return sorted list of facility IDs from data/sample/facilities.csv."""
    import csv as _csv
    facilities_path = Path(__file__).parent / "data" / "sample" / "facilities.csv"
    if facilities_path.exists():
        with open(facilities_path, newline="") as f:
            reader = _csv.DictReader(f)
            return sorted({row["facility_id"] for row in reader if row.get("facility_id")})
    # Fallback: enumerate FAC-001..FAC-030
    return [f"FAC-{i:03d}" for i in range(1, 31)]


def _get_commodities() -> list:
    """Return sorted list of unique commodity names from data/sample/stock.csv."""
    import csv as _csv
    stock_path = Path(__file__).parent / "data" / "sample" / "stock.csv"
    if stock_path.exists():
        with open(stock_path, newline="") as f:
            reader = _csv.DictReader(f)
            seen = set()
            commodities = []
            for row in reader:
                c = row.get("commodity", "").strip()
                if c and c not in seen:
                    seen.add(c)
                    commodities.append(c)
            return sorted(commodities)
    return []


def _get_cases() -> list:
    """Return list of case dicts from data/cases/questions.csv."""
    import csv as _csv
    questions_path = Path(__file__).parent / "data" / "cases" / "questions.csv"
    if not questions_path.exists():
        return []
    with open(questions_path, newline="") as f:
        reader = _csv.DictReader(f)
        return [
            {
                "dataset": row["dataset"],
                "facility_id": row["facility_id"],
                "commodity": row["commodity"],
                "month": row["month"],
                "noise_level": row.get("noise_level", ""),
            }
            for row in reader
        ]


def _serve(port: int = 8000) -> None:
    """Start a minimal HTTP server exposing a /run endpoint and the frontend."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    print(f"StockyWhy HTTP server starting on port {port}...")
    print(f"  Frontend  : http://localhost:{port}/")
    print(f"  API       : POST http://localhost:{port}/run  "
          "{question} or {facility_id, commodity, month[, dataset]}")
    print(f"  Metadata  : GET  http://localhost:{port}/api/facilities|commodities|cases")
    print("Press Ctrl+C to stop.\n")

    _base_dir = Path(__file__).parent

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # suppress default access log
            pass

        def do_GET(self):
            path = self.path.split("?")[0]  # strip query string

            # ── Frontend index ─────────────────────────────────────
            if path in ("/", "/index.html"):
                index_path = _base_dir / "index.html"
                if index_path.exists():
                    body = index_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self._error(404, "index.html not found")
                return

            # ── Health check ───────────────────────────────────────
            if path == "/health":
                body = json.dumps({"status": "ok", "service": "stockywhy"}).encode()
                self._json_response(200, body)
                return

            # ── API: facilities ────────────────────────────────────
            if path == "/api/facilities":
                body = json.dumps({"facilities": _get_facilities()}).encode()
                self._json_response(200, body)
                return

            # ── API: commodities ───────────────────────────────────
            if path == "/api/commodities":
                body = json.dumps({"commodities": _get_commodities()}).encode()
                self._json_response(200, body)
                return

            # ── API: cases ─────────────────────────────────────────
            if path == "/api/cases":
                body = json.dumps({"cases": _get_cases()}).encode()
                self._json_response(200, body)
                return

            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            if self.path != "/run":
                self.send_response(404)
                self.end_headers()
                return

            try:
                length = int(self.headers.get("Content-Length", 0))
                if length > 64_000:
                    self._error(413, "Request too large")
                    return
                body = self.rfile.read(length)
                payload = json.loads(body)
            except Exception as exc:
                self._error(400, f"Invalid JSON: {str(exc).splitlines()[0]}")
                return

            try:
                result, code = execute_request(payload, interactive=False)
                self._json_response(code, json.dumps(result, default=str).encode())
            except Exception as exc:
                self._error(500, str(exc).splitlines()[0] if str(exc) else type(exc).__name__)

        def _json_response(self, code: int, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, code: int, msg: str) -> None:
            body = json.dumps({"error": msg}).encode()
            self._json_response(code, body)

    server = HTTPServer(("0.0.0.0", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


def _emit(result: dict, parsed) -> None:
    """Print the result (JSON only with --json) and write --output if asked."""
    if parsed.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_results(result)
    if parsed.output:
        out_path = Path(parsed.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
        if not parsed.json:
            print(f"\nFull result written to: {parsed.output}")


def main():
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

    sample_mode = os.environ.get("SAMPLE_MODE", "false").lower() == "true"

    # Build one request dict from --input, --case and the flags (flags win).
    payload = {}
    if parsed.input:
        try:
            with open(parsed.input, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError) as exc:
            result = _invalid(f"Could not read --input {parsed.input}: {str(exc).splitlines()[0]}")
            _emit(result, parsed)
            sys.exit(1)
        if not isinstance(payload, dict):
            _emit(_invalid("--input must hold a JSON object"), parsed)
            sys.exit(1)

    dataset = parsed.dataset or payload.get("dataset")
    facility_id = parsed.facility or payload.get("facility_id") or payload.get("facility")
    commodity = parsed.commodity or payload.get("commodity")
    month = parsed.month or payload.get("month")
    question = parsed.question or payload.get("question")

    if parsed.case:
        resolved = _resolve_case(parsed.case)
        dataset = dataset or resolved.get("dataset")
        facility_id = facility_id or resolved.get("facility_id")
        commodity = commodity or resolved.get("commodity")
        month = month or resolved.get("month")

    # Sample mode supplies the default dataset only; an explicit path is honoured.
    if sample_mode and not dataset:
        dataset = SAMPLE_DIR

    # Validate required args (a question can stand in for facility/commodity/month)
    missing = []
    if not dataset and not sample_mode and not question and not parsed.input:
        missing.append("--dataset")
    if not question:
        if not facility_id:
            missing.append("--facility")
        if not commodity:
            missing.append("--commodity")
        if not month:
            missing.append("--month")

    if missing:
        message = f"missing required arguments: {', '.join(missing)}"
        if parsed.json:
            _emit(_invalid(message), parsed)
        else:
            print(f"\nError: {message}")
            print("\nRun 'python run.py help' for usage examples.")
        sys.exit(1)

    request = {"dataset": dataset, "facility_id": facility_id, "commodity": commodity,
               "month": month, "question": question,
               "role": payload.get("role") or parsed.role}
    interactive = not parsed.no_review and not parsed.json

    # Run the investigation. With --json, progress output goes to stderr.
    try:
        quiet = contextlib.redirect_stdout(sys.stderr) if parsed.json else contextlib.nullcontext()
        with quiet:
            result, _ = execute_request(request, interactive=interactive, log_file=parsed.log_file)
    except KeyboardInterrupt:
        print("\nInvestigation cancelled.", file=sys.stderr)
        sys.exit(0)
    except Exception as exc:
        result = {"status": "error", "error": f"StockyWhy failed: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}",
                  "hint": "Run with PYTHONTRACEBACK=1 for details."}
        if os.environ.get("PYTHONTRACEBACK"):
            raise

    _emit(result, parsed)
    code = exit_code(result)
    if code:
        sys.exit(code)


if __name__ == "__main__":
    main()
