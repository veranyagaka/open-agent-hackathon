"""
tests/test_agent_loop.py

End-to-end checks of the agent loop on the real sample and case data
(rule-based, no network): transfer drafts, the H4 demand self-correction,
citation scope, LLM fallbacks, the no-stock-out exit and the CLI review.
"""

import contextlib
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import orchestrator  # noqa: E402
from agents import evaluator, rules  # noqa: E402
from orchestrator import StockWhy  # noqa: E402
from tools.data_loader import load_dataset  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = str(ROOT / "data" / "sample")
CASE_04 = str(ROOT / "data" / "cases" / "normal" / "case_04")


class FakeMemory:
    def __init__(self):
        self.stored, self.feedbacks = [], []

    def recall(self, facility_id, commodity, limit=5):
        return []

    def store(self, finding, citations, run_id):
        self.stored.append((finding, citations))
        return "mem-1"

    def feedback(self, memory_id, decision, note=""):
        self.feedbacks.append((memory_id, decision))
        return {}


@pytest.fixture
def offline(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKWHY_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("STOCKWHY_USE_LLM", "false")
    monkeypatch.setenv("STOCKWHY_DATA_SOURCE", "csv")
    for var in ("SAMPLE_MODE", "STOCKWHY_INJECT_FAULT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    return tmp_path


def _run(dataset, facility, commodity, month, memory=None, **kw):
    agent = StockWhy(memory=memory or FakeMemory())
    with contextlib.redirect_stdout(io.StringIO()):
        return agent.run(dataset, facility, commodity, month, interactive=kw.pop("interactive", False),
                         **kw)


# ---------------------------------------------------------------------------
# Transfer draft
# ---------------------------------------------------------------------------

def test_transfer_candidate_is_computed_from_rows():
    data = load_dataset(SAMPLE)
    best = rules.transfer_candidates(data, "FAC-009", "magnesium sulphate inj", "2026-03")[0]
    assert best["source_facility"] == "FAC-024"
    assert best["units"] == 205
    assert best["distance_km"] > 0
    assert best["source_closing"] == 580
    assert best["source_avg_consumed_3m"] == pytest.approx(374.33, abs=0.01)
    assert len(best["history_rows"]) == 3
    assert "facilities#FAC-009" in best["citations"] and "facilities#FAC-024" in best["citations"]


def test_supply_cause_gets_verified_transfer_draft(offline):
    r = _run(SAMPLE, "FAC-009", "magnesium sulphate inj", "2026-03")
    assert r["verified_cause"]["hypothesis_id"] == "H1"
    transfers = [a for a in r["actions"] if a.get("type") == "transfer_request"]
    assert len(transfers) == 1
    t = transfers[0]
    assert t["source_facility"] == "FAC-024" and t["units"] == 205 and t["distance_km"] > 0
    assert t["requires_pharmacist_approval"] is True and t["pharmacist_review_required"] is True
    assert set(t["citations"]) == set(t["verified_citations"])
    assert "verify_transfer" in [e["action"] for e in r["trace"]]
    assert "FAC-009" in r["steps"]["action_strategist"]["emergency_requisition_memo"]


def test_demand_cause_gets_no_transfer(offline):
    r = _run(str(ROOT / "data/cases/normal/case_01"), "FAC-011", "ORS sachet", "2026-03")
    assert r["verified_cause"]["hypothesis_id"] == "H4"
    assert not [a for a in r["actions"] if a.get("type") == "transfer_request"]


def test_tampered_transfer_is_rejected():
    data = load_dataset(SAMPLE)
    best = rules.transfer_candidates(data, "FAC-009", "magnesium sulphate inj", "2026-03")[0]
    scope = {"facility_id": "FAC-009", "commodity": "magnesium sulphate inj", "month": "2026-03"}
    action = {"source_facility": best["source_facility"], "units": best["units"] + 50,
              "distance_km": best["distance_km"], "citations": best["citations"]}
    assert not evaluator.verify_transfer(action, data, scope)["ok"]
    action["units"] = best["units"]
    assert evaluator.verify_transfer(action, data, scope)["ok"]


# ---------------------------------------------------------------------------
# H4 demand self-correction (stock-out days with stock on hand)
# ---------------------------------------------------------------------------

def test_case_04_revises_stockout_adjusted_demand(offline):
    r = _run(CASE_04, "FAC-020", "zinc 20mg tab", "2026-03")
    acts = [e["action"] for e in r["trace"]]
    for name in ("record_check", "request_revision", "retry_investigation", "accept_revision"):
        assert name in acts
    revision = next(e for e in r["trace"] if e["action"] == "request_revision")
    assert "Record check shows stock was on hand" in revision["summary"]
    h4 = next(e for e in r["steps"]["evidence_investigator"]["evaluations"] if e["theory_id"] == "H4")
    assert h4["verdict"] == "weakened" and h4["demand_basis"] == "issues_only"
    assert "-9.23%" in h4["recomputed_after_critique"]
    assert r["verified_cause"]["hypothesis_id"] == "H5"


def test_normal_stockout_keeps_adjustment_without_revision(offline):
    # closing 0: stock really was out, so the adjusted demand stands
    r = _run(str(ROOT / "data/cases/normal/case_01"), "FAC-011", "ORS sachet", "2026-03")
    assert "request_revision" not in [e["action"] for e in r["trace"]]


# ---------------------------------------------------------------------------
# Citation scope
# ---------------------------------------------------------------------------

def test_claim_citing_another_facilitys_row_is_rejected():
    data = load_dataset(SAMPLE)
    scope = {"facility_id": "FAC-009", "commodity": "magnesium sulphate inj", "month": "2026-03"}
    ev = {"theory_id": "H4", "verdict": "weakened", "cited_values": {"stock#3426": {"closing": 580}}}
    out = evaluator.verify_citations(ev, data, scope)
    assert not out["ok"] and "out of scope" in out["failures"][0]["reason"]
    assert out["verified"] == []
    # Same row is fine without a scope (existence and values only)
    assert evaluator.verify_citations(ev, data)["ok"]


def test_facilities_rows_only_for_case_or_transfer_source():
    data = load_dataset(SAMPLE)
    scope = {"facility_id": "FAC-009", "commodity": "magnesium sulphate inj", "month": "2026-03"}
    ev = {"theory_id": "H1", "supporting_evidence_ids": ["facilities#FAC-024"]}
    assert not evaluator.verify_citations(ev, data, scope)["ok"]
    assert evaluator.verify_citations(ev, data, {**scope, "transfer_sources": ["FAC-024"]})["ok"]
    assert evaluator.verify_citations({"theory_id": "H1", "supporting_evidence_ids": ["facilities#FAC-009"]},
                                      data, scope)["ok"]


def test_web_note_ids_are_one_based_like_zetaris():
    data = {"web_notes": [{"month": "2025-06", "commodity": "ORS sachet"},
                          {"id": "7", "month": "2025-11", "commodity": "zinc 20mg tab"}]}
    assert evaluator.lookup_row(data, "web_notes#1")["month"] == "2025-06"
    assert evaluator.lookup_row(data, "web_notes#7")["commodity"] == "zinc 20mg tab"
    assert evaluator.lookup_row(data, "web_notes#0") is None


# ---------------------------------------------------------------------------
# LLM fallback: a failing or malformed model never stops the run
# ---------------------------------------------------------------------------

AGENT_MODULES = ("data_reader", "data_analyst", "theory_generator", "evidence_investigator",
                 "action_strategist")


@pytest.mark.parametrize("mode", ["raises", "wrong_shape"])
def test_run_completes_when_llm_fails(offline, monkeypatch, mode):
    from llm_client import LLMError
    monkeypatch.setenv("STOCKWHY_USE_LLM", "true")
    monkeypatch.setattr(orchestrator, "llm_enabled", lambda: True)

    def broken(*args, **kwargs):
        if mode == "raises":
            raise LLMError("provider down")
        return {"theories": [{"title": "no id"}], "actions": "not a list", "evaluations": 3}

    for module in AGENT_MODULES:
        monkeypatch.setattr(f"agents.{module}.ask_agent", broken)
        monkeypatch.setattr(f"agents.{module}.llm_enabled", lambda: True)
    r = _run(SAMPLE, "FAC-009", "magnesium sulphate inj", "2026-03")
    assert r["status"] == "complete", r.get("error")
    assert r["verified_cause"]["hypothesis_id"] == "H1"
    steps = r["steps"]
    assert steps["data_reader"]["evidence"]["_fallback_reason"]
    assert steps["data_analyst"]["_fallback_reason"]
    assert steps["theory_generator"]["_fallback_reason"]
    assert steps["action_strategist"]["_fallback_reason"]
    assert all(e.get("_fallback_reason") for e in steps["evidence_investigator"]["evaluations"])


# ---------------------------------------------------------------------------
# No stock-out / no stock row
# ---------------------------------------------------------------------------

def test_no_stockout_month_returns_no_stockout(offline):
    data = load_dataset(SAMPLE)
    s = data["stock"]
    row = s[(s["reported_stockout_days"] == 0) & (s["closing"] > 0)].iloc[0]
    r = _run(SAMPLE, row["facility_id"], row["commodity"], row["month"])
    assert r["status"] == "no_stockout"
    assert r["citations"] == [f"stock#{row['id']}"]
    assert "investigate_wave" not in [e["action"] for e in r["trace"]]


# ---------------------------------------------------------------------------
# CLI review
# ---------------------------------------------------------------------------

def _tty(monkeypatch, answers):
    tty = io.StringIO("")
    tty.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", tty)
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(it))


def test_stop_leaves_rest_pending_and_mixed_is_partial(offline, monkeypatch):
    _tty(monkeypatch, ["a", "r", "", "s", "y"])
    memory = FakeMemory()
    r = _run(SAMPLE, "FAC-009", "magnesium sulphate inj", "2026-03", memory=memory, interactive=True)
    assert r["review"]["accepted"] == ["A1"] and r["review"]["rejected"] == ["A2"]
    assert r["review"]["pending"] == ["A3"]
    assert memory.feedbacks == [("mem-1", "partial")]


def test_wrong_cause_is_rejected(offline, monkeypatch):
    _tty(monkeypatch, ["a", "a", "a", "n"])
    memory = FakeMemory()
    _run(SAMPLE, "FAC-009", "magnesium sulphate inj", "2026-03", memory=memory, interactive=True)
    assert memory.feedbacks == [("mem-1", "rejected")]


# ---------------------------------------------------------------------------
# Scout contracts per phase
# ---------------------------------------------------------------------------

def test_every_phase_has_a_signed_child_of_the_scout_contract(offline):
    r = _run(SAMPLE, "FAC-009", "magnesium sulphate inj", "2026-03")
    root = r["contract"]["contractId"]
    phases = r["contracts"]["phases"]
    assert [p["phase"] for p in phases] == ["read", "analyse", "investigate", "draft", "memory"]
    for p in phases:
        assert p["contract"]["parentId"] == root
        assert p["contract"]["signedBy"] == "scout" and p["contract"]["signature"]
    draft = next(p for p in phases if p["phase"] == "draft")["contract"]
    assert "action.draft" in draft["scope"]["capabilities"]
    read = next(p for p in phases if p["phase"] == "read")["contract"]
    assert "action.draft" not in read["scope"]["capabilities"]
