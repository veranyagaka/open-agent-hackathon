"""Live data setup: load Postgres, register both sources in Zetaris, verify a federated query.

  docker compose up -d                       # stockwhy-pg, seeded from data/sample/
  python scripts/setup_live.py --skip-load   # register + verify (the container loaded the data)
  python scripts/setup_live.py               # load with psql too, for a Postgres you run yourself
  python scripts/setup_live.py --verify-only # checks only

Reads .env: PG_HOST, PG_PORT (5432), PG_USER, PG_PASSWORD, PG_DATABASE (stockwhy),
PG_WEB_DATABASE (stockwhy_web), PG_JDBC_PARAMS (e.g. ?sslmode=require), PG_ZETARIS_HOST /
PG_ZETARIS_PORT (the address Zetaris uses to reach Postgres, when it differs from this machine's;
with docker-compose.yml: stockwhy-pg / 5432; PG_ZETARIS_PORT defaults to 5432 when PG_ZETARIS_HOST is set), ZETARIS_SCHEMA (stockwhy_pg),
ZETARIS_WEB_SCHEMA (stockwhy_web), plus ZETARIS_REST_URL / ZETARIS_API_KEY / ZETARIS_ORG_ID.

Zetaris then holds one dataset, data/sample (the demo county): stock, orders, payments and
facilities in datasource stockwhy_pg, public notices in datasource stockwhy_web.
Loading needs the `psql` client on PATH. Never prints passwords or keys. One SQL statement
per Zetaris call. A statement that fails because the source already exists is reported as
"already registered"; any other failure is printed with its error and makes the script exit 1.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from scripts.check_zetaris import run_sql  # noqa: E402
from tools.data_loader import _zetaris_rows  # noqa: E402

SAMPLE = ROOT / "data" / "sample"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _redact(text: str) -> str:
    """Remove anything secret from a message before it is printed."""
    for name in ("PG_PASSWORD", "ZETARIS_API_KEY"):
        secret = os.environ.get(name, "")
        if secret:
            text = text.replace(secret, "***")
    return re.sub(r'password\s+"[^"]*"', 'password "***"', text, flags=re.I)


def query(sql: str, columns: list = None) -> list:
    """Rows as dicts with lower-case keys; headerless rows are zipped against *columns*."""
    return _zetaris_rows(run_sql(sql, limit=1000), columns)


_EXISTS = re.compile(r"already\s+exists|already\s+registered|duplicate", re.I)


def load_postgres() -> bool:
    if not shutil.which("psql"):
        print("psql not found: install the Postgres client, or load data/sample/*.sql another way "
              "and use --skip-load")
        return False
    base = {"PGHOST": env("PG_HOST", "localhost"), "PGPORT": env("PG_PORT", "5432"),
            "PGUSER": env("PG_USER"), "PGPASSWORD": os.environ.get("PG_PASSWORD", "")}
    for db, script in ((env("PG_DATABASE", "stockwhy"), "postgres_load.sql"),
                       (env("PG_WEB_DATABASE", "stockwhy_web"), "web_notes_load.sql")):
        subprocess.run(["psql", "-v", "ON_ERROR_STOP=0", "-d", "postgres", "-c", f'CREATE DATABASE "{db}"'],
                       env={**os.environ, **base}, capture_output=True)
        r = subprocess.run(["psql", "-v", "ON_ERROR_STOP=1", "-q", "-d", db, "-f", str(SAMPLE / script)],
                           env={**os.environ, **base}, capture_output=True, text=True)
        status = "ok" if r.returncode == 0 else "FAILED: " + _redact(r.stderr.strip()[:300])
        print(f"load {script} -> {db}: {status}")
        if r.returncode:
            return False
    return True


def register() -> bool:
    """Run data/sample/zetaris_register.sql with the placeholders filled from .env."""
    template = (SAMPLE / "zetaris_register.sql").read_text(encoding="utf-8")
    values = {
        "PG_HOST": env("PG_ZETARIS_HOST") or env("PG_HOST", "localhost"),
        "PG_PORT": env("PG_ZETARIS_PORT") or ("5432" if env("PG_ZETARIS_HOST") else env("PG_PORT", "5432")),
        "PG_USER": env("PG_USER"),
        "PG_PASSWORD": os.environ.get("PG_PASSWORD", ""),
        "PG_DATABASE": env("PG_DATABASE", "stockwhy"),
        "PG_WEB_DATABASE": env("PG_WEB_DATABASE", "stockwhy_web"),
        "PG_JDBC_PARAMS": env("PG_JDBC_PARAMS"),
    }
    for name, value in values.items():
        if name != "PG_JDBC_PARAMS" and '"' in value:
            raise SystemExit(f"{name} must not contain a double quote")
    body = "\n".join(line for line in template.splitlines() if not line.strip().startswith("--"))
    ok = True
    for stmt in [s.strip() for s in body.split(";") if s.strip()]:
        sql = re.sub(r"\{(\w+)\}", lambda m: values[m.group(1)], stmt)
        label = stmt.split("(")[0].split(" OPTIONS")[0].split(" DESCRIBE")[0][:70]
        try:
            run_sql(sql, limit=10)
            print(f"zetaris: {label} ... ok")
        except RuntimeError as exc:
            message = _redact(str(exc))
            if _EXISTS.search(message):
                print(f"zetaris: {label} ... already registered, kept")
            else:
                ok = False
                print(f"zetaris: {label} ... FAILED: {message[:300]}")
    return ok


def verify() -> bool:
    pg = env("ZETARIS_SCHEMA", "stockwhy_pg")
    web = env("ZETARIS_WEB_SCHEMA", "stockwhy_web")
    checks = [
        ("stock rows (expect 4320)", f"SELECT COUNT(*) AS n FROM {pg}.stock", "4320"),
        ("orders rows (expect 4320)", f"SELECT COUNT(*) AS n FROM {pg}.orders", "4320"),
        ("payments rows (expect 24)", f"SELECT COUNT(*) AS n FROM {pg}.payments", "24"),
        ("facilities rows (expect 30)", f"SELECT COUNT(*) AS n FROM {pg}.facilities", "30"),
        ("public notices (expect 2)", f"SELECT COUNT(*) AS n FROM {web}.web_notes", "2"),
        ("federated join stockwhy_pg x stockwhy_web (expect 2)",
         f"SELECT COUNT(*) AS n FROM {web}.web_notes n JOIN "
         f"(SELECT DISTINCT commodity FROM {pg}.orders) o ON o.commodity = n.commodity", "2"),
    ]
    ok = True
    for name, sql, expected in checks:
        start = time.monotonic()
        try:
            rows = query(sql, ["n"])
            got = str(rows[0].get("n")) if rows else None
            if got is not None and re.fullmatch(r"-?\d+\.0+", got):
                got = got.split(".")[0]
            ms = round((time.monotonic() - start) * 1000)
            good = got == expected
            ok &= good
            print(f"verify {name}: {got} {'ok' if good else 'MISMATCH'} ({ms} ms)")
        except RuntimeError as exc:
            ok = False
            print(f"verify {name}: FAILED ({_redact(str(exc))[:200]})")
    try:
        row = query(f"SELECT opening, consumed, closing FROM {pg}.stock WHERE id = 1",
                    ["opening", "consumed", "closing"])[0]
        got = tuple(round(float(row[k])) for k in ("opening", "consumed", "closing"))
        good = got == (900, 377, 523)
        ok &= good
        print(f"verify stock#1 opening/consumed/closing: {got} {'ok' if good else 'MISMATCH'}")
    except (RuntimeError, IndexError, KeyError, ValueError) as exc:
        ok = False
        print(f"verify stock#1: FAILED ({_redact(str(exc))[:200]})")
    return ok


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print(__doc__.strip())
        return 0
    load_dotenv(ROOT / ".env")
    if not os.environ.get("ZETARIS_API_KEY"):
        print("Set ZETARIS_API_KEY in .env first (Zetaris: Management > API Tokens).")
        return 1
    args = set(sys.argv[1:])
    if "--verify-only" not in args:
        if "--skip-load" not in args and not load_postgres():
            return 1
        registered = register()
        verified = verify()
        if not registered:
            print("Some Zetaris registrations failed (see FAILED above).")
        return 0 if registered and verified else 1
    return 0 if verify() else 1


if __name__ == "__main__":
    sys.exit(main())
