
"""
tests/test_orchestrator.py

Tests for the StockWhy orchestrator pipeline.
All LLM calls mocked. No real API calls made.
"""

import sys
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Shared mock responses
# ---------------------------------------------------------------------------

def _data_reader_resp(facility, commodity, month):
    return {
        "facility_id": facility,
        "commodity": commodity,
        "month": month,
        "evidence": {
            "dataset_summary": {
                "stock_rows": 1,
                "order_rows": 1,
                "history_months_available": 3,
                "has_payment_records": True,
                "has_web_notes": False,
            },
            "relevant_records": {
                "stock_ids": ["stock#1"],
                "order_ids": ["orders#1"],
                "payment_months": [],
            },
            "data_quality_flags": [],
            "evidence_for_hypotheses": {
                "h1_late_order": "late",
                "h2_supplier_underfill": "no",
                "h3_payment_arrears": "no",
                "h4_demand_surge": "strong",
                "h5_record_error": "ok",
                "h6_expiry": "no",
                "h7_national_disruption": "no",
            },
            "missing_data_warnings": [],
        },
        "computed_evidence": {
            "h1_late_order": {"late": False},
            "h2_supplier_underfill": {"underfill": False},
            "h3_payment_arrears": {"major_arrears": False},
            "h4_demand_surge": {"surge": True},
            "h5_record_error": {"identity_holds": True},
            "h6_expiry": {"high_wastage": False},
            "h7_national_disruption": {"web_notice_found": False},
        },
        "data_quality": [],
        "missing_data_warnings": [],
        "_profile": {},
    }


def _analyst_resp():
    return {
        "analysis_summary": "Strong demand surge.",
        "hypothesis_signals": {"h4_demand_surge": "strong"},
        "data_quality_issues": [],
        "observed_patterns": [],
        "evidence_gaps": [],
        "recommended_tests": [],
    }


def _theories_resp():
    names = [
        "late_order",
        "supplier_underfill",
        "payment_arrears",
        "demand_surge",
        "record_error",
        "expiry",
        "national_disruption",
    ]

    return {
        "theories": [
            {
                "id": f"H{i}",
                "hypothesis_name": name,
                "title": f"Theory {i}",
                "mechanism": "mech",
                "evidence_needed": [],
                "disconfirming_evidence": [],
                "predictions": [],
            }
            for i, name in enumerate(names, 1)
        ]
    }


def _evaluations_resp():
    names = [
        "late_order",
        "supplier_underfill",
        "payment_arrears",
        "demand_surge",
        "record_error",
        "expiry",
        "national_disruption",
    ]

    return {
        "evaluations": [
            {
                "theory_id": f"H{i}",
                "hypothesis_name": name,
                "verdict": "inconclusive",
                "supporting_evidence_ids": [],
                "contradicting_evidence_ids": [],
                "reasoning": "Test",
                "limitations": [],
                "additional_analysis_needed": [],
            }
            for i, name in enumerate(names, 1)
        ],
        "analysis_requests": [],
    }


def _actions_resp():
    return {
        "most_likely_cause": "demand_surge",
        "ranked_hypotheses": [
            {
                "hypothesis_id": "H4",
                "hypothesis_name": "demand_surge",
                "verdict": "supported",
                "likelihood": "high",
            }
        ],
        "actions": [
            {
                "action_id": "A1",
                "action": "Submit emergency req.",
                "linked_theory_ids": ["H4"],
                "evidence_basis": "Demand spike",
                "priority": "high",
                "proposed_owner": "Pharmacist",
                "timeframe": "24h",
                "expected_outcome": "Stock restored",
                "success_measure": "Stock > 0",
                "risks_and_caveats": "Needs approval",
                "pharmacist_review_required": True,
            }
        ],
        "communication_draft": "Urgent stock needed.",
        "open_questions": [],
    }


SAMPLE_DIR = str(Path(__file__).parent.parent / "data" / "sample")


# ---------------------------------------------------------------------------
# Orchestrator tests
# ---------------------------------------------------------------------------

class TestOrchestrator:

    @patch("orchestrator.recommend_actions")
    @patch("orchestrator.investigate_parallel")
    @patch("orchestrator.generate")
    @patch("orchestrator.analyze_evidence")
    @patch("orchestrator.read_and_profile")
    def test_full_pipeline_returns_result(
        self,
        mock_reader,
        mock_analyst,
        mock_theory,
        mock_investigate,
        mock_actions,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_reader.return_value = _data_reader_resp(
            "FAC-011", "ORS sachet", "2026-03"
        )
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
        self,
        mock_reader,
        mock_analyst,
        mock_theory,
        mock_investigate,
        mock_actions,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_reader.return_value = _data_reader_resp(
            "FAC-001", "test", "2026-03"
        )
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
            log_file="test_run.jsonl",
            interactive=False,
        )

        log_path = tmp_path / "logs" / "test_run.jsonl"
        assert log_path.exists(), "Log file should have been created"

        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 5

    @patch("orchestrator.recommend_actions")
    @patch("orchestrator.investigate_parallel")
    @patch("orchestrator.generate")
    @patch("orchestrator.analyze_evidence")
    @patch("orchestrator.read_and_profile")
    def test_log_file_is_valid_jsonl(
        self,
        mock_reader,
        mock_analyst,
        mock_theory,
        mock_investigate,
        mock_actions,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_reader.return_value = _data_reader_resp(
            "FAC-001", "test", "2026-03"
        )
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
        assert log_path.exists()

        for line in log_path.read_text(encoding="utf-8").strip().splitlines():
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
        self,
        mock_reader,
        mock_analyst,
        mock_theory,
        mock_investigate,
        mock_actions,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SAMPLE_MODE", "true")

        mock_reader.return_value = _data_reader_resp(
            "FAC-001", "test", "2026-03"
        )
        mock_analyst.return_value = _analyst_resp()
        mock_theory.return_value = _theories_resp()
        mock_investigate.return_value = _evaluations_resp()
        mock_actions.return_value = _actions_resp()

        # Do not reload orchestrator here. Reloading discards the patched
        # functions and can accidentally trigger real Nightshift API calls.
        from orchestrator import StockyWhy

        agent = StockyWhy()
        result = agent.run(
            dataset_dir="/wrong/path",
            facility_id="FAC-001",
            commodity="test",
            month="2026-03",
            interactive=False,
        )

        assert "data/sample" in result.get(
            "dataset_dir", ""
        ).replace("\\", "/")

    @patch("orchestrator.read_and_profile")
    def test_data_reader_failure_returns_error(
        self, mock_reader, tmp_path, monkeypatch
    ):
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
        self,
        mock_reader,
        mock_analyst,
        mock_theory,
        mock_investigate,
        mock_actions,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_reader.return_value = _data_reader_resp(
            "FAC-001", "test", "2026-03"
        )
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
# CLI tests
# ---------------------------------------------------------------------------

class TestCLI:
    """Test that run.py CLI parses arguments and rejects invalid input."""

    def _run_cli(self, args: list, env=None) -> subprocess.CompletedProcess:
        """Run run.py as a subprocess with explicit UTF-8 decoding."""
        cmd = [sys.executable, "run.py"] + args
        my_env = os.environ.copy()

        if env:
            my_env.update(env)

        my_env.setdefault("PYTHONIOENCODING", "utf-8")

        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(Path(__file__).parent.parent),
            env=my_env,
            timeout=30,
        )

    def test_help_shows_banner(self):
        result = self._run_cli(["help"])
        assert result.returncode == 0
        assert (
            "StockyWhy" in result.stdout
            or "STOCKYWHY" in result.stdout.upper()
        )

    def test_missing_required_args_exits_nonzero(self):
        result = self._run_cli(["--dataset", "data/sample"])
        assert result.returncode != 0
        output = (result.stdout or "") + (result.stderr or "")
        assert "missing" in output.lower() or "error" in output.lower()

    def test_nonexistent_dataset_exits_nonzero(self):
        """A nonexistent dataset should fail without an uncaught traceback."""
        result = self._run_cli([
            "--dataset", "/nonexistent/path",
            "--facility", "FAC-001",
            "--commodity", "ORS sachet",
            "--month", "2026-03",
            "--no-review",
        ])

        output = (result.stdout or "") + (result.stderr or "")
        assert result.returncode != 0
        assert "Traceback" not in output

    def test_help_flag_works(self):
        result = self._run_cli(["--help"])
        assert result.returncode == 0
        assert "--dataset" in result.stdout
        assert "--facility" in result.stdout

    def test_env_example_has_provider_configuration(self):
        """The example environment file should document provider settings."""
        env_example = Path(__file__).parent.parent / ".env.example"
        assert env_example.exists()

        content = env_example.read_text(encoding="utf-8")

        # Support the current Nightshift configuration or a legacy example.
        has_nightshift = (
            "METERLESS_BASE_URL" in content
            and "METERLESS_RUNTIME_TOKEN" in content
        )
        has_legacy_groq = (
            "GROQ_API_KEY" in content
            and "GROQ_MODEL" in content
        )

        assert has_nightshift or has_legacy_groq
        assert "gsk_" not in content
