"""
tests/test_engine_hmem.py

H-MEM (Meterless engine, engines/hmem.py):
  1. A Python port of the upstream conformance runner (engines/hmem/conformance/runner.ts), run on the official
     vectors in tests/fixtures/hmem_vectors.json.
  2. StockWhy case memory (CaseMemory): store -> recall -> feedback round trip, persistence and the audit ledger.
Deterministic: no LLM, no network.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.hmem import HMEM, CaseMemory

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "hmem_vectors.json").read_text())
T0 = VECTORS["clock"]
DAY = 86_400_000


def approx(a, b):
    return a is not None and abs(a - b) < 1e-9


def section(name):
    return pytest.mark.parametrize("case", VECTORS["sections"][name], ids=lambda c: c["id"])


# ---------------------------------------------------------------------------
# Official conformance vectors
# ---------------------------------------------------------------------------

def test_vectors_are_the_official_set():
    assert VECTORS["engine"] == "hmem"
    assert set(VECTORS["sections"]) >= {"record-validation", "feedback-deltas", "ranking-order", "sleep-guardrails",
                                        "conflict-gate", "ledger-audit", "dream-boundary"}


@section("record-validation")
def test_record_validation(case):
    h = HMEM(clock=lambda: T0)
    try:
        h.add({"content": case["input"]["content"], "source": case["input"]["source"]})
        got = "accept"
    except ValueError:
        got = "reject"
    assert got == case["expect"]


@section("feedback-deltas")
def test_feedback_deltas(case):
    h = HMEM(clock=lambda: T0)
    m = h.add({"content": "feedback target record", "confidence": case["start"], "source": "conformance"})
    before = m["accessCount"]
    h.feedback(m["id"], case["kind"])
    after = h.store.get(m["id"])
    assert approx(after["confidence"], case["expectConfidence"])
    if "expectAccessDelta" in case:
        assert after["accessCount"] - before == case["expectAccessDelta"]
    if "expectTag" in case:
        assert case["expectTag"] in after["tags"]


@section("ranking-order")
def test_ranking_order(case):
    h = HMEM(clock=lambda: T0)
    by = {r["key"]: h.add({"content": r["content"], "confidence": r["confidence"], "layer": r["layer"],
                           "source": "conformance"}) for r in case["records"]}
    for r in case["records"]:
        if r.get("supersededByKey"):
            by[r["key"]]["supersededBy"] = by[r["supersededByKey"]]["id"]
    order = [s["memory"]["id"] for s in h.query(case["query"], {"threshold": 0, "topN": 10})["memories"]]
    expected = [by[k]["id"] for k in case["expectOrder"]]
    for a, b in zip(expected, expected[1:]):
        assert order.index(a) < order.index(b)


@section("sleep-guardrails")
def test_sleep_guardrails(case):
    now = [T0]
    h = HMEM(clock=lambda: now[0])
    by = {r["key"]: h.add({"content": r["content"], "source": r["source"], "derivedFrom": r.get("derivedFrom")})
          for r in case["records"]}
    now[0] = T0 + case["ageDays"] * DAY
    before = sorted(m["id"] for m in h.store.all())
    preview = h.sleep.preview()
    assert sorted(m["id"] for m in h.store.all()) == before, "preview mutated the store"
    for k in case["expectArchived"]:
        assert by[k]["id"] in preview["toArchive"]
    for k in case["expectProtected"]:
        assert by[k]["id"] not in preview["toArchive"]
    report = h.sleep.execute(preview)
    for k in case["expectProtected"]:
        assert h.store.get(by[k]["id"]) is not None
    assert report["backupId"]


@section("conflict-gate")
def test_conflict_gate(case):
    h = HMEM(clock=lambda: T0)
    a = h.add({"content": case["a"]["content"], "confidence": case["a"]["confidence"], "source": "conformance"})
    b = h.add({"content": case["b"]["content"], "confidence": case["b"]["confidence"], "source": "conformance"})
    found = h.conflicts.scan()
    assert found
    outcome = h.conflicts.autoResolve(found[0])
    assert outcome in ("resolved", "queued")
    if outcome == "resolved":
        assert any(h.store.get(x["id"]).get("supersededBy") for x in (a, b))
    assert h.store.get(a["id"]) is not None
    assert h.store.get(b["id"]) is not None


@section("ledger-audit")
def test_ledger_audit(case):
    h = HMEM(clock=lambda: T0)
    m = h.add({"content": "audited record", "confidence": case["start"], "source": "conformance"})
    h.feedback(m["id"], case["kind"])
    hist = h.ledger.history(m["id"])
    assert [e["action"] for e in hist] == case["expectActions"]
    assert approx(hist[-1]["previousState"]["confidence"], case["expectPrev"])
    assert approx(hist[-1]["newState"]["confidence"], case["expectNew"])


@section("dream-boundary")
def test_dream_boundary(case):
    h = HMEM(clock=lambda: T0)
    for r in case["records"]:
        h.add({"content": r["content"], "type": r["type"], "source": "conformance"})
    n = len(h.store.all())
    proposals = h.dreaming.dream()
    assert proposals
    assert len(h.store.all()) == n, "dreaming materialised before approval"
    created = h.dreaming.approve(proposals[0]["id"])
    if created:
        assert created["layer"] == "long_term"
        assert created["derivedFrom"]


# ---------------------------------------------------------------------------
# StockWhy case memory
# ---------------------------------------------------------------------------

FINDING = {"facility_id": "FAC-016", "commodity": "oxytocin 10IU inj", "month": "2026-03",
           "cause": "h1_late_order", "summary": "February order placed after the cutoff; delivery slipped a month.",
           "confidence": 0.8}
CITES = ["orders#3161", "stock#1506"]


def test_case_memory_round_trip(tmp_path):
    path = tmp_path / "memory" / "hmem.json"
    mem = CaseMemory(path)
    assert mem.recall("FAC-016", "oxytocin 10IU inj") == []

    mid = mem.store(FINDING, CITES, run_id="run-abc")
    got = mem.recall("FAC-016", "oxytocin 10IU inj")
    assert [g["id"] for g in got] == [mid]
    g = got[0]
    assert g["status"] == "pending_approval"
    assert g["cause"] == "h1_late_order"
    assert g["month"] == "2026-03"
    assert g["citations"] == CITES
    assert g["provenance"]["run_id"] == "run-abc"
    assert g["provenance"]["citations"] == CITES
    assert mem.recall("FAC-016", "zinc 20mg tab") == []
    assert mem.recall("FAC-001", "oxytocin 10IU inj") == []

    after = mem.feedback(mid, "approve", note="matches the delivery note")
    assert after["status"] == "approved"
    assert approx(after["confidence"], 0.85)  # H-MEM `helpful`: +0.05

    # Persisted: a new process sees the same memory and status.
    again = CaseMemory(path)
    g2 = again.recall("FAC-016", "oxytocin 10IU inj")[0]
    assert g2["id"] == mid and g2["status"] == "approved" and g2["note"] == "matches the delivery note"


def test_reject_feedback_lowers_confidence_and_flags_review(tmp_path):
    mem = CaseMemory(tmp_path / "hmem.json")
    mid = mem.store(FINDING, CITES, run_id="run-1")
    out = mem.feedback(mid, "reject", note="delivery was on time")
    assert out["status"] == "rejected"
    assert approx(out["confidence"], 0.6)  # H-MEM `wrong`: -0.20
    assert "review" in mem.h.store.get(mid)["tags"]
    with pytest.raises(ValueError):
        mem.feedback(mid, "maybe")
    with pytest.raises(KeyError):
        mem.feedback("no-such-id", "approve")


def test_recall_newest_first_and_limit(tmp_path):
    mem = CaseMemory(tmp_path / "hmem.json")
    ids = {}
    for month in ("2025-11", "2026-03", "2026-01"):
        ids[month] = mem.store({**FINDING, "month": month}, CITES, run_id=f"run-{month}")
    got = mem.recall("FAC-016", "oxytocin 10IU inj")
    assert [g["month"] for g in got] == ["2026-03", "2026-01", "2025-11"]
    assert len(mem.recall("FAC-016", "oxytocin 10IU inj", limit=2)) == 2


def test_store_requires_provenance(tmp_path):
    mem = CaseMemory(tmp_path / "hmem.json")
    with pytest.raises(ValueError):
        mem.store(FINDING, CITES, run_id="")
    with pytest.raises(ValueError):
        mem.store(FINDING, [], run_id="run-1")
    with pytest.raises(ValueError):
        mem.store({**FINDING, "cause": ""}, CITES, run_id="run-1")


def test_ledger_is_append_only_audit(tmp_path):
    mem = CaseMemory(tmp_path / "hmem.json")
    mid = mem.store(FINDING, CITES, run_id="run-1")
    mem.recall("FAC-016", "oxytocin 10IU inj")
    mem.feedback(mid, "approve")
    actions = [e["action"] for e in mem.ledger(mid)]
    assert actions == ["create", "read", "feedback", "update"]
    first = (tmp_path / "hmem.ledger.jsonl").read_text()
    mid2 = mem.store({**FINDING, "month": "2026-04"}, CITES, run_id="run-2")
    assert (tmp_path / "hmem.ledger.jsonl").read_text().startswith(first)  # earlier entries untouched
    update = mem.ledger(mid)[-1]
    assert update["previousState"] == {"status": "pending_approval"}
    assert update["newState"] == {"status": "approved"}
    assert update["actor"] == "pharmacist"
    assert mem.ledger(mid2)[0]["action"] == "create"
