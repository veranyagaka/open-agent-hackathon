"""
tests/test_zetaris_client.py

Zetaris REST client (scripts/check_zetaris.py) and response-shape handling in
tools/data_loader.py: headerless and upper-case rows, optional facility
columns, timeout setting and one retry on 5xx. Local 127.0.0.1 servers only.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import check_zetaris  # noqa: E402
from tools import data_loader  # noqa: E402


def test_rows_shapes():
    cols = ["id", "month"]
    assert data_loader._zetaris_rows({"data": [["1", "2026-03"]]}, cols) == [{"id": "1", "month": "2026-03"}]
    assert data_loader._zetaris_rows({"data": [["1", "x"]], "headers": ["ID", "MONTH"]}) == \
        [{"id": "1", "month": "x"}]
    assert data_loader._zetaris_rows({"data": [{"ID": "1"}]}) == [{"id": "1"}]
    with pytest.raises(RuntimeError):
        data_loader._zetaris_rows({"data": [["1"]]}, cols)  # width mismatch
    with pytest.raises(RuntimeError):
        data_loader._zetaris_rows({"data": [["1", "x"]]})  # no names at all


def test_optional_facility_columns_kept(monkeypatch):
    calls = []

    def run_sql(sql, limit=100):
        calls.append(sql)
        cols = sql.split("SELECT ", 1)[1].split(" FROM", 1)[0].split(", ")
        if "facilities" in sql:
            return {"data": [["FAC-009", "-1.3", "38.0", "Katutu Dispensary", "dispensary",
                              "Kitui", "Kitui Central", "n123"]]}
        if "web_notes" in sql:
            return {"data": []}
        if "payments" in sql:
            return {"data": [["1", "2026-03", "0", "0"]]}
        return {"data": [], "headers": cols}

    monkeypatch.setattr("scripts.check_zetaris.run_sql", run_sql)
    ds = data_loader.load_zetaris_dataset(str(ROOT / "data" / "sample"), "FAC-009",
                                          "magnesium sulphate inj", "2026-03")
    fac = ds["facilities"]
    assert fac.loc[0, "facility_name"] == "Katutu Dispensary" and fac.loc[0, "county"] == "Kitui"
    assert not any("SELECT *" in sql for sql in calls)


class _Server:
    def __init__(self, responses):
        self.responses, self.count = list(responses), 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.count += 1
                code, body = outer.responses.pop(0)
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def zetaris_env(monkeypatch):
    monkeypatch.setattr(check_zetaris, "RETRY_PAUSE_S", 0)
    monkeypatch.setenv("ZETARIS_API_KEY", "test-key")
    monkeypatch.setenv("ZETARIS_ORG_ID", "1")

    def start(*responses):
        srv = _Server(responses)
        monkeypatch.setenv("ZETARIS_REST_URL", f"http://127.0.0.1:{srv.httpd.server_port}/api/v1.0")
        return srv
    return start


def test_run_sql_retries_once_on_5xx(zetaris_env):
    srv = zetaris_env((503, {"error": "busy"}), (200, {"data": [["1"]]}))
    try:
        assert check_zetaris.run_sql("SELECT 1") == {"data": [["1"]]}
        assert srv.count == 2
    finally:
        srv.close()


def test_run_sql_gives_up_after_one_retry_and_skips_4xx(zetaris_env):
    srv = zetaris_env((500, {"e": 1}), (502, {"e": 2}), (400, {"e": 3}))
    try:
        with pytest.raises(RuntimeError, match="HTTP 502"):
            check_zetaris.run_sql("SELECT 1")
        with pytest.raises(RuntimeError, match="HTTP 400"):
            check_zetaris.run_sql("SELECT 1")
        assert srv.count == 3
    finally:
        srv.close()


def test_timeout_setting(monkeypatch):
    monkeypatch.delenv("ZETARIS_TIMEOUT_S", raising=False)
    assert check_zetaris._timeout() == 120.0
    monkeypatch.setenv("ZETARIS_TIMEOUT_S", "30")
    assert check_zetaris._timeout() == 30.0
    monkeypatch.setenv("ZETARIS_TIMEOUT_S", "abc")
    assert check_zetaris._timeout() == 120.0
