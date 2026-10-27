"""
tests/test_run.py

run.py runtime: question parsing (Swahili months, conflicts), --case
resolution, the HTTP server (/health, dataset restriction, body checks,
/api/review), result printing for newer result fields, and UTF-8 output.
No network beyond 127.0.0.1.
"""

import http.client
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import run  # noqa: E402

SAMPLE_DIR = str(ROOT / "data" / "sample")


class FakeAgent:
    def __init__(self):
        self.calls = []

    def run(self, **kw):
        self.calls.append(kw)
        return {"status": "complete", **kw}


# -- parsing ------------------------------------------------------------------

def test_swahili_month_question():
    out = run.parse_question("Kwa nini FAC-009 iliishiwa na magnesium sulphate mwezi Machi 2026?",
                             SAMPLE_DIR)
    assert out == {"facility_id": "FAC-009", "commodity": "magnesium sulphate inj", "month": "2026-03"}


def test_question_conflicting_with_fields_clarifies():
    agent = FakeAgent()
    q = "Why did FAC-009 run out of magnesium sulphate in March 2026?"
    result, code = run.execute_request({"question": q, "facility_id": "FAC-011"}, agent=agent)
    assert code == 200 and result["status"] == "clarify" and "facility_id" in result["conflicts"]
    result, _ = run.execute_request({"question": q, "month": "2026-02"}, agent=agent)
    assert result["status"] == "clarify" and "month" in result["conflicts"]
    assert agent.calls == []
    # Agreeing fields are fine (case and sulfate/sulphate spelling ignored)
    result, _ = run.execute_request({"question": q, "facility_id": "fac-009",
                                     "commodity": "magnesium sulphate inj"}, agent=agent)
    assert result["status"] == "complete" and agent.calls[-1]["facility_id"] == "fac-009"


def test_fields_fill_what_the_question_lacks():
    agent = FakeAgent()
    result, _ = run.execute_request({"question": "Why did we run out of oxytocin in March 2026?",
                                     "facility_id": "FAC-016"}, agent=agent)
    assert result["status"] == "complete" and agent.calls[-1]["commodity"] == "oxytocin 10IU inj"


def test_resolve_case_from_other_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    got = run._resolve_case("data/cases/normal/case_01")
    assert got["facility_id"] == "FAC-011" and got["month"] == "2026-03"
    assert Path(got["dataset"]).is_dir()
    got = run._resolve_case("./data/cases/normal/case_1")  # no loose substring match
    assert got["facility_id"] is None


def test_refine_hint():
    r = run._refine_hint({"status": "error", "error": "Data Analyst failed: Could not reach Nightshift"})
    assert "Nightshift" in r["hint"] and "SAMPLE_MODE" in r["hint"]
    r = run._refine_hint({"status": "error", "error": "Data Reader failed: Zetaris returned HTTP 500"})
    assert "check_zetaris" in r["hint"]
    r = run._refine_hint({"status": "complete", "hint": "x"})
    assert r["hint"] == "x"


def test_offline_fallback(monkeypatch):
    for name in ("SAMPLE_MODE", "METERLESS_RUNTIME_TOKEN", "STOCKWHY_USE_LLM", "STOCKWHY_DATA_SOURCE"):
        monkeypatch.setenv(name, "x")  # records the original value so it is restored
        monkeypatch.delenv(name)
    assert "sample mode" in run._offline_fallback()
    assert os.environ["SAMPLE_MODE"] == "true"
    monkeypatch.delenv("SAMPLE_MODE")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "real-looking-token")
    assert run._offline_fallback() == ""
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.delenv("METERLESS_RUNTIME_TOKEN")
    assert run._offline_fallback() == ""  # explicit SAMPLE_MODE is honoured


# -- printing -------------------------------------------------------------------

def test_print_newer_result_fields(capsys):
    run._print_results({"status": "no_stockout", "facility_id": "FAC-001",
                        "summary": "Closing stock never reached zero.", "citations": ["stock#1"]})
    out = capsys.readouterr().out
    assert "No stock-out" in out and "stock#1" in out
    run._print_results({
        "status": "complete", "most_likely_cause": "H2",
        "hypotheses_not_investigated": [{"id": "H4", "name": "payment_hold",
                                         "computed_verdict": "ruled_out", "rows": ["payments#3"]}],
        "approved_actions": [{"action_id": "A9", "type": "transfer_request", "priority": "high",
                              "source_facility": "FAC-004", "source_facility_name": "Kibera HC",
                              "units": 120, "distance_km": 6.5, "rule": "surplus beyond 1 month",
                              "citations": ["stock#7"], "requires_pharmacist_approval": True}],
    })
    out = capsys.readouterr().out
    assert "H4 payment_hold" in out and "TRANSFER REQUEST" in out
    assert "120 units from Kibera HC (FAC-004), 6.5 km" in out and "stock#7" in out


# -- HTTP server ----------------------------------------------------------------

class FakeMemory:
    def __init__(self):
        self.calls = []

    def feedback(self, memory_id, decision, note="", action_decisions=None):
        if memory_id == "missing":
            raise KeyError(memory_id)
        self.calls.append((memory_id, decision, note, action_decisions))
        return {"id": memory_id, "status": decision}


def test_review_request_validation():
    mem = FakeMemory()
    body, code = run.review_request({"memory_id": "abc123", "decision": "partial", "note": "n",
                                     "action_decisions": {"A1": "accepted", "A2": "rejected"}}, mem)
    assert code == 200 and body == {"ok": True, "memory_id": "abc123", "status": "partial"}
    assert mem.calls[0][3] == {"A1": "accepted", "A2": "rejected"}
    assert run.review_request({"memory_id": "abc", "decision": "maybe"}, mem)[1] == 400
    assert run.review_request({"memory_id": "../x", "decision": "approved"}, mem)[1] == 400
    assert run.review_request({"memory_id": "abc", "decision": "approved",
                               "action_decisions": {"A1": "yes"}}, mem)[1] == 400
    assert run.review_request({"memory_id": "missing", "decision": "approved"}, mem)[1] == 404


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCKWHY_MEMORY_PATH", str(tmp_path / "hmem.json"))
    srv = run.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _request(srv, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=10)
    data = json.dumps(body).encode() if body is not None and not isinstance(body, bytes) else body
    conn.request(method, path, body=data, headers=headers or {})
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return resp.status, (json.loads(raw) if raw and raw[:1] in b"{[" else raw)


def test_server_basics(server):
    assert server.server_address[0] == "127.0.0.1"
    assert type(server).__name__ == "ThreadingHTTPServer"
    status, body = _request(server, "GET", "/health")
    assert status == 200 and body["service"] == "stockwhy"
    status, body = _request(server, "POST", "/run",
                            {"facility_id": "FAC-011", "commodity": "ORS sachet", "month": "2026-03",
                             "dataset": "../../etc"})
    assert status == 400 and "etc" not in json.dumps(body)
    status, body = _request(server, "POST", "/run",
                            {"facility_id": "FAC-011", "commodity": "ORS sachet", "month": "2026-03",
                             "dataset": "/tmp"})
    assert status == 400
    status, body = _request(server, "POST", "/run", b"{}", {"Content-Length": "-5"})
    assert status == 400
    status, body = _request(server, "POST", "/api/review",
                            {"memory_id": "nope", "decision": "approved"})
    assert status == 404 and body["ok"] is False


def test_safe_dataset():
    assert run._safe_dataset("data/sample") == str((ROOT / "data" / "sample").resolve())
    assert run._safe_dataset("data/../run.py") is None
    assert run._safe_dataset(str(ROOT)) is None


def test_review_round_trip_through_case_memory(server, tmp_path):
    from engines.hmem import CaseMemory
    mem = CaseMemory(tmp_path / "hmem.json")
    mid = mem.store({"facility_id": "FAC-011", "commodity": "ORS sachet", "month": "2026-03",
                     "cause": "H2 supplier_underfill"}, ["orders#1505"], run_id="r1")
    status, body = _request(server, "POST", "/api/review",
                            {"memory_id": mid, "decision": "approved", "note": "agree"})
    assert status == 200 and body == {"ok": True, "memory_id": mid, "status": "approved"}
    assert CaseMemory(tmp_path / "hmem.json").get(mid)["status"] == "approved"


# -- encoding ----------------------------------------------------------------------

def test_cli_survives_cp1252_redirected_output(tmp_path):
    env = {k: v for k, v in os.environ.items()
           if k not in ("METERLESS_RUNTIME_TOKEN", "STOCKWHY_DATA_SOURCE", "METERLESS_BASE_URL")}
    env.update(SAMPLE_MODE="true", PYTHONIOENCODING="cp1252", STOCKWHY_LOGS_DIR=str(tmp_path),
               STOCKWHY_MEMORY_PATH=str(tmp_path / "hmem.json"))
    out = tmp_path / "out.txt"
    with open(out, "w", encoding="utf-8") as fh:
        proc = subprocess.run([sys.executable, str(ROOT / "run.py"), "--facility", "FAC-011",
                               "--commodity", "ORS sachet", "--month", "2026-03", "--no-review"],
                              stdout=fh, stderr=subprocess.PIPE, env=env, cwd=str(tmp_path), timeout=120)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-500:]
    assert "STOCKWHY INVESTIGATION RESULTS" in out.read_text(encoding="utf-8")
