BANNER = r"""
  ____  _             _         __        ___
 / ___|| |_ ___   ___| | ___   / / /\  /\/ _ \ _   _
 \___ \| __/ _ \ / __| |/ / | | / / /_/ / /_)/ | | |
  ___) | || (_) | (__|   <| |_| / /__/ / ___/| |_| |
 |____/ \__\___/ \___|_|\_\\__, \____/\/     \__, |
                            |___/             |___/

           S T O C K Y W H Y
     Drug Stockout Investigation System
"""


def show_help():
    print(BANNER)
    print("StockyWhy — Investigate drug stockouts in health facilities.")
    print("Uses AI agents + deterministic data analysis to identify root causes.")

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
    print("  SAMPLE_MODE=true python run.py --facility FAC-011 "
          "--commodity 'ORS sachet' --month 2026-03")

    print("\nOPTIONS")
    print("  help                   Show this help screen")
    print("  --dataset PATH         Dataset directory (CSV/JSON files)")
    print("  --facility ID          Facility ID, e.g. FAC-011")
    print("  --commodity NAME       Medicine name, e.g. 'ORS sachet'")
    print("  --month YYYY-MM        Reporting month, e.g. 2026-03")
    print("  --case PATH            Run a case from data/cases/ or questions.csv")
    print("  --serve                Start HTTP server on port 8000 (/run endpoint)")
    print("  --no-review            Skip pharmacist review step")
    print("  --output PATH          Write full JSON result to file")
    print("  --log-file NAME        JSONL log filename (written to logs/)")

    print("\nENVIRONMENT VARIABLES")
    print("  GROQ_API_KEY           Your Groq API key (required)")
    print("  GROQ_MODEL             LLM model name (default: set in .env)")
    print("  SAMPLE_MODE=true       Use data/sample/ as dataset automatically")

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
    print("  StockyWhy NEVER executes orders, transfers, or payments autonomously.")

    print("\nStockyWhy | Open Agent Hackathon 2026")
