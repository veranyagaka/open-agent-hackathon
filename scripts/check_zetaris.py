
"""Zetaris REST client used by tools/data_loader.py, plus a connectivity check.

    python scripts/check_zetaris.py

Reads ZETARIS_REST_URL, ZETARIS_API_KEY and ZETARIS_ORG_ID from the environment
(or .env). ZETARIS_TIMEOUT_S (default 120) is the per-request timeout; a 5xx
answer or a reset connection is retried once. Never prints the key.
"""

import http.client
import json
import os
import sys
import time
import uuid
import urllib.error
import urllib.request

DEFAULT_TIMEOUT_S = 120.0
RETRY_PAUSE_S = 1.0


def _timeout() -> float:
    try:
        return max(1.0, float(os.getenv("ZETARIS_TIMEOUT_S", "").strip() or DEFAULT_TIMEOUT_S))
    except ValueError:
        return DEFAULT_TIMEOUT_S


def _is_reset(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, (ConnectionResetError, ConnectionAbortedError,
                               http.client.RemoteDisconnected, BrokenPipeError))

from dotenv import load_dotenv


def run_sql(sql: str, limit: int = 100) -> dict:
    """Run ONE SQL statement through the Zetaris SQL Editor REST endpoint.

    *limit* caps the rows returned for this call.
    """
    load_dotenv()  # does not override variables already set
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
        "limit": int(limit),
    }

    timeout = _timeout()
    for attempt in (0, 1):
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
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            # Do not print request headers or credentials.
            body = exc.read().decode("utf-8", errors="replace")
            if 500 <= exc.code < 600 and attempt == 0:
                time.sleep(RETRY_PAUSE_S)
                continue
            raise RuntimeError(
                f"Zetaris returned HTTP {exc.code}: {body[:500]}"
            ) from None
        except (urllib.error.URLError, ConnectionError, http.client.HTTPException) as exc:
            if _is_reset(exc) and attempt == 0:
                time.sleep(RETRY_PAUSE_S)
                continue
            raise RuntimeError(
                f"Could not reach Zetaris: {getattr(exc, 'reason', exc)}"
            ) from None
        except TimeoutError:
            raise RuntimeError(
                f"Zetaris did not answer within {timeout:.0f}s (ZETARIS_TIMEOUT_S)"
            ) from None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError(f"Zetaris sent a non-JSON response: {raw[:120]!r}") from None
    raise RuntimeError("Zetaris request failed after one retry")  # pragma: no cover


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print(__doc__.strip())
        print("\nRuns SELECT 1 and SHOW LIGHTNING DATABASES; exits 1 if Zetaris is unreachable.")
        return
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
