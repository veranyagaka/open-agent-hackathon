"""
tests/test_agents.py

Tests for all four agents with LLM calls mocked.
No real API calls are made — the LLM client is patched throughout.
"""

import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import concurrent.futures

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Minimal LLM response factories
# ---------------------------------------------------------------------------

def _data_reader_response():
    return {
        "dataset_summary": {
            "stock_rows": 1, "order_rows": 1,
            "history_months_available": 3,
            "has_payment_records": True, "has_web_notes": False,
        },
        "relevant_records": {
            "stock_ids": ["stock#1"], "order_ids": ["orders#1"],
            "payment_months": ["2026-03"],
        },
        "data_quality_flags": [],
        "evidence_for_hypotheses": {
            "h1_late_order": "Order was placed 5 days after cutoff.",
            "h2_supplier_underfill": "Fill rate 92%, near county average.",
            "h3_payment_arrears": "No arrears flagged.",
            "h4_demand_surge": "Consumption up 60% vs 3-month average.",
            "h5_record_error": "Identity equation holds.",
            "h6_expiry": "No significant wastage.",
            "h7_national_disruption": "No public notice found.",
        },
        "missing_data_warnings": [],
    }


def _analyst_response():
    return {
        "analysis_summary": "Strong demand surge signal; late order also possible.",
        "hypothesis_signals": {
            "h1_late_order": "weak",
            "h2_supplier_underfill": "none",
            "h3_payment_arrears": "none",
            "h4_demand_surge": "strong",
            "h5_record_error": "none",
            "h6_expiry": "none",
            "h7_national_disruption": "none",
        },
        "data_quality_issues": [],
        "observed_patterns": ["Consumption spike in 2026-03"],
        "evidence_gaps": [],
        "recommended_tests": [],
    }


def _theories_response():
    theories = []
    names = [
        ("H1", "late_order", "Late ordering"),
        ("H2", "supplier_underfill", "Supplier under-fill"),
        ("H3", "payment_arrears", "Payment arrears"),
        ("H4", "demand_surge", "Demand surge"),
        ("H5", "record_error", "Stock record error"),
        ("H6", "expiry", "Expiry or wastage"),
        ("H7", "national_disruption", "National supply disruption"),
    ]
    for h_id, h_name, title in names:
        theories.append({
            "id": h_id,
            "hypothesis_name": h_name,
            "title": title,
            "mechanism": f"Mechanism for {h_name}",
            "evidence_needed": [f"Need data for {h_name}"],
            "disconfirming_evidence": [f"Counter for {h_name}"],
            "predictions": [f"Prediction for {h_name}"],
        })
    return {"theories": theories}


def _evaluation_response(theory_id="H4", hypothesis_name="demand_surge"):
    return {
        "theory_id": theory_id,
        "hypothesis_name": hypothesis_name,
        "verdict": "supported",
        "supporting_evidence_ids": ["stock#1"],
        "contradicting_evidence_ids": [],
        "reasoning": "Consumption was 60% above baseline.",
        "limitations": ["3-month window may be insufficient"],
        "additional_analysis_needed": [],
    }


def _actions_response():
    return {
        "most_likely_cause": "demand_surge",
        "ranked_hypotheses": [
            {"hypothesis_id": "H4", "hypothesis_name": "demand_surge",
             "verdict": "supported", "likelihood": "high"},
            {"hypothesis_id": "H1", "hypothesis_name": "late_order",
             "verdict": "weakened", "likelihood": "low"},
        ],
        "actions": [
            {
                "action_id": "A1",
                "action": "Submit emergency requisition for ORS sachet.",
                "linked_theory_ids": ["H4"],
                "evidence_basis": "Demand spike confirmed by stock records.",
                "priority": "high",
                "proposed_owner": "Facility pharmacist",
                "timeframe": "Within 24 hours",
                "expected_outcome": "Stock replenished within 3 days.",
                "success_measure": "Stock > 0 within 72 hours.",
                "risks_and_caveats": "Requires county approval.",
                "pharmacist_review_required": True,
            },
        ],
        "communication_draft": "Dear County Pharmacist,\n\nUrgent stock replenishment needed...",
        "open_questions": ["Will demand continue at this level?"],
    }


# ---------------------------------------------------------------------------
# Data Reader Agent tests
# ---------------------------------------------------------------------------

class TestDataReaderAgent:
    @patch("agents.data_reader.load_dataset")
    @patch("agents.data_reader.profile_stockout")
    @patch("agents.data_reader.ask_agent")
    def test_returns_required_structure(self, mock_ask, mock_profile, mock_load):
        mock_load.return_value = {}
        mock_profile.return_value = {
            "stock_record": [], "order_record": [], "payments_history": [],
            "stock_history": [], "web_notes": [],
            "computed_evidence": {
                "h1_late_order": {}, "h2_supplier_underfill": {},
                "h3_payment_arrears": {}, "h4_demand_surge": {},
                "h5_record_error": {}, "h6_expiry": {}, "h7_national_disruption": {},
            },
        }
        mock_ask.return_value = _data_reader_response()

        from agents.data_reader import read_and_profile
        result = read_and_profile("data/sample", "FAC-011", "ORS sachet", "2026-03")

        assert "facility_id" in result
        assert "commodity" in result
        assert "month" in result
        assert "evidence" in result
        assert "computed_evidence" in result
        assert "missing_data_warnings" in result
        assert result["facility_id"] == "FAC-011"

    @patch("agents.data_reader.load_dataset")
    @patch("agents.data_reader.profile_stockout")
    @patch("agents.data_reader.ask_agent")
    def test_never_reads_answer_key(self, mock_ask, mock_profile, mock_load):
        """The data reader must never touch eval/answer_key.csv"""
        import agents.data_reader as dr
        import inspect
        source = inspect.getsource(dr)
        assert "answer_key" not in source.lower()
        assert "ANSWER_KEY" not in source

    @patch("agents.data_reader.load_dataset")
    @patch("agents.data_reader.profile_stockout")
    @patch("agents.data_reader.ask_agent")
    def test_llm_called_once(self, mock_ask, mock_profile, mock_load):
        mock_load.return_value = {}
        mock_profile.return_value = {
            "stock_record": [], "order_record": [], "payments_history": [],
            "stock_history": [], "web_notes": [],
            "computed_evidence": {k: {} for k in [
                "h1_late_order", "h2_supplier_underfill", "h3_payment_arrears",
                "h4_demand_surge", "h5_record_error", "h6_expiry",
                "h7_national_disruption"
            ]},
        }
        mock_ask.return_value = _data_reader_response()
        from agents.data_reader import read_and_profile
        read_and_profile("data/sample", "FAC-001", "test", "2026-03")
        assert mock_ask.call_count == 1


# ---------------------------------------------------------------------------
# Data Analyst Agent tests
# ---------------------------------------------------------------------------

class TestDataAnalystAgent:
    @patch("agents.data_analyst.ask_agent")
    def test_analyze_evidence_returns_signals(self, mock_ask):
        mock_ask.return_value = _analyst_response()
        from agents.data_analyst import analyze_evidence
        result = analyze_evidence(
            {"h1_late_order": {"late": False}, "h4_demand_surge": {"surge": True}},
            "Why did FAC-011 run out of ORS sachet in 2026-03?"
        )
        assert "hypothesis_signals" in result or "analysis_summary" in result

    @patch("agents.data_analyst.ask_agent")
    def test_original_analyze_still_works(self, mock_ask):
        mock_ask.return_value = {
            "dataset_overview": "overview",
            "data_quality_issues": [],
            "observed_patterns": [],
            "evidence_gaps": [],
            "recommended_tests": [],
        }
        from agents.data_analyst import analyze
        result = analyze({"Monthly_Summary": {}}, "test question")
        assert "dataset_overview" in result


# ---------------------------------------------------------------------------
# Theory Generator Agent tests
# ---------------------------------------------------------------------------

class TestTheoryGeneratorAgent:
    @patch("agents.theory_generator.ask_agent")
    def test_generates_seven_theories(self, mock_ask):
        mock_ask.return_value = _theories_response()
        from agents.theory_generator import generate
        result = generate("Why did FAC-011 run out?", _analyst_response())
        assert len(result["theories"]) == 7

    @patch("agents.theory_generator.ask_agent")
    def test_all_hypothesis_ids_present(self, mock_ask):
        mock_ask.return_value = _theories_response()
        from agents.theory_generator import generate
        result = generate("Why?", {})
        ids = {t["id"] for t in result["theories"]}
        assert ids == {"H1", "H2", "H3", "H4", "H5", "H6", "H7"}

    @patch("agents.theory_generator.ask_agent")
    def test_wrong_count_raises(self, mock_ask):
        mock_ask.return_value = {"theories": [{"id": "H1", "hypothesis_name": "late_order"}]}
        from agents.theory_generator import generate
        with pytest.raises(ValueError, match="Expected 7"):
            generate("Why?", {})

    @patch("agents.theory_generator.ask_agent")
    def test_missing_hypothesis_id_raises(self, mock_ask):
        # 7 theories but H4 is missing, duplicate H1 instead
        resp = _theories_response()
        resp["theories"][3]["id"] = "H1_dup"
        mock_ask.return_value = resp
        from agents.theory_generator import generate
        with pytest.raises(ValueError):
            generate("Why?", {})

    def test_each_theory_has_required_fields(self):
        """All theory dicts in a valid response must have required fields."""
        theories = _theories_response()["theories"]
        required = {"id", "hypothesis_name", "title", "mechanism",
                    "evidence_needed", "disconfirming_evidence", "predictions"}
        for t in theories:
            assert required.issubset(set(t.keys())), (
                f"Theory {t.get('id')} missing fields: {required - set(t.keys())}"
            )


# ---------------------------------------------------------------------------
# Evidence Investigator Agent tests
# ---------------------------------------------------------------------------

class TestEvidenceInvestigatorAgent:
    @patch("agents.evidence_investigator.ask_agent")
    def test_investigate_sequential(self, mock_ask):
        mock_ask.return_value = {
            "evaluations": [_evaluation_response()],
            "analysis_requests": [],
        }
        from agents.evidence_investigator import investigate
        result = investigate("Why?", _theories_response(), _analyst_response(), [])
        assert "evaluations" in result

    @patch("agents.evidence_investigator.ask_agent")
    def test_investigate_parallel_returns_seven(self, mock_ask):
        """investigate_parallel should return one evaluation per theory."""
        # Mock returns the appropriate evaluation for each call
        def side_effect(system_prompt, payload):
            t = payload.get("theory", {})
            h_id = t.get("id", "H1")
            return _evaluation_response(h_id, t.get("hypothesis_name", "unknown"))

        mock_ask.side_effect = side_effect
        from agents.evidence_investigator import investigate_parallel
        result = investigate_parallel(
            "Why?",
            _theories_response(),
            {
                "h1_late_order": {"late": False},
                "h2_supplier_underfill": {"underfill": False},
                "h3_payment_arrears": {"major_arrears": False},
                "h4_demand_surge": {"surge": True},
                "h5_record_error": {"identity_holds": True},
                "h6_expiry": {"high_wastage": False},
                "h7_national_disruption": {"web_notice_found": False},
            }
        )
        assert "evaluations" in result
        assert len(result["evaluations"]) == 7

    @patch("agents.evidence_investigator.ask_agent")
    def test_parallel_sorted_by_id(self, mock_ask):
        """Parallel evaluations should be sorted H1..H7 for determinism."""
        def side_effect(system_prompt, payload):
            t = payload.get("theory", {})
            h_id = t.get("id", "H1")
            return {"theory_id": h_id, "hypothesis_name": "x",
                    "verdict": "inconclusive", "supporting_evidence_ids": [],
                    "contradicting_evidence_ids": [], "reasoning": "",
                    "limitations": [], "additional_analysis_needed": []}

        mock_ask.side_effect = side_effect
        from agents.evidence_investigator import investigate_parallel
        result = investigate_parallel(
            "Why?", _theories_response(),
            {k: {} for k in [
                "h1_late_order", "h2_supplier_underfill", "h3_payment_arrears",
                "h4_demand_surge", "h5_record_error", "h6_expiry",
                "h7_national_disruption"
            ]}
        )
        ids = [e["theory_id"] for e in result["evaluations"]]
        assert ids == ["H1", "H2", "H3", "H4", "H5", "H6", "H7"]

    @patch("agents.evidence_investigator.ask_agent")
    def test_parallel_handles_single_failure_gracefully(self, mock_ask):
        """If one parallel call fails, the rest should still return."""
        call_count = [0]

        def side_effect(system_prompt, payload):
            call_count[0] += 1
            t = payload.get("theory", {})
            if t.get("id") == "H3":
                raise RuntimeError("Simulated API failure")
            return _evaluation_response(t.get("id", "H1"), t.get("hypothesis_name", "x"))

        mock_ask.side_effect = side_effect
        from agents.evidence_investigator import investigate_parallel, _deterministic_verdict
        result = investigate_parallel(
            "Why?", _theories_response(),
            {k: {} for k in [
                "h1_late_order", "h2_supplier_underfill", "h3_payment_arrears",
                "h4_demand_surge", "h5_record_error", "h6_expiry",
                "h7_national_disruption"
            ]}
        )
        # Should still return 7 evaluations
        assert len(result["evaluations"]) == 7
        h3 = next(e for e in result["evaluations"] if e["theory_id"] == "H3")
        # H3 with empty evidence {} gets deterministic verdict (not inconclusive)
        # The deterministic verdict for H3 with empty evidence is "weakened"
        # (no major_arrears flag = False/missing)
        expected_verdict = _deterministic_verdict("H3", {})
        assert h3["verdict"] == expected_verdict, (
            f"Expected deterministic verdict '{expected_verdict}' for H3 on failure, "
            f"got '{h3['verdict']}'"
        )


# ---------------------------------------------------------------------------
# Action Strategist Agent tests
# ---------------------------------------------------------------------------

class TestActionStrategistAgent:
    @patch("agents.action_strategist.ask_agent")
    def test_returns_actions_list(self, mock_ask):
        mock_ask.return_value = _actions_response()
        from agents.action_strategist import recommend_actions
        result = recommend_actions("Why?", {"evaluations": [_evaluation_response()]})
        assert "actions" in result
        assert isinstance(result["actions"], list)

    @patch("agents.action_strategist.ask_agent")
    def test_pharmacist_review_flag_enforced(self, mock_ask):
        """Every action must have pharmacist_review_required=True."""
        response = _actions_response()
        # Deliberately remove the flag from one action
        response["actions"][0]["pharmacist_review_required"] = False
        mock_ask.return_value = response
        from agents.action_strategist import recommend_actions
        result = recommend_actions("Why?", {})
        for action in result.get("actions", []):
            assert action.get("pharmacist_review_required") is True, (
                f"Action {action.get('action_id')} missing pharmacist_review_required=True"
            )

    @patch("agents.action_strategist.ask_agent")
    def test_returns_communication_draft(self, mock_ask):
        mock_ask.return_value = _actions_response()
        from agents.action_strategist import recommend_actions
        result = recommend_actions("Why?", {})
        assert "communication_draft" in result
        assert len(result["communication_draft"]) > 0

    def test_system_prompt_contains_no_autonomous_execution(self):
        """System prompt must forbid autonomous execution."""
        from agents.action_strategist import SYSTEM
        lowered = SYSTEM.lower()
        assert "never" in lowered or "do not" in lowered or "must not" in lowered
        assert "autonomous" in lowered or "pharmacist" in lowered

    @patch("agents.action_strategist.ask_agent")
    def test_returns_ranked_hypotheses(self, mock_ask):
        mock_ask.return_value = _actions_response()
        from agents.action_strategist import recommend_actions
        result = recommend_actions("Why?", {})
        assert "ranked_hypotheses" in result
        assert len(result["ranked_hypotheses"]) > 0
