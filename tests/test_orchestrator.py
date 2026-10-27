
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
    def test_nemotron_served_model_is_recordable_per_investigation_call(self):
        from orchestrator import _log_model_fields

        metadata = _log_model_fields({
            "evaluations": [
                {
                    "theory_id": "H1",
                    "_provider": "Meterless Nightshift",
                    "_requested_model": "meterless/auto",
                    "_served_model": "nvidia/nemotron-3.5-lightning-30b-a3b",
                    "_reasoning_content": "verifies the computed signal",
                },
                {
                    "theory_id": "H2",
                    "_provider": "Meterless Nightshift",
                    "_requested_model": "meterless/auto",
                    "_served_model": "nvidia/nemotron-3.5-lightning-30b-a3b",
                },
            ]
        })

        assert metadata["provider"] == "Meterless Nightshift"
        assert metadata["model"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
        assert [
            call["hypothesis_id"] for call in metadata["llm_requests"]
        ] == ["H1", "H2"]
        assert all(
            call["served_model"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
            for call in metadata["llm_requests"]
        )
        assert "reasoning_content" not in metadata["llm_requests"][0]

    @patch("orchestrator.recommend_actions", return_value=_actions_resp())
    @patch("orchestrator.investigate_parallel")
    @patch("orchestrator.generate", return_value=_theories_resp())
    @patch("orchestrator.analyze_evidence", return_value=_analyst_resp())
    @patch("orchestrator.read_and_profile")
    def test_investigator_fallback_is_logged_as_non_live(
        self,
        mock_reader,
        mock_analyst,
        mock_theory,
        mock_investigator,
        mock_actions,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_reader.return_value = _data_reader_resp(
            "FAC-011", "ORS sachet", "2026-03"
        )
        mock_investigator.return_value = {
            "evaluations": [{
                "theory_id": "H1",
                "hypothesis_name": "late_order",
                "verdict": "supported",
                "verdict_source": "deterministic",
                "explanation_source": "local_deterministic_fallback",
                "_provider": "Local deterministic fallback",
                "_requested_model": "meterless/deep",
                "_served_model": None,
                "_request_error_category": "http_error",
                "_request_metadata": {
                    "provider": "Meterless Nightshift",
                    "requested_model": "meterless/deep",
                    "served_model": None,
                    "endpoint": "http://localhost:8088/v1/chat/completions",
                    "http_status": 503,
                    "duration_ms": 15.2,
                    "request_outcome": "http_error",
                    "request_attempted": True,
                    "response_received": True,
                    "response_parsed": False,
                    "correlation_id": "test-correlation-id",
                    "error_category": "http_error",
                },
            }],
            "analysis_requests": [],
        }

        from orchestrator import StockyWhy

        result = StockyWhy().run(
            dataset_dir=SAMPLE_DIR,
            facility_id="FAC-011",
            commodity="ORS sachet",
            month="2026-03",
            interactive=False,
        )

        assert "error" not in result
        entries = [
            json.loads(line)
            for line in (tmp_path / "logs" / result["log_file"])
            .read_text(encoding="utf-8").splitlines()
        ]
        hypothesis = next(
            entry for entry in entries
            if entry.get("action") == "investigate_hypothesis"
        )
        assert hypothesis["hypothesis_id"] == "H1"
        assert hypothesis["status"] == "warning"
        assert hypothesis["explanation_source"] == "local_deterministic_fallback"
        assert hypothesis["provider"] == "Local deterministic fallback"
        assert hypothesis["request_metadata"]["request_outcome"] == "http_error"
        aggregate = next(
            entry for entry in entries
            if entry.get("action") == "investigate_parallel"
        )
        assert aggregate["status"] == "warning"

    def test_sample_mode_runs_full_pipeline_without_external_services(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SAMPLE_MODE", "true")
        monkeypatch.setenv("STOCKWHY_DATA_SOURCE", "zetaris")
        monkeypatch.setenv("METERLESS_BASE_URL", "")
        monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "")

        from orchestrator import StockyWhy

        result = StockyWhy().run(
            dataset_dir="/nonexistent/path",
            facility_id="FAC-011",
            commodity="ORS sachet",
            month="2026-03",
            interactive=False,
        )

        capsys.readouterr()
        assert "error" not in result
        assert set(result["steps"]) == {
            "data_reader",
            "data_analyst",
            "theory_generator",
            "evidence_investigator",
            "action_strategist",
        }
        assert result["steps"]["data_reader"]["evidence"]["_provider"] == (
            "StockWhy offline sample provider"
        )
        assert result["steps"]["evidence_investigator"]["evaluations"]
        assert result["actions"]
        assert all(
            item["likelihood"] == "not assessed (offline)"
            for item in result["ranked_hypotheses"]
        )
        assert all(
            action["pharmacist_review_required"]
            for action in result["actions"]
        )
        log_entries = [
            json.loads(line)
            for line in (tmp_path / "logs" / result["log_file"]).read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        assert any(
            entry.get("provider") == "StockWhy offline sample provider"
            for entry in log_entries
        )

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

    @patch("orchestrator.generate", side_effect=RuntimeError(
        "Nightshift returned unusable JSON"
    ))
    @patch("orchestrator.analyze_evidence", return_value=_analyst_resp())
    @patch("orchestrator.read_and_profile")
    def test_theory_generator_json_failure_returns_stage_error(
        self, mock_reader, mock_analyst, mock_theory, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_reader.return_value = _data_reader_resp(
            "FAC-011", "ORS sachet", "2026-03"
        )

        from orchestrator import StockyWhy

        result = StockyWhy().run(
            dataset_dir=SAMPLE_DIR,
            facility_id="FAC-011",
            commodity="ORS sachet",
            month="2026-03",
            interactive=False,
        )

        assert result["error"] == (
            "Theory Generator failed: Nightshift returned unusable JSON"
        )
        assert "theory_generator" not in result["steps"]
        log_entries = [
            json.loads(line)
            for line in (tmp_path / "logs" / result["log_file"])
            .read_text(encoding="utf-8").splitlines()
        ]
        assert log_entries[-1]["status"] == "error"
        assert log_entries[-1]["agent_name"] == "theory_generator"

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

    def _run_cli(self, args: list, env=None, cwd=None) -> subprocess.CompletedProcess:
        """Run run.py as a subprocess with explicit UTF-8 decoding."""
        project_root = Path(__file__).parent.parent
        cmd = [sys.executable, str(project_root / "run.py")] + args
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
            cwd=str(cwd or project_root),
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
        assert "METERLESS_BASE_URL" in result.stdout
        assert "STOCKWHY_DATASET" in result.stdout
        assert "GROQ_API_KEY" not in result.stdout

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

    def test_case_argument_resolves_case_question_and_runs_offline(self, tmp_path):
        project_root = Path(__file__).parent.parent
        case_path = project_root / "data" / "cases" / "normal" / "case_01"
        result = self._run_cli(
            ["--case", str(case_path), "--no-review"],
            env={
                "SAMPLE_MODE": "true",
                "STOCKWHY_DATA_SOURCE": "zetaris",
                "METERLESS_BASE_URL": "",
                "METERLESS_RUNTIME_TOKEN": "",
                "STOCKWHY_WORLD_MODEL_DB": str(tmp_path / "world-model.sqlite3"),
            },
            cwd=tmp_path,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "Facility  : FAC-011" in result.stdout
        assert "Most Likely Cause" in result.stdout

    def test_help_flag_works(self):
        result = self._run_cli(["--help"])
        assert result.returncode == 0
        assert "--dataset" in result.stdout
        assert "--facility" in result.stdout

    def test_stockwhy_dataset_environment_is_used(self, monkeypatch, tmp_path, capsys):
        import run

        captured = {}

        class FakeStockyWhy:
            def run(self, **kwargs):
                captured.update(kwargs)
                return {
                    "facility_id": kwargs["facility_id"],
                    "commodity": kwargs["commodity"],
                    "month": kwargs["month"],
                    "run_id": "test",
                    "most_likely_cause": "inconclusive",
                    "log_file": "test.jsonl",
                    "actions": [],
                }

        monkeypatch.setenv("SAMPLE_MODE", "false")
        monkeypatch.setenv("STOCKWHY_DATASET", str(tmp_path))
        monkeypatch.setattr("orchestrator.StockyWhy", FakeStockyWhy)
        monkeypatch.setattr(
            "sys.argv",
            [
                "run.py", "--facility", "FAC-001", "--commodity", "test",
                "--month", "2026-03", "--no-review",
            ],
        )

        run.main()
        capsys.readouterr()
        assert captured["dataset_dir"] == str(tmp_path)

    def test_env_example_has_provider_configuration(self):
        """The example environment file should document provider settings."""
        env_example = Path(__file__).parent.parent / ".env.example"
        assert env_example.exists()

        content = env_example.read_text(encoding="utf-8")

        assert "METERLESS_BASE_URL" in content
        assert "METERLESS_RUNTIME_TOKEN" in content
        assert "ZETARIS_REST_URL" in content
        assert "ZETARIS_API_KEY" in content
        assert "STOCKWHY_DATASET" in content
        assert "GROQ_API_KEY" not in content
        assert "NVIDIA_API_KEY" not in content
