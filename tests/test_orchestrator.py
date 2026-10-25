"""
tests/test_orchestrator.py

Tests for the StockyWhy orchestrator pipeline.
All LLM calls mocked. No real API calls made.
"""

import sys
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Shared mock responses (same as in test_agents.py)
def _data_reader_resp(facility, commodity, month):
    return {
        "facility_id": facility,
        "commodity": commodity,
        "month": month,
        "evidence": {
            "dataset_summary": {"stock_rows": 1, "order_rows": 1,
                                 "history_months_available": 3,
                                 "has_payment_records": True, "has_web_notes": False},
            "relevant_records": {"stock_ids": ["stock#1"], "order_ids": ["orders#1"],
                                  "payment_months": []},
            "data_quality_flags": [],
            "evidence_for_hypotheses": {
                "h1_late_order": "late", "h2_supplier_underfill": "no",
                "h3_payment_arrears": "no", "h4_demand_surge": "strong",
                "h5_record_error": "ok", "h6_expiry": "no",
                "h7_national_disruption": "no",
            },
            "missing_data_warnings": [],
        },
        "computed_evidence": {
            "h1_late_order": {"late": False}, "h2_supplier_underfill": {"underfill": False},
            "h3_payment_arrears": {"major_arrears": False},
            "h4_demand_surge": {"surge": True}, "h5_record_error": {"identity_holds": True},
            "h6_expiry": {"high_wastage": False}, "h7_national_disruption": {"web_notice_found": False},
        },
        "data_quality": [],
        "missing_data_warnings": [],
        "_profile": {},
    }

def _analyst_resp():
    return {
        "analysis_summary": "Strong demand surge.",
        "hypothesis_signals": {"h4_demand_surge": "strong"},
        "data_quality_issues": [], "observed_patterns": [],
        "evidence_gaps": [], "recommended_tests": [],
    }

def _theories_resp():
    return {"theories": [
        {"id": f"H{i}", "hypothesis_name": name, "title": f"Theory {i}",
         "mechanism": "mech", "evidence_needed": [], "disconfirming_evidence": [],
         "predictions": []}
        for i, name in enumerate(
            ["late_order", "supplier_underfill", "payment_arrears",
             "demand_surge", "record_error", "expiry", "national_disruption"], 1
        )
    ]}

def _evaluations_resp():
    return {
        "evaluations": [
            {"theory_id": f"H{i}", "hypothesis_name": name, "verdict": "inconclusive",
             "supporting_evidence_ids": [], "contradicting_evidence_ids": [],
             "reasoning": "Test", "limitations": [], "additional_analysis_needed": []}
            for i, name in enumerate(
                ["late_order", "supplier_underfill", "payment_arrears",
                 "demand_surge", "record_error", "expiry", "national_disruption"], 1
            )
        ],
        "analysis_requests": [],
    }

def _actions_resp():
    return {
        "most_likely_cause": "demand_surge",
        "ranked_hypotheses": [
            {"hypothesis_id": "H4", "hypothesis_name": "demand_surge",
             "verdict": "supported", "likelihood": "high"}
        ],
        "actions": [
            {"action_id": "A1", "action": "Submit emergency req.",
             "linked_theory_ids": ["H4"], "evidence_basis": "Demand spike",
             "priority": "high", "proposed_owner": "Pharmacist",
             "timeframe": "24h", "expected_outcome": "Stock restored",
             "success_measure": "Stock > 0", "risks_and_caveats": "Needs approval",
             "pharmacist_review_required": True}
        ],
        "communication_draft": "Urgent stock needed.",
        "open_questions": [],
    }


SAMPLE_DIR = str(Path(__file__).parent.parent / "data" / "sample")


class TestOrchestrator:
    @patch("orchestrator.recommend_actions")
    @patch("orchestrator.investigate_parallel")
    @patch("orchestrator.generate")
    @patch("orchestrator.analyze_evidence")
    @patch("orchestrator.read_and_profile")
    def test_full_pipeline_returns_result(
        self, mock_reader, mock_analyst, mock_theory,
        mock_investigate, mock_actions, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_reader.return_value = _data_reader_resp("FAC-011", "ORS sachet", "2026-03")
        mock_analyst.return_value = _analyst_resp()
        mock_theory.return_value = _theories_resp()
        mock_investigate.return_value = _evaluations_resp()
        mock_actions.return_value = _actions_resp()

        from orchestrator import StockyWhy
        agent = StockyWhy()
        result = agent.run(
            dataset_dir=SAMPLE_DIR,
            facility_id="FAC-011",
            commodity="ORS sachet",
            month="2026-03",
            interactive=False,
        )

        assert "run_id" in result
        assert "steps" in result
        assert "data_reader" in result["steps"]
        assert "data_analyst" in result["steps"]
        assert "theory_generator" in result["steps"]
        assert "evidence_investigator" in result["steps"]
        assert "action_strategist" in result["steps"]
        assert result["most_likely_cause"] == "demand_surge"

    @patch("orchestrator.recommend_actions")
    @patch("orchestrator.investigate_parallel")
    @patch("orchestrator.generate")
    @patch("orchestrator.analyze_evidence")
    @patch("orchestrator.read_and_profile")
    def test_creates_log_file(
        self, mock_reader, mock_analyst, mock_theory,
        mock_investigate, mock_actions, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_reader.return_value = _data_reader_resp("FAC-001", "test", "2026-03")
        mock_analyst.return_value = _analyst_resp()
        mock_theory.return_value = _theories_resp()
        mock_investigate.return_value = _evaluations_resp()
        mock_actions.return_value = _actions_resp()

        from orchestrator import StockyWhy
        agent = StockyWhy()
        result = agent.run(
            dataset_dir=SAMPLE_DIR,
            facility_id="FAC-001",
            commodity="test",
            month="2026-03",
            log_file="test_run.jsonl",
            interactive=False,
        )
        log_path = tmp_path / "logs" / "test_run.jsonl"
        assert log_path.exists(), "Log file should have been created"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) >= 5  # At least one event per step

    @patch("orchestrator.recommend_actions")
    @patch("orchestrator.investigate_parallel")
    @patch("orchestrator.generate")
    @patch("orchestrator.analyze_evidence")
    @patch("orchestrator.read_and_profile")
    def test_log_file_is_valid_jsonl(
        self, mock_reader, mock_analyst, mock_theory,
        mock_investigate, mock_actions, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_reader.return_value = _data_reader_resp("FAC-001", "test", "2026-03")
        mock_analyst.return_value = _analyst_resp()
        mock_theory.return_value = _theories_resp()
        mock_investigate.return_value = _evaluations_resp()
        mock_actions.return_value = _actions_resp()

        from orchestrator import StockyWhy
        agent = StockyWhy()
        agent.run(
            dataset_dir=SAMPLE_DIR,
            facility_id="FAC-001",
            commodity="test",
            month="2026-03",
            log_file="test_jsonl.jsonl",
            interactive=False,
        )
        log_path = tmp_path / "logs" / "test_jsonl.jsonl"
        for line in log_path.read_text().strip().split("\n"):
            obj = json.loads(line)
            assert "timestamp" in obj
            assert "agent_name" in obj
            assert "status" in obj

    @patch("orchestrator.recommend_actions")
    @patch("orchestrator.investigate_parallel")
    @patch("orchestrator.generate")
    @patch("orchestrator.analyze_evidence")
    @patch("orchestrator.read_and_profile")
    def test_sample_mode_overrides_dataset(
        self, mock_reader, mock_analyst, mock_theory,
        mock_investigate, mock_actions, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SAMPLE_MODE", "true")
        mock_reader.return_value = _data_reader_resp("FAC-001", "test", "2026-03")
        mock_analyst.return_value = _analyst_resp()
        mock_theory.return_value = _theories_resp()
        mock_investigate.return_value = _evaluations_resp()
        mock_actions.return_value = _actions_resp()

        from orchestrator import StockyWhy
        import importlib
        import orchestrator
        importlib.reload(orchestrator)

        agent = orchestrator.StockyWhy()
        result = agent.run(
            dataset_dir="/wrong/path",  # should be ignored
            facility_id="FAC-001",
            commodity="test",
            month="2026-03",
            interactive=False,
        )
        # In SAMPLE_MODE the dataset_dir should be data/sample/
        assert "data/sample" in result.get("dataset_dir", "").replace("\\", "/")

    @patch("orchestrator.read_and_profile")
    def test_data_reader_failure_returns_error(self, mock_reader, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_reader.side_effect = FileNotFoundError("Dataset not found")
        from orchestrator import StockyWhy
        agent = StockyWhy()
        result = agent.run(
            dataset_dir="/nonexistent",
            facility_id="FAC-001",
            commodity="test",
            month="2026-03",
            interactive=False,
        )
        assert "error" in result
        assert "Data Reader" in result["error"]

    @patch("orchestrator.recommend_actions")
    @patch("orchestrator.investigate_parallel")
    @patch("orchestrator.generate")
    @patch("orchestrator.analyze_evidence")
    @patch("orchestrator.read_and_profile")
    def test_actions_have_pharmacist_review_flag(
        self, mock_reader, mock_analyst, mock_theory,
        mock_investigate, mock_actions, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_reader.return_value = _data_reader_resp("FAC-001", "test", "2026-03")
        mock_analyst.return_value = _analyst_resp()
        mock_theory.return_value = _theories_resp()
        mock_investigate.return_value = _evaluations_resp()
        mock_actions.return_value = _actions_resp()

        from orchestrator import StockyWhy
        agent = StockyWhy()
        result = agent.run(
            dataset_dir=SAMPLE_DIR,
            facility_id="FAC-001",
            commodity="test",
            month="2026-03",
            interactive=False,
        )
        for action in result.get("actions", []):
            assert action.get("pharmacist_review_required") is True


# ---------------------------------------------------------------------------
# CLI tests (run.py)
# ---------------------------------------------------------------------------

class TestCLI:
    """Test that run.py CLI parses arguments correctly and rejects invalid input."""

    def _run_cli(self, args: list, env=None) -> subprocess.CompletedProcess:
        """Run run.py as a subprocess."""
        cmd = [sys.executable, "run.py"] + args
        my_env = os.environ.copy()
        if env:
            my_env.update(env)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
            env=my_env,
            timeout=10,
        )

    def test_help_shows_banner(self):
        result = self._run_cli(["help"])
        assert result.returncode == 0
        assert "StockyWhy" in result.stdout or "STOCKYWHY" in result.stdout.upper()

    def test_missing_required_args_exits_nonzero(self):
        result = self._run_cli(["--dataset", "data/sample"])
        assert result.returncode != 0
        assert "missing" in result.stdout.lower() or "error" in result.stdout.lower()

    def test_nonexistent_dataset_exits_nonzero(self):
        """Without mocking, a nonexistent dataset should fail gracefully."""
        result = self._run_cli([
            "--dataset", "/nonexistent/path",
            "--facility", "FAC-001",
            "--commodity", "ORS sachet",
            "--month", "2026-03",
            "--no-review",
        ])
        # Should exit with error, not crash with traceback
        assert result.returncode != 0
        assert "Traceback" not in result.stdout

    def test_help_flag_works(self):
        result = self._run_cli(["--help"])
        assert result.returncode == 0
        assert "--dataset" in result.stdout
        assert "--facility" in result.stdout

    def test_env_example_has_placeholders(self):
        """The .env.example file should exist with the right keys."""
        env_example = Path(__file__).parent.parent / ".env.example"
        assert env_example.exists()
        content = env_example.read_text()
        assert "GROQ_API_KEY" in content
        assert "GROQ_MODEL" in content
        # Must not contain real keys
        assert "gsk_" not in content  # Groq keys start with gsk_
