"""
tests/test_logger.py

Tests for the JSONL event logger.
"""

import sys
import json
import os
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from logger import log_event


class TestLogger:
    def test_creates_log_file(self, tmp_path, monkeypatch):
        """log_event should create the logs/ dir and file."""
        monkeypatch.chdir(tmp_path)
        log_event(
            log_file="test_run.jsonl",
            run_id="abc123",
            agent_name="test_agent",
            action="test_action",
            input_summary="input here",
            output_summary="output here",
            status="ok",
        )
        assert (tmp_path / "logs" / "test_run.jsonl").exists()

    def test_valid_jsonl(self, tmp_path, monkeypatch):
        """Each line must be valid JSON."""
        monkeypatch.chdir(tmp_path)
        for i in range(3):
            log_event(
                log_file="run.jsonl",
                run_id="run1",
                agent_name=f"agent_{i}",
                action="action",
                input_summary="in",
                output_summary="out",
                status="ok",
            )
        lines = (tmp_path / "logs" / "run.jsonl").read_text().strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            obj = json.loads(line)
            assert isinstance(obj, dict)

    def test_required_fields(self, tmp_path, monkeypatch):
        """Each log line must contain required fields."""
        monkeypatch.chdir(tmp_path)
        log_event(
            log_file="run.jsonl",
            run_id="run42",
            agent_name="data_reader",
            action="read",
            input_summary="FAC-001/test/2026-03",
            output_summary="ok",
            status="ok",
            model="test-model",
            confidence=0.8,
        )
        line = (tmp_path / "logs" / "run.jsonl").read_text().strip()
        obj = json.loads(line)
        assert obj["run_id"] == "run42"
        assert obj["agent_name"] == "data_reader"
        assert obj["action"] == "read"
        assert obj["input_summary"] == "FAC-001/test/2026-03"
        assert obj["output_summary"] == "ok"
        assert obj["status"] == "ok"
        assert obj["model"] == "test-model"
        assert obj["confidence"] == pytest.approx(0.8)
        assert obj["target_agent"] is None
        assert obj["retry_count"] == 0
        assert "timestamp" in obj

    def test_timestamp_iso_format(self, tmp_path, monkeypatch):
        """Timestamp must be a parseable ISO 8601 string."""
        from datetime import datetime
        monkeypatch.chdir(tmp_path)
        log_event(
            log_file="run.jsonl",
            run_id="r1",
            agent_name="a",
            action="x",
            input_summary="i",
            output_summary="o",
            status="ok",
        )
        line = (tmp_path / "logs" / "run.jsonl").read_text().strip()
        obj = json.loads(line)
        # Should be parseable
        ts = datetime.fromisoformat(obj["timestamp"].replace("Z", "+00:00"))
        assert ts is not None

    def test_appends_multiple_events(self, tmp_path, monkeypatch):
        """Multiple calls must append, not overwrite."""
        monkeypatch.chdir(tmp_path)
        for i in range(5):
            log_event(
                log_file="multi.jsonl",
                run_id="r1",
                agent_name="a",
                action=f"step_{i}",
                input_summary="i",
                output_summary="o",
                status="ok",
            )
        content = (tmp_path / "logs" / "multi.jsonl").read_text().strip()
        lines = content.split("\n")
        assert len(lines) == 5

    def test_error_status(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        log_event(
            log_file="run.jsonl",
            run_id="r1",
            agent_name="a",
            action="x",
            input_summary="i",
            output_summary="error occurred",
            status="error",
        )
        obj = json.loads((tmp_path / "logs" / "run.jsonl").read_text().strip())
        assert obj["status"] == "error"

    def test_kwargs_included(self, tmp_path, monkeypatch):
        """Extra kwargs should appear in the log entry."""
        monkeypatch.chdir(tmp_path)
        log_event(
            log_file="run.jsonl",
            run_id="r1",
            agent_name="a",
            action="x",
            input_summary="i",
            output_summary="o",
            status="ok",
            retry_count=2,
            target_agent="theory_generator",
        )
        obj = json.loads((tmp_path / "logs" / "run.jsonl").read_text().strip())
        assert obj["retry_count"] == 2
        assert obj["target_agent"] == "theory_generator"
