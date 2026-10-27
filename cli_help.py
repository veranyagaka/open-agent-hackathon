BANNER = r"""
  ____  _             _    __        ___           
 / ___|| |_ ___   ___| | __\ \      / / |__  _   _ 
 \___ \| __/ _ \ / __| |/ / \ \ /\ / /| '_ \| | | |
  ___) | || (_) | (__|   <   \ V  V / | | | | |_| |
 |____/ \__\___/ \___|_|\_\   \_/\_/  |_| |_|\__, |
                                             |___/ 

           S T O C K W H Y
     Drug Stockout Investigation System
"""


def show_help():
    print(BANNER)
    print("StockWhy — Investigate drug stockouts in health facilities.")
    print("Agents investigate, an Evaluator re-checks every cited row, and only")
    print("verified causes reach the pharmacist, who approves any action.")

    print("\nUSAGE")
    print("  python run.py help")
    print("  python run.py [OPTIONS]")
    print("  python run.py --serve")

    print("\nQUICK START")
    print(
        "  python run.py --dataset data/sample "
        "--facility FAC-011 --commodity 'ORS sachet' --month 2026-03"
    )
    print("  python run.py --case data/cases/normal/case_01")
    print('  python run.py --question "Why did FAC-009 run out of magnesium '
          'sulphate in March 2026?"')
    print("  python run.py --input request.json --json")
    print("  SAMPLE_MODE=true python run.py --facility FAC-011 "
          "--commodity 'ORS sachet' --month 2026-03")

    print("\nOPTIONS")
    print("  help                   Show this help screen")
    print("  --dataset PATH         Dataset directory (CSV/JSON files)")
    print("  --facility ID          Facility ID, e.g. FAC-011")
    print("  --commodity NAME       Medicine name, e.g. 'ORS sachet'")
    print("  --month YYYY-MM        Reporting month, e.g. 2026-03")
    print("  --case PATH            Run a case from data/cases/ or questions.csv")
    print("  --serve                Start the web UI and HTTP API (/run, /api/review)")
    print("  --host HOST            Address for --serve (default 127.0.0.1)")
    print("  --port PORT            Port for --serve (default 8000)")
    print("  --no-review            Skip pharmacist review step")
    print("  --output PATH          Write full JSON result to file")
    print("  --log-file NAME        JSONL log filename (written to logs/)")
    print('  --question TEXT        Plain question; facility, month and medicine are')
    print("                         read from it (ambiguous -> a clarify result)")
    print("  --input FILE.json      JSON request: {question} or {facility_id, commodity,")
    print("                         month}, optional dataset and role")
    print("  --json                 Print only the JSON result (no prompts)")
    print("  --role NAME            Who is asking (default: pharmacist)")

    print("\nHOW AN INVESTIGATION RUNS")
    print("  Scout gate -> memory recall -> Data Reader -> Data Analyst -> Theory Generator")
    print("  -> Investigators (wave 1: hypotheses with a signal or a prior finding)")
    print("  -> Evaluator: re-reads every cited row, checks verdicts against the flags,")
    print("     cross-checks hypotheses; a failed investigator re-runs once with the critique;")
    print("     unverified claims are dropped; no cause yet -> wave 2; still none ->")
    print("     'insufficient evidence', escalated to the pharmacist")
    print("  -> Action Strategist (drafts only) -> memory (pending approval) -> pharmacist")

    print("\nHTTP (--serve)")
    print("  GET  /                 Web page")
    print("  GET  /health, /api/facilities, /api/commodities, /api/cases")
    print("  POST /run              Same JSON as --input; returns the same result")
    print("  POST /api/review       {memory_id, decision: approved|rejected|partial, note?}")

    print("\nEXIT CODES")
    print("  0  complete, clarify, refuse, block or insufficient evidence")
    print("  1  system or data error (the JSON has 'error' and 'hint')")

    print("\nENVIRONMENT VARIABLES")
    print("  METERLESS_BASE_URL     Meterless Nightshift runtime URL (LLM mode)")
    print("  METERLESS_RUNTIME_TOKEN  Nightshift runtime token (LLM mode)")
    print("  METERLESS_MODEL_DEEP   Model lane, e.g. meterless/deep")
    print("  SAMPLE_MODE=true       Default dataset data/sample/; rule-based agents")
    print("  STOCKWHY_USE_LLM       true/false; overrides the SAMPLE_MODE default")
    print("  STOCKWHY_DATA_SOURCE   csv (default) or zetaris")
    print("  STOCKWHY_LOGS_DIR      Where JSONL traces go (default: logs)")
    print("  STOCKWHY_MEMORY_PATH   Case memory file (default: logs/memory/hmem.json)")
    print("  STOCKWHY_INJECT_FAULT  e.g. H4: corrupt one cited value on the first pass")
    print("                         (demo drill: the Evaluator catches it, the retry recovers)")

    print("\nHYPOTHESES INVESTIGATED")
    print("  H1  late_order          — Order placed after cutoff date")
    print("  H2  supplier_underfill  — Facility filled less than peer facilities")
    print("  H3  payment_arrears     — County owed ≥30M KES; supplier reduced deliveries")
    print("  H4  demand_surge        — Consumption >25% above 3-month average")
    print("  H5  record_error        — Stock identity equation broken; stockout implausible")
    print("  H6  expiry              — Large wastage write-off depleted usable stock")
    print("  H7  national_disruption — County-wide fill drop + public web notice")

    print("\nSAFETY")
    print("  All actions require pharmacist/supply-chain officer review.")
    print("  StockWhy NEVER executes orders, transfers, or payments autonomously.")

    print("\nStockWhy | Open Agent Hackathon 2026")
