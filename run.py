"""
run.py

StockWhy CLI entry point.

Three ways in, one result shape out:
  python run.py --facility FAC-011 --commodity "ORS sachet" --month 2026-03
  python run.py --question "Why did FAC-009 run out of magnesium sulphate in March 2026?"
  python run.py --input request.json --json
and POST /run on the --serve HTTP server (same JSON as --input);
POST /api/review records the pharmacist's decision in case memory.

Exit code is non-zero only for system or data errors (status "error").
A clarify / refuse / block / insufficient-evidence result exits 0.
"""

import argparse
import contextlib
import csv
import json
import os
import re
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DATA_ROOT = REPO_ROOT / "data"
SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sample")
QUESTIONS_CSV = DATA_ROOT / "cases" / "questions.csv"
_TRUE = {"1", "true", "yes", "on"}
PLACEHOLDER_TOKENS = {"replace_with_your_runtime_token"}


def _configure_stdio() -> None:
    """UTF-8 output everywhere (Windows consoles default to cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(REPO_ROOT / ".env")


def _offline_fallback() -> str:
    """
    No runtime token and SAMPLE_MODE unset: run rule-based instead of failing
    on every agent with "token is not set". Returns the notice to print, or "".
    """
    if os.environ.get("SAMPLE_MODE", "").strip():
        return ""
    if os.environ.get("STOCKWHY_USE_LLM", "").strip().lower() not in ("",) + tuple(_TRUE):
        return ""  # LLM explicitly off already: rule-based, nothing to say
    token = (os.environ.get("METERLESS_RUNTIME_TOKEN") or "").strip()
    if token and token not in PLACEHOLDER_TOKENS:
        return ""
    if os.environ.get("STOCKWHY_DATA_SOURCE", "csv").strip().lower() == "zetaris":
        os.environ["STOCKWHY_USE_LLM"] = "false"
        return ("Note: METERLESS_RUNTIME_TOKEN is not set, so the agents run rule-based "
                "(no LLM) on Zetaris data. Set the token to use Nightshift.")
    os.environ["SAMPLE_MODE"] = "true"
    return ("Note: METERLESS_RUNTIME_TOKEN is not set and SAMPLE_MODE is unset, so StockWhy "
            "runs in sample mode (data/sample, rule-based agents, no network). Set "
            "SAMPLE_MODE=true to silence this, or set the token to use Nightshift.")


def _reset_llm_budget() -> None:
    """Each run gets a fresh LLM call cap (STOCKWHY_MAX_LLM_CALLS)."""
    try:
        import llm_client
        llm_client.reset_call_budget()
    except Exception:
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stockwhy",
        description="StockWhy — Drug Stockout Investigation System",
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
            "  python run.py --serve --port 8000\n"
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
        help="Start the web UI and HTTP API (/run, /api/review)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Address for --serve (default 127.0.0.1; use 0.0.0.0 to expose on the network)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for --serve (default 8000)",
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


def _norm_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/").rstrip("/")


def _resolve_case(case_path: str) -> dict:
    """
    Resolve a --case argument to {dataset, facility_id, commodity, month}.

    Accepts a case directory path, or a dataset path listed in
    data/cases/questions.csv (exact match, or the same path seen from
    another directory, e.g. ./data/cases/normal/case_01). A listed case
    carries its facility, medicine and month; an unlisted directory needs
    --facility, --commodity and --month.
    """
    wanted = _norm_path(case_path)
    if QUESTIONS_CSV.exists():
        with open(QUESTIONS_CSV, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            listed = _norm_path(row.get("dataset"))
            if listed and (wanted == listed or wanted.endswith("/" + listed)
                           or _norm_path(str((REPO_ROOT / listed).resolve())) == _norm_path(
                               str(Path(case_path).resolve()))):
                dataset = case_path if Path(case_path).is_dir() else str(REPO_ROOT / listed)
                return {
                    "dataset": dataset,
                    "facility_id": row["facility_id"],
                    "commodity": row["commodity"],
                    "month": row["month"],
                }
    return {"dataset": case_path, "facility_id": None, "commodity": None, "month": None}


# ---------------------------------------------------------------------------
# Plain-language questions
# ---------------------------------------------------------------------------

try:  # one month table for English and Swahili, shared with Scout Intent
    from engines.scout_intent import MONTHS as _SCOUT_MONTHS
except Exception:  # pragma: no cover - Scout missing; English only
    import calendar as _calendar
    _SCOUT_MONTHS = {n.lower(): i for i, n in enumerate(_calendar.month_name) if n}
    _SCOUT_MONTHS.update({n.lower(): i for i, n in enumerate(_calendar.month_abbr) if n})
_MONTHS = dict(_SCOUT_MONTHS)
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


def _conflict_result(question: str, conflicts: dict, parsed: dict) -> dict:
    labels = {"facility_id": "facility", "commodity": "medicine", "month": "month"}
    parts = [f"the question says {labels[k]} {q!r} but the field says {f!r}"
             for k, (q, f) in conflicts.items()]
    message = "Please confirm: " + "; ".join(parts) + "."
    return {
        "status": "clarify",
        "question": question,
        "message": message,
        "error": f"Clarify: {message}",
        "hint": "Make the question and the facility/medicine/month fields agree, or send only one.",
        "missing": [],
        "conflicts": {k: {"question": q, "field": f} for k, (q, f) in conflicts.items()},
        "candidates": {},
        "parsed": parsed,
    }


def _same_value(key: str, a, b) -> bool:
    a, b = str(a or "").strip(), str(b or "").strip()
    if key == "commodity":
        return _norm(a) == _norm(b)
    return a.upper() == b.upper()


def _safe_dataset(dataset: str):
    """
    Resolve a dataset path sent over HTTP. It must sit under <repo>/data;
    returns the resolved path, or None for anything else.
    """
    try:
        candidate = Path(str(dataset))
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        resolved = candidate.resolve()
        return str(resolved) if resolved.is_relative_to(DATA_ROOT.resolve()) else None
    except (OSError, ValueError, RuntimeError):
        return None


_LLM_WORDS = ("nightshift", "meterless", "llm", "runtime_token", "language model")


def _refine_hint(result: dict) -> dict:
    """Replace a generic data hint with a Zetaris- or LLM-specific one."""
    if not isinstance(result, dict) or result.get("status") != "error":
        return result
    text = str(result.get("error") or "").lower()
    if any(word in text for word in _LLM_WORDS):
        result["hint"] = ("The LLM step failed. Check that Meterless Nightshift is running at "
                          "METERLESS_BASE_URL and METERLESS_RUNTIME_TOKEN is set, or run offline "
                          "with SAMPLE_MODE=true (rule-based agents).")
    elif "zetaris" in text or (
            os.environ.get("STOCKWHY_DATA_SOURCE", "csv").strip().lower() == "zetaris"
            and "data reader" in text):
        result["hint"] = ("Zetaris could not serve the data. Check ZETARIS_REST_URL, ZETARIS_API_KEY "
                          "and ZETARIS_ORG_ID, run `python scripts/check_zetaris.py`, and register "
                          "the datasources with `python scripts/setup_live.py`; or set "
                          "STOCKWHY_DATA_SOURCE=csv to read the CSV files.")
    return result


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
        "error": (f"Scout Intent {'blocked' if decision['decision'] == 'block' else 'refused'} "
                  f"the request: {decision.get('reason', '')}"),
        "hint": "Ask why a facility ran out of a medicine in a given month.",
        "scout": {k: v for k, v in decision.items() if k != "contract"},
    }


def execute_request(payload: dict, interactive: bool = False, log_file: str = None,
                    agent=None, restrict_dataset: bool = False) -> tuple:
    """
    Run one JSON request (shared by --input, --question and POST /run).

    payload: {"question"} or {"facility_id"/"facility", "commodity", "month"},
             plus optional "dataset" and "role".
    restrict_dataset: True for HTTP requests; "dataset" must then resolve
             under <repo>/data.
    Returns (result, http_status). http_status is 400 for a malformed request,
    otherwise 200 (the result's own "status" says what happened).
    """
    if not isinstance(payload, dict):
        return _invalid("Request must be a JSON object"), 400
    # Keys starting with "_" are comments in example files, never request data
    payload = {k: v for k, v in payload.items() if not str(k).startswith("_")}
    for key, value in payload.items():
        if value is not None and not isinstance(value, (str, int, float, bool)):
            return _invalid(f"Field '{key}' must be a plain value"), 400
        if isinstance(value, str) and len(value) > 500:
            return _invalid(f"Field '{key}' is too long"), 400

    dataset = payload.get("dataset") or None
    if dataset and restrict_dataset:
        dataset = _safe_dataset(dataset)
        if dataset is None:
            return _invalid("Field 'dataset' must be a folder under data/"), 400
    dataset = dataset or SAMPLE_DIR
    question = (payload.get("question") or "").strip() or None
    facility_id = payload.get("facility_id") or payload.get("facility")
    commodity = payload.get("commodity")
    month = payload.get("month")

    screened = _screen_request(payload)
    if screened is not None:
        return screened, 200

    if question:
        parsed = parse_question(question, dataset)
        explicit = {"facility_id": facility_id, "commodity": commodity, "month": month}
        bound = parsed.get("parsed", {}) if parsed.get("status") == "clarify" else parsed
        if parsed.get("status") == "clarify":
            need = {"facility": "facility_id", "year": "month", "month": "month",
                    "commodity": "commodity"}
            if not all(explicit[need[m]] for m in parsed.get("missing", []) if m in need):
                return _clarify_result(question, parsed), 200
        conflicts = {k: (bound[k], explicit[k]) for k in explicit
                     if explicit[k] and bound.get(k) and not _same_value(k, bound[k], explicit[k])}
        if conflicts:
            return _conflict_result(question, conflicts, bound), 200
        facility_id = facility_id or bound.get("facility_id")
        commodity = commodity or bound.get("commodity")
        month = month or bound.get("month")

    if not all([facility_id, commodity, month]):
        return _invalid("Required: question, or facility_id, commodity and month"), 400

    if agent is None:
        import orchestrator
        agent_cls = getattr(orchestrator, "StockWhy", None) or getattr(orchestrator, "StockyWhy")
        agent = agent_cls()
    _reset_llm_budget()
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
    return _refine_hint(result), 200


def exit_code(result: dict) -> int:
    """Non-zero only for system or data errors."""
    return 1 if result.get("status") in ("error", "invalid_request") else 0


def _facility_label(result: dict) -> str:
    """'Katutu Dispensary (FAC-009)' when the result carries a facility name, else the id."""
    fid = result.get("facility_id") or ""
    profile = ((result.get("steps") or {}).get("data_reader") or {}).get("_profile") or {}
    facility = profile.get("facility") if isinstance(profile.get("facility"), dict) else {}
    name = result.get("facility_name") or facility.get("facility_name")
    return f"{name} ({fid})" if name and fid else str(name or fid)


def _print_results(result: dict) -> None:
    """Print a nicely formatted summary of the investigation result."""
    print("\n" + "="*60)
    print("  STOCKWHY INVESTIGATION RESULTS")
    print("="*60)
    print(f"  Facility  : {_facility_label(result)}")
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

    if result.get("status") == "no_stockout":
        print(f"\n  No stock-out: {result.get('summary') or result.get('message') or ''}")
        cites = [str(c) for c in (result.get("citations") or [])]
        if cites:
            print(f"  Rows : {', '.join(cites)}")
        print(f"\n  Log: {result.get('log_file', 'N/A')}")
        print("="*60)
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

    skipped = result.get("hypotheses_not_investigated") or []
    if skipped:
        print("\n  Not investigated (rules already settled them):")
        for h in skipped:
            rows = ", ".join(str(r) for r in (h.get("rows") or [])[:6])
            print(f"    {h.get('id', '?')} {h.get('name', '')} — {h.get('computed_verdict', '?')}"
                  + (f" (rows {rows})" if rows else ""))

    actions = result.get("approved_actions") or result.get("actions", [])
    if actions:
        print(f"\n  Proposed Actions ({len(actions)}):")
        for a in actions:
            flag = " [AMENDED]" if "pharmacist_amendment" in a else ""
            priority = str(a.get("priority") or "?").upper()
            if a.get("type") == "transfer_request":
                source = a.get("source_facility_name") or a.get("source_facility", "?")
                if a.get("source_facility_name") and a.get("source_facility"):
                    source = f"{a['source_facility_name']} ({a['source_facility']})"
                distance = a.get("distance_km")
                print(f"    {a.get('action_id','?')} [{priority}] TRANSFER REQUEST{flag}"
                      f" — {a.get('units', '?')} units from {source}"
                      + (f", {distance} km" if distance is not None else ""))
                if a.get("rule"):
                    print(f"         Rule : {a['rule']}")
                cites = a.get("citations") or a.get("verified_citations") or []
                if cites:
                    print(f"         Rows : {', '.join(str(c) for c in cites)}")
                print("         Needs pharmacist approval before anyone moves stock.")
                continue
            print(
                f"    {a.get('action_id','?')} [{priority}]{flag}"
                f" — {a.get('action','')}"
            )
            print(f"         Owner: {a.get('proposed_owner','')}  "
                  f"By: {a.get('timeframe','')}")
            if a.get("verified_citations"):
                print(f"         Rows : {', '.join(a['verified_citations'])}")

    rejected = result.get("rejected_actions", [])
    if rejected:
        print(f"\n  Rejected Actions: {len(rejected)}")

    strategist = (result.get("steps") or {}).get("action_strategist") or {}
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
        with open(facilities_path, newline="", encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            return sorted({row["facility_id"] for row in reader if row.get("facility_id")})
    # Fallback: enumerate FAC-001..FAC-030
    return [f"FAC-{i:03d}" for i in range(1, 31)]


def _get_commodities() -> list:
    """Return sorted list of unique commodity names from data/sample/stock.csv."""
    import csv as _csv
    stock_path = Path(__file__).parent / "data" / "sample" / "stock.csv"
    if stock_path.exists():
        with open(stock_path, newline="", encoding="utf-8") as f:
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
    questions_path = QUESTIONS_CSV
    if not questions_path.exists():
        return []
    with open(questions_path, newline="", encoding="utf-8") as f:
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


_REVIEW_DECISIONS = ("approved", "rejected", "partial")
_ACTION_DECISIONS = ("accepted", "rejected")
MAX_BODY = 64_000
REQUEST_TIMEOUT_S = 30


def review_request(payload, memory=None) -> tuple:
    """
    POST /api/review: {memory_id, decision: approved|rejected|partial, note?,
    action_decisions?: {action_id: accepted|rejected}} -> ({ok, memory_id, status}, http_status).
    """
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Request must be a JSON object"}, 400
    memory_id = payload.get("memory_id")
    decision = payload.get("decision")
    note = payload.get("note") or ""
    actions = payload.get("action_decisions") or {}
    if not isinstance(memory_id, str) or not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", memory_id):
        return {"ok": False, "error": "memory_id must be the id from result.memory.stored_id"}, 400
    if decision not in _REVIEW_DECISIONS:
        return {"ok": False, "error": "decision must be approved, rejected or partial"}, 400
    if not isinstance(note, str) or len(note) > 500:
        return {"ok": False, "error": "note must be text of at most 500 characters"}, 400
    if not isinstance(actions, dict) or len(actions) > 50 or not all(
            isinstance(k, str) and len(k) <= 40 and v in _ACTION_DECISIONS for k, v in actions.items()):
        return {"ok": False, "error": "action_decisions must map action ids to accepted or rejected"}, 400
    if memory is None:
        from engines.hmem import CaseMemory
        memory = CaseMemory(os.environ.get("STOCKWHY_MEMORY_PATH", "logs/memory/hmem.json"))
    try:
        try:
            view = memory.feedback(memory_id, decision, note=note, action_decisions=actions or None)
        except TypeError:  # an older CaseMemory without action_decisions
            view = memory.feedback(memory_id, decision, note=note)
    except KeyError:
        return {"ok": False, "memory_id": memory_id, "error": "No stored finding with that memory_id"}, 404
    except ValueError as exc:
        return {"ok": False, "memory_id": memory_id, "error": str(exc).splitlines()[0]}, 400
    status = (view or {}).get("status") if isinstance(view, dict) else None
    return {"ok": True, "memory_id": memory_id, "status": status or decision}, 200


def make_server(host: str = "127.0.0.1", port: int = 8000):
    """Build the threaded HTTP server (the web UI, /run, /api/review and metadata)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    _base_dir = REPO_ROOT

    class Handler(BaseHTTPRequestHandler):
        timeout = REQUEST_TIMEOUT_S

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
                body = json.dumps({"status": "ok", "service": "stockwhy"}).encode()
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

            self._error(404, "Not found")

        def _read_json(self):
            """Parsed JSON body, or None after sending an error response."""
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                self._error(400, "Invalid Content-Length")
                return None
            if length < 0:
                self._error(400, "Invalid Content-Length")
                return None
            if length > MAX_BODY:
                self._error(413, "Request too large")
                return None
            try:
                return json.loads(self.rfile.read(length) or b"null")
            except Exception as exc:
                self._error(400, f"Invalid JSON: {str(exc).splitlines()[0]}")
                return None

        def do_POST(self):
            path = self.path.split("?")[0]
            if path not in ("/run", "/api/run", "/api/review"):
                self._error(404, "Not found")
                return
            payload = self._read_json()
            if payload is None:
                return
            try:
                if path == "/api/review":
                    result, code = review_request(payload)
                else:
                    result, code = execute_request(payload, interactive=False,
                                                   restrict_dataset=True)
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

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def _serve(port: int = 8000, host: str = "127.0.0.1") -> None:
    """Start the HTTP server exposing the frontend, /run and /api/review."""
    server = make_server(host, port)
    shown = "localhost" if host in ("127.0.0.1", "localhost") else host
    print(f"StockWhy HTTP server on {host}:{port}")
    print(f"  Frontend  : http://{shown}:{port}/")
    print(f"  API       : POST http://{shown}:{port}/run  "
          "{question} or {facility_id, commodity, month[, dataset under data/]}")
    print(f"  Review    : POST http://{shown}:{port}/api/review  "
          "{memory_id, decision: approved|rejected|partial[, note]}")
    print(f"  Metadata  : GET  http://{shown}:{port}/api/facilities|commodities|cases")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("  Warning   : listening beyond this machine; there is no login. Use only on a trusted network.")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


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
    _configure_stdio()
    _load_env()
    # Traces and case memory live in the repo, whatever directory run.py is started from.
    os.environ.setdefault("STOCKWHY_LOGS_DIR", str(REPO_ROOT / "logs"))
    os.environ.setdefault("STOCKWHY_MEMORY_PATH", str(REPO_ROOT / "logs" / "memory" / "hmem.json"))
    argv = sys.argv[1:]

    # Display the custom help screen for bare "help" command
    if argv == ["help"]:
        from cli_help import show_help
        show_help()
        return

    parser = build_parser()
    parsed = parser.parse_args(argv)

    notice = _offline_fallback()
    if notice:
        print(notice, file=sys.stderr)

    # --serve mode
    if parsed.serve:
        _serve(port=parsed.port, host=parsed.host)
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

    # A relative path that is not under the current directory is read from the repo.
    if dataset and not Path(dataset).exists() and (REPO_ROOT / dataset).exists():
        dataset = str(REPO_ROOT / dataset)

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
        result = _refine_hint({
            "status": "error",
            "error": f"StockWhy failed: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}",
            "hint": "Run with PYTHONTRACEBACK=1 for details."})
        if os.environ.get("PYTHONTRACEBACK"):
            raise

    _emit(result, parsed)
    code = exit_code(result)
    if code:
        sys.exit(code)


if __name__ == "__main__":
    main()
