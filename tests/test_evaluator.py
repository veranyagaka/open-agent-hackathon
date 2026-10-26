"""
tests/test_evaluator.py

Unit tests for the Evaluator agent (agents/evaluator.py). Deterministic, no LLM.
The small dataset below is also used by tests/test_orchestrator.py.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents import evaluator  # noqa: E402

FAC, MED, MONTH = "FAC-009", "magnesium sulphate inj", "2026-03"


# ---------------------------------------------------------------------------
# Shared fixtures (plain builders so other test modules can import them)
# ---------------------------------------------------------------------------

def make_dataset(closing=0, consumed=100, delivery_month="2026-04", web_notes=None,
                 payments=None):
    stock = pd.DataFrame([
        {"id": "1506", "facility_id": FAC, "commodity": MED, "month": MONTH, "opening": 100,
         "received": 0, "wastage": 0, "consumed": consumed, "closing": closing,
         "reported_stockout_days": 10},
        {"id": "1505", "facility_id": FAC, "commodity": MED, "month": "2026-02", "opening": 150,
         "received": 40, "wastage": 0, "consumed": 90, "closing": 100,
         "reported_stockout_days": 0},
    ])
    orders = pd.DataFrame([
        {"id": "3161", "facility_id": FAC, "commodity": MED, "month": "2026-02",
         "cutoff_date": pd.Timestamp("2026-02-10"), "order_date": pd.Timestamp("2026-02-15"),
         "qty_requested": 200, "qty_delivered": 180, "delivery_month": delivery_month},
    ])
    payments = pd.DataFrame(payments or [
        {"id": "1", "month": MONTH, "county_arrears_flag": 0, "amount_owed_kes": 0},
    ])
    facilities = pd.DataFrame([{"facility_id": FAC, "lat": -1.0, "lon": 36.0}])
    return {"stock": stock, "orders": orders, "payments": payments,
            "facilities": facilities, "web_notes": web_notes or [], "_source": "csv"}


def make_evidence(**overrides):
    """computed_evidence matching make_dataset(): H1 (late order) is the real cause."""
    ev = {
        "h1_late_order": {"late": True, "delivery_slipped": True, "order_id": "orders#3161",
                          "order_date": "2026-02-15", "cutoff_date": "2026-02-10",
                          "delivery_month": "2026-04", "expected_delivery_month": MONTH,
                          "days_late": 5},
        "h2_supplier_underfill": {"underfill": False, "facility_fill_rate": 0.9,
                                  "county_avg_fill_rate": 0.9, "order_id": "orders#3161"},
        "h3_payment_arrears": {"arrears_in_month": False, "major_arrears": False,
                               "amount_owed_kes": 0.0, "fill_drop_vs_prev": 0.0},
        "h4_demand_surge": {"surge": False, "consumed_this_month": 100.0, "pct_change": 11.1,
                            "avg_consumed_3m": 90.0, "stock_id": "stock#1506"},
        "h5_record_error": {"identity_holds": True, "stockout_days_plausible": True,
                            "computed_closing": 0.0, "reported_closing": 0.0, "discrepancy": 0.0,
                            "reported_stockout_days": 10.0, "stock_id": "stock#1506"},
        "h6_expiry": {"high_wastage": False, "wastage_this_month": 0.0, "avg_wastage_3m": 0.0,
                      "stock_id": "stock#1506"},
        "h7_national_disruption": {"web_notice_found": False, "county_fill_drop": 0.0,
                                   "notice_details": None},
    }
    for key, patch in overrides.items():
        ev[key] = {**ev[key], **patch}
    return ev


def make_eval(h_id, verdict, supporting=None):
    return {"theory_id": h_id, "hypothesis_name": evaluator.HYPOTHESIS_NAMES[h_id],
            "verdict": verdict, "supporting_evidence_ids": list(supporting or []),
            "contradicting_evidence_ids": [], "reasoning": "test"}


def claimed(h_id, verdict, evidence=None, dataset=None, supporting=None):
    ev = make_eval(h_id, verdict, supporting)
    return evaluator.attach_claims(ev, evidence or make_evidence(), dataset or make_dataset(), MONTH)


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------

class TestCitations:

    def test_derived_claims_verify_against_rows(self):
        ev = claimed("H1", "supported")
        assert ev["cited_values"]["orders#3161"]["order_date"] == "2026-02-15"
        report = evaluator.verify_citations(ev, make_dataset())
        assert report["ok"], report
        assert report["verified"] == ["orders#3161"]

    def test_unknown_row_is_a_failure(self):
        ev = claimed("H4", "weakened", supporting=["stock#999999"])
        report = evaluator.verify_citations(ev, make_dataset())
        assert not report["ok"]
        assert report["failures"][0]["row_id"] == "stock#999999"
        assert not report["core_failed"]  # extra id, not a number the verdict rests on

    def test_mismatched_number_is_a_core_failure(self):
        ev = claimed("H4", "weakened")
        ev["cited_values"]["stock#1506"]["consumed"] = 175
        report = evaluator.verify_citations(ev, make_dataset())
        assert not report["ok"] and report["core_failed"]
        fail = report["failures"][0]
        assert fail["field"] == "consumed" and fail["actual"] in ("100", "100.0")

    def test_derived_fill_rate_and_computed_closing(self):
        assert evaluator.verify_citations(claimed("H2", "weakened"), make_dataset())["ok"]
        assert evaluator.verify_citations(claimed("H5", "weakened"), make_dataset())["ok"]

    def test_non_row_strings_are_ignored(self):
        ev = claimed("H6", "weakened", supporting=["h6_expiry.high_wastage", "stock#1505"])
        report = evaluator.verify_citations(ev, make_dataset())
        assert report["ok"]
        assert "stock#1505" in report["verified"]

    def test_payments_rows_cited_for_arrears(self):
        ds = make_dataset(payments=[
            {"id": "7", "month": "2026-02", "county_arrears_flag": 1, "amount_owed_kes": 42_000_000},
        ])
        evidence = make_evidence(h3_payment_arrears={"arrears_in_month": True, "major_arrears": True,
                                                     "amount_owed_kes": 42_000_000.0})
        ev = claimed("H3", "supported", evidence, ds)
        assert "payments#7" in ev["cited_values"]
        assert evaluator.verify_citations(ev, ds)["ok"]


# ---------------------------------------------------------------------------
# Consistency
# ---------------------------------------------------------------------------

class TestConsistency:

    def test_supported_surge_without_flag_is_rejected(self):
        res = evaluator.check_consistency(make_eval("H4", "supported"), make_evidence())
        assert not res["ok"]
        assert res["expected"] == "weakened"

    def test_missed_cause_is_rejected(self):
        res = evaluator.check_consistency(make_eval("H1", "weakened"), make_evidence())
        assert not res["ok"]

    def test_inconclusive_vs_weakened_is_tolerated(self):
        assert evaluator.check_consistency(make_eval("H6", "inconclusive"), make_evidence())["ok"]

    def test_record_error_flag(self):
        ev = make_evidence(h5_record_error={"identity_holds": False})
        assert evaluator.expected_verdict("H5", ev["h5_record_error"]) == "supported"


# ---------------------------------------------------------------------------
# Cross-critique
# ---------------------------------------------------------------------------

class TestCrossCritique:

    def test_surge_against_broken_identity(self):
        evidence = make_evidence(
            h4_demand_surge={"surge": True, "pct_change": 60.0},
            h5_record_error={"identity_holds": False, "reported_closing": 30.0},
        )
        crit = evaluator.cross_critique([make_eval("H4", "supported")], evidence, MONTH)
        assert crit and crit[0]["target"] == "H4" and crit[0]["raised_by"] == "H5"

    def test_surge_against_stock_on_hand(self):
        evidence = make_evidence(
            h4_demand_surge={"surge": True},
            h5_record_error={"identity_holds": True, "stockout_days_plausible": False},
        )
        crit = evaluator.cross_critique([make_eval("H4", "supported")], evidence, MONTH)
        assert crit[0]["kind"] == "stock_on_hand"

    def test_late_order_delivered_before_stockout(self):
        evidence = make_evidence(h1_late_order={"delivery_month": "2026-02"})
        crit = evaluator.cross_critique([make_eval("H1", "supported")], evidence, MONTH)
        assert crit[0]["target"] == "H1" and crit[0]["kind"] == "delivered_before_stockout"

    def test_arrears_with_full_county_supply(self):
        full = make_evidence(h3_payment_arrears={"major_arrears": True, "county_fill_prev_month": 0.95,
                                                 "county_fill_this_month": 0.92})
        crit = evaluator.cross_critique([make_eval("H3", "supported")], full, MONTH)
        assert crit[0]["kind"] == "no_delivery_drop"
        short = make_evidence(h3_payment_arrears={"major_arrears": True, "county_fill_prev_month": 0.39,
                                                  "county_fill_this_month": 0.92})
        assert evaluator.cross_critique([make_eval("H3", "supported")], short, MONTH) == []

    def test_no_critique_when_consistent(self):
        assert evaluator.cross_critique([make_eval("H1", "supported")], make_evidence(), MONTH) == []

    def test_settle_downgrades_contested_claim(self):
        evidence = make_evidence(h4_demand_surge={"surge": True},
                                 h5_record_error={"identity_holds": False})
        ev = claimed("H4", "supported", evidence)
        report = evaluator.review([ev], evidence, make_dataset(), MONTH)["reports"]["H4"]
        kept, note = evaluator.settle(ev, report)
        assert kept["verdict"] == "inconclusive" and kept["contested_by"] == ["H5"]
        assert "contested" in note


# ---------------------------------------------------------------------------
# Review + coverage
# ---------------------------------------------------------------------------

class TestReviewAndCoverage:

    def test_review_flags_only_bad_evaluations(self):
        good = claimed("H1", "supported")
        bad = claimed("H4", "supported")
        out = evaluator.review([good, bad], make_evidence(), make_dataset(), MONTH)
        assert out["failed"] == ["H4"]
        assert out["reports"]["H1"]["ok"]
        assert "computed flags" in evaluator.critique_text(out["reports"]["H4"])

    def test_settle_drops_wrong_numbers(self):
        ev = claimed("H4", "weakened")
        ev["cited_values"]["stock#1506"]["consumed"] = 1
        report = evaluator.review([ev], make_evidence(), make_dataset(), MONTH)["reports"]["H4"]
        kept, note = evaluator.settle(ev, report)
        assert kept is None and "do not match" in note

    def test_coverage_states(self):
        final = {"H1": {**make_eval("H1", "supported"), "verified_citations": ["orders#3161"]}}
        assert evaluator.check_coverage(final, ["H2"])["verdict"] == "explained"
        weak = {"H4": {**make_eval("H4", "weakened"), "verified_citations": ["stock#1506"]}}
        assert evaluator.check_coverage(weak, ["H2", "H3"])["request"] == ["H2", "H3"]
        assert evaluator.check_coverage(weak, [])["verdict"] == "insufficient_evidence"

    def test_supported_without_verified_rows_does_not_count(self):
        final = {"H7": {**make_eval("H7", "supported"), "verified_citations": []}}
        assert evaluator.check_coverage(final, [])["verdict"] == "insufficient_evidence"
