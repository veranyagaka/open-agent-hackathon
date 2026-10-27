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

REPO = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def _llm_on(monkeypatch):
    """Mocked-LLM tests run with the LLM switch on; offline tests turn it off."""
    monkeypatch.setenv("STOCKWHY_USE_LLM", "true")


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
    def test_wrong_count_falls_back_to_rules(self, mock_ask, monkeypatch):
        monkeypatch.setenv("STOCKWHY_USE_LLM", "true")
        mock_ask.return_value = {"theories": [{"id": "H1", "hypothesis_name": "late_order"}]}
        from agents.theory_generator import generate
        result = generate("Why?", {})
        assert [t["id"] for t in result["theories"]] == [f"H{i}" for i in range(1, 8)]
        assert "Expected 7" in result["_fallback_reason"]

    @patch("agents.theory_generator.ask_agent")
    def test_missing_hypothesis_id_falls_back_to_rules(self, mock_ask, monkeypatch):
        # 7 theories but H4 is missing, duplicate H1 instead
        monkeypatch.setenv("STOCKWHY_USE_LLM", "true")
        resp = _theories_response()
        resp["theories"][3]["id"] = "H1_dup"
        mock_ask.return_value = resp
        from agents.theory_generator import generate
        result = generate("Why?", {})
        assert {t["id"] for t in result["theories"]} == {f"H{i}" for i in range(1, 8)}
        assert "H4" in result["_fallback_reason"]

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
        def side_effect(system_prompt, payload, **kwargs):
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
        def side_effect(system_prompt, payload, **kwargs):
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

        def side_effect(system_prompt, payload, **kwargs):
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


# ---------------------------------------------------------------------------
# Rule-based (offline) mode — real logic on cached data, no LLM
# ---------------------------------------------------------------------------

OFFLINE_CASES = [
    # dataset, facility, commodity, month, expected top hypothesis from computed_evidence
    ("data/sample", "FAC-009", "magnesium sulphate inj", "2026-03", "H1", "orders#1265"),
    ("data/cases/normal/case_01", "FAC-011", "ORS sachet", "2026-03", "H4", "stock#1506"),
    ("data/cases/normal/case_06", "FAC-022", "iron-folate tab", "2026-03", "H1", "orders#3161"),
]


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setenv("STOCKWHY_USE_LLM", "false")
    monkeypatch.setenv("STOCKWHY_DATA_SOURCE", "csv")

    def no_llm(*args, **kwargs):
        raise AssertionError("ask_agent must not be called in rule-based mode")

    for module in ("data_reader", "data_analyst", "theory_generator",
                   "evidence_investigator", "action_strategist"):
        monkeypatch.setattr(f"agents.{module}.ask_agent", no_llm)


def _run_offline(dataset, facility, commodity, month):
    from agents.data_reader import read_and_profile
    from agents.data_analyst import analyze_evidence
    from agents.theory_generator import generate
    from agents.evidence_investigator import investigate_parallel
    from agents.action_strategist import recommend_actions

    question = f"Why did facility {facility} report a stockout of {commodity} in {month}?"
    profile = read_and_profile(str(REPO / dataset), facility, commodity, month)
    analysis = analyze_evidence(profile["computed_evidence"], question)
    theories = generate(question, analysis)
    evaluations = investigate_parallel(question, theories, profile["computed_evidence"])
    actions = recommend_actions(question, evaluations, facility_id=facility, commodity=commodity,
                                month=month)
    return profile, analysis, theories, evaluations, actions


class TestLLMSwitch:
    def test_sample_mode_disables_llm(self, monkeypatch):
        from llm_client import llm_enabled
        monkeypatch.delenv("STOCKWHY_USE_LLM", raising=False)
        monkeypatch.setenv("SAMPLE_MODE", "true")
        assert llm_enabled() is False
        monkeypatch.setenv("SAMPLE_MODE", "false")
        assert llm_enabled() is True

    def test_explicit_switch_wins(self, monkeypatch):
        from llm_client import llm_enabled
        monkeypatch.setenv("SAMPLE_MODE", "true")
        monkeypatch.setenv("STOCKWHY_USE_LLM", "true")
        assert llm_enabled() is False  # SAMPLE_MODE=true always means offline
        monkeypatch.setenv("SAMPLE_MODE", "false")
        monkeypatch.setenv("STOCKWHY_USE_LLM", "0")
        assert llm_enabled() is False


@pytest.mark.parametrize("dataset,facility,commodity,month,top,row_id", OFFLINE_CASES)
class TestOfflineAgents:
    def test_data_reader(self, offline, dataset, facility, commodity, month, top, row_id):
        profile, *_ = _run_offline(dataset, facility, commodity, month)
        evidence = profile["evidence"]
        assert profile["_produced_by"] == "rule-based"
        assert evidence["_produced_by"] == "rule-based"
        assert set(evidence["evidence_for_hypotheses"]) == {
            "h1_late_order", "h2_supplier_underfill", "h3_payment_arrears",
            "h4_demand_surge", "h5_record_error", "h6_expiry", "h7_national_disruption",
        }
        assert evidence["dataset_summary"]["stock_rows"] == 1
        all_ids = evidence["relevant_records"]["stock_ids"] + evidence["relevant_records"]["order_ids"]
        assert row_id in all_ids
        assert any(row_id in text for text in evidence["evidence_for_hypotheses"].values())

    def test_data_analyst(self, offline, dataset, facility, commodity, month, top, row_id):
        _, analysis, *_ = _run_offline(dataset, facility, commodity, month)
        assert analysis["_produced_by"] == "rule-based"
        assert set(analysis["hypothesis_signals"]) == {f"H{i}" for i in range(1, 8)}
        assert analysis["primary_lead_ids"][0] == top
        assert analysis["hypothesis_signals"][top]["signal"] == "strong"
        assert row_id in analysis["hypothesis_signals"][top]["reasoning"]

    def test_theory_generator(self, offline, dataset, facility, commodity, month, top, row_id):
        _, _, theories, *_ = _run_offline(dataset, facility, commodity, month)
        assert theories["_produced_by"] == "rule-based"
        assert [t["id"] for t in theories["theories"]] == [f"H{i}" for i in range(1, 8)]
        lead = next(t for t in theories["theories"] if t["id"] == top)
        assert lead["lead_signal"] == "strong"

    def test_evidence_investigator(self, offline, dataset, facility, commodity, month, top, row_id):
        *_, evaluations, _ = _run_offline(dataset, facility, commodity, month)
        assert evaluations["_produced_by"] == "rule-based"
        evals = {e["theory_id"]: e for e in evaluations["evaluations"]}
        assert len(evals) == 7
        assert evals[top]["verdict"] == "supported"
        assert row_id in evals[top]["supporting_evidence_ids"]
        assert row_id in evals[top]["reasoning"]
        assert all(e["_produced_by"] == "rule-based" for e in evals.values())

    def test_action_strategist(self, offline, dataset, facility, commodity, month, top, row_id):
        *_, actions = _run_offline(dataset, facility, commodity, month)
        assert actions["_produced_by"] == "rule-based"
        assert actions["ranked_hypotheses"][0]["hypothesis_id"] == top
        assert actions["most_likely_hypothesis_id"] == top
        assert actions["actions"]
        assert all(a["pharmacist_review_required"] is True for a in actions["actions"])
        assert any(row_id in a["evidence_basis"] for a in actions["actions"])
        assert facility in actions["emergency_requisition_memo"]
        assert "medical_disclaimer" in actions

    def test_offline_never_reads_answer_key(self, offline, monkeypatch, dataset, facility, commodity, month, top, row_id):
        import builtins
        real_open = builtins.open

        def guarded_open(file, *args, **kwargs):
            name = str(file).lower()
            assert "answer_key" not in name and "dev_notes" not in name and "output_examples" not in name
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", guarded_open)
        _run_offline(dataset, facility, commodity, month)


class TestOfflineFallbacks:
    def test_no_supported_hypothesis_is_undetermined(self, offline):
        from agents.action_strategist import recommend_actions
        result = recommend_actions("Why?", {"evaluations": [
            {"theory_id": "H1", "hypothesis_name": "late_order", "verdict": "weakened",
             "reasoning": "x", "supporting_evidence_ids": [], "contradicting_evidence_ids": ["orders#1"]},
        ]})
        assert result["most_likely_hypothesis_id"] is None
        assert result["most_likely_cause"].startswith("undetermined")
        assert all(a["pharmacist_review_required"] for a in result["actions"])

    def test_missing_evidence_is_inconclusive(self, offline):
        from agents.evidence_investigator import investigate_parallel
        from agents.theory_generator import generate
        theories = generate("Why?", {})
        result = investigate_parallel("Why?", theories, {
            "h1_late_order": {"data_missing": True, "late": False},
        })
        h1 = next(e for e in result["evaluations"] if e["theory_id"] == "H1")
        assert h1["verdict"] == "inconclusive"

    def test_cap_reached_falls_back_with_label(self, monkeypatch):
        from llm_client import LLMCallCapReached
        import agents.data_analyst as da

        def capped(*args, **kwargs):
            raise LLMCallCapReached("LLM call cap reached (0 calls)")

        monkeypatch.setattr(da, "ask_agent", capped)
        result = da.analyze_evidence({"h4_demand_surge": {"surge": True, "pct_change": 60.0,
                                                           "stock_id": "stock#9"}}, "Why?")
        assert result["_produced_by"] == "rule-based"
        assert "cap" in result["_fallback_reason"]
