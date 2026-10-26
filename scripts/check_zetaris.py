
import json
import os
import uuid
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()


def run_sql(sql: str) -> dict:
    base_url = os.getenv("ZETARIS_REST_URL", "").rstrip("/")
    api_key = os.getenv("ZETARIS_API_KEY", "")
    org_id = os.getenv("ZETARIS_ORG_ID", "")

    missing = [
        name
        for name, value in (
            ("ZETARIS_REST_URL", base_url),
            ("ZETARIS_API_KEY", api_key),
            ("ZETARIS_ORG_ID", org_id),
        )
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing required .env settings: " + ", ".join(missing)
        )

    payload = {
        "queryId": str(uuid.uuid4()),
        "sql": sql,
        "source": "SqlEditor",
        "limit": 100,
    }

    request = urllib.request.Request(
        f"{base_url}/sql-editor/sqls/run",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "X-Org-ID": org_id,
            "X-Request-ID": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Do not print request headers or credentials.
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Zetaris returned HTTP {exc.code}: {body[:500]}"
        ) from None
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Zetaris: {exc.reason}"
        ) from None


def main():
    print("Checking Zetaris connection...")

    try:
        result = run_sql("SELECT 1")
        rows = result.get("data") if isinstance(result, dict) else None
        print("SELECT 1 response:", rows)

        if not rows:
            print("Connection responded, but the expected data rows were absent.")
            print("Response keys:", list(result) if isinstance(result, dict) else type(result).__name__)
            return

        print("\nChecking accessible Lightning databases...")
        databases = run_sql("SHOW LIGHTNING DATABASES")
        print(json.dumps(databases.get("data", databases), indent=2)[:3000])

        print("\nZetaris connectivity check completed.")

    except Exception as exc:
        print(f"\nZetaris check failed: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
