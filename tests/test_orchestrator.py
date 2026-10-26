"""
tests/test_orchestrator.py

Tests for the StockWhy orchestrator loop and the run.py entry points.
Every agent, engine and LLM call is a fake. No network.
"""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from orchestrator import StockyWhy  # noqa: E402
from tests.test_evaluator import FAC, MED, MONTH, make_dataset, make_evidence  # noqa: E402

ROOT = Path(__file__).parent.parent
SAMPLE_DIR = str(ROOT / "data" / "sample")
NAMES = ["late_order", "supplier_underfill", "payment_arrears", "demand_surge",
         "record_error", "expiry", "national_disruption"]
LOG_FIELDS = {"timestamp", "run_id", "agent_name", "action", "input_summary", "output_summary",
              "target_agent", "model", "confidence", "retry_count", "status"}


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeContract:
    def __init__(self, caps, child_caps=None, id="c-main"):
        self.caps, self.child_caps, self.id = set(caps), child_caps, id
        self.children = []

    def check(self, capability):
        if capability not in self.caps:
            raise PermissionError(f"capability '{capability}' is not granted")

    def child(self, intent, capabilities):
        caps = self.child_caps if self.child_caps is not None else capabilities
        c = FakeContract(caps, id="c-child")
        self.children.append((intent, set(capabilities)))
        return c

    def to_dict(self):
        return {"id": self.id, "capabilities": sorted(self.caps)}


ALL_CAPS = {"data.read", "llm.call", "memory.read", "memory.write", "action.draft"}


class FakeScout:
    def __init__(self, decision="allow", contract=None, params=None, reason="ok"):
        self.decision, self.contract, self.params, self.reason = decision, contract, params, reason
        self.requests = []

    def gate(self, request, dataset):
        self.requests.append(request)
        return {"decision": self.decision, "intent": "stockout.explain", "band": "high",
                "reason": self.reason, "contract": self.contract if self.decision == "allow" else None,
                "params": self.params or {}, "suggestions": {}, "trace": {}}


class FakeMemory:
    def __init__(self, prior=None):
        self.prior = prior or []
        self.stored, self.feedbacks = [], []

    def recall(self, facility_id, commodity, limit=5):
        return list(self.prior)

    def store(self, finding, citations, run_id):
        if not citations:
            raise ValueError("no citations")
        self.stored.append((finding, citations, run_id))
        return "mem-1"

    def feedback(self, memory_id, decision, note=""):
        self.feedbacks.append((memory_id, decision, note))
        return {"id": memory_id, "status": decision}


class Agents:
    """Fake agents patched into the orchestrator module."""

    def __init__(self, evidence=None, verdicts=None, retry_verdicts=None, signals=None):
        self.evidence = evidence or make_evidence()
        self.verdicts = verdicts or {"H1": "supported"}
        self.retry_verdicts = retry_verdicts
        self.signals = signals or {}
        self.investigate_calls = []
        self.reader_calls = 0
        self.strategist_input = None

    def read_and_profile(self, dataset_dir, facility_id, commodity, month):
        self.reader_calls += 1
        return {"facility_id": facility_id, "commodity": commodity, "month": month,
                "evidence": {"_produced_by": "rule-based"}, "computed_evidence": self.evidence,
                "data_quality": [], "missing_data_warnings": [], "_profile": {}}

    def analyze_evidence(self, computed_evidence, question):
        return {"analysis_summary": "test", "hypothesis_signals": self.signals,
                "_produced_by": "rule-based"}

    def generate(self, question, analysis):
        return {"theories": [{"id": f"H{i}", "hypothesis_name": n, "title": n}
                             for i, n in enumerate(NAMES, 1)], "_produced_by": "rule-based"}

    def investigate_parallel(self, question, theories, computed_evidence):
        batch = theories["theories"]
        self.investigate_calls.append(batch)
        revising = any(t.get("revision_request") for t in batch)
        table = self.retry_verdicts if (revising and self.retry_verdicts) else self.verdicts
        return {"evaluations": [
            {"theory_id": t["id"], "hypothesis_name": t["hypothesis_name"],
             "verdict": table.get(t["id"], "weakened"), "supporting_evidence_ids": [],
             "contradicting_evidence_ids": [], "reasoning": "fake",
             "_produced_by": "rule-based"} for t in batch
        ], "analysis_requests": []}

    def recommend_actions(self, question, evaluations):
        self.strategist_input = evaluations
        supported = [e["theory_id"] for e in evaluations["evaluations"] if e["verdict"] == "supported"]
        top = supported[0] if supported else "H1"
        return {
            "most_likely_cause": f"{top} cause",
            "ranked_hypotheses": [{"hypothesis_id": e["theory_id"], "hypothesis_name": e["hypothesis_name"],
                                   "verdict": e["verdict"], "likelihood": "high"}
                                  for e in evaluations["evaluations"]],
            "actions": [
                {"action_id": "A1", "action": "Emergency requisition", "linked_hypothesis_ids": [top],
                 "priority": "high", "pharmacist_review_required": False},
                {"action_id": "A2", "action": "Chase supplier", "linked_hypothesis_ids": ["H2"],
                 "priority": "low"},
            ],
            "_produced_by": "rule-based",
        }

    def install(self, monkeypatch):
        for name in ("read_and_profile", "analyze_evidence", "generate",
                     "investigate_parallel", "recommend_actions"):
            monkeypatch.setattr(orchestrator, name, getattr(self, name))
        return self


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STOCKWHY_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("STOCKWHY_USE_LLM", "false")
    for var in ("SAMPLE_MODE", "STOCKWHY_INJECT_FAULT", "METERLESS_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    return tmp_path


def _run(agent=None, log_file="t.jsonl", **kw):
    agent = agent or StockyWhy(scout=FakeScout(contract=FakeContract(ALL_CAPS)), memory=FakeMemory(),
                               loader=lambda d: make_dataset())
    return agent.run(dataset_dir=kw.pop("dataset_dir", SAMPLE_DIR), facility_id=FAC, commodity=MED,
                     month=MONTH, log_file=log_file, interactive=kw.pop("interactive", False), **kw)


def _log(tmp_path, name="t.jsonl"):
    path = tmp_path / "logs" / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _actions(records):
    return [r["action"] for r in records]


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

class TestLoop:

    def test_happy_path_cites_verified_rows(self, env, monkeypatch):
        fake = Agents().install(monkeypatch)
        result = _run()
        assert result["status"] == "complete"
        assert result["verified_cause"]["hypothesis_id"] == "H1"
        assert result["verified_cause"]["citations"] == ["orders#3161"]
        assert result["most_likely_cause"] == "H1 cause"
        for key in ("data_reader", "data_analyst", "theory_generator",
                    "evidence_investigator", "action_strategist"):
            assert key in result["steps"]
        # A2 was linked only to an unsupported hypothesis: removed.
        assert [a["action_id"] for a in result["actions"]] == ["A1"]
        assert result["removed_actions"] == ["A2"]
        for a in result["actions"]:
            assert a["pharmacist_review_required"] is True
            assert a["verified_citations"] == ["orders#3161"]
        assert result["medical_disclaimer"]
        # Strategist only saw evaluations the Evaluator verified.
        assert all(e.get("verified_citations") is not None
                   for e in fake.strategist_input["evaluations"])

    def test_fault_drill_caught_and_recovered(self, env, monkeypatch):
        monkeypatch.setenv("STOCKWHY_INJECT_FAULT", "H1")
        fake = Agents().install(monkeypatch)
        result = _run()
        drill = result["fault_drill"]
        assert drill["injected"] and drill["caught"] and drill["recovered"]
        assert result["verified_cause"]["hypothesis_id"] == "H1"
        assert len(fake.investigate_calls) == 2
        retry_batch = fake.investigate_calls[1]
        assert [t["id"] for t in retry_batch] == ["H1"]
        assert "orders#3161" in retry_batch[0]["evaluator_critique"]

        records = _log(env)
        acts = _actions(records)
        for name in ("inject_fault", "verify_citations", "request_revision",
                     "retry_investigation", "accept_revision"):
            assert name in acts
        first_check = next(r for r in records if r["action"] == "verify_citations")
        assert first_check["status"] == "warning" and first_check["retry_count"] == 0
        retry = next(r for r in records if r["action"] == "retry_investigation")
        assert retry["retry_count"] == 1 and retry["target_agent"] == "evaluator"
        revision = next(r for r in records if r["action"] == "request_revision")
        assert revision["agent_name"] == "evaluator"
        assert revision["target_agent"] == "evidence_investigator"

    def test_consistency_rejection_drops_claim(self, env, monkeypatch):
        # Investigator insists on a demand surge the flags do not show.
        fake = Agents(verdicts={"H1": "supported", "H4": "supported"},
                      signals={"H4": {"signal": "weak"}}).install(monkeypatch)
        result = _run()
        assert [d["hypothesis_id"] for d in result["dropped_claims"]] == ["H4"]
        assert "H4" not in result["verified_citations"]
        assert result["verified_cause"]["hypothesis_id"] == "H1"
        assert [t["id"] for t in fake.investigate_calls[1]] == ["H4"]  # only H4 re-ran
        records = _log(env)
        cons = [r for r in records if r["action"] == "check_consistency"]
        assert cons[0]["status"] == "warning"
        assert "drop_unverified" in _actions(records)

    def test_cross_critique_revision(self, env, monkeypatch):
        evidence = make_evidence(
            h1_late_order={"late": False, "delivery_slipped": False},
            h4_demand_surge={"surge": True, "pct_change": 60.0},
            h5_record_error={"identity_holds": False, "reported_closing": 30.0,
                             "computed_closing": 0.0, "discrepancy": -30.0},
        )
        fake = Agents(evidence=evidence, verdicts={"H4": "supported", "H5": "supported"}).install(monkeypatch)
        agent = StockyWhy(scout=FakeScout(contract=FakeContract(ALL_CAPS)), memory=FakeMemory(),
                          loader=lambda d: make_dataset(closing=30))
        result = _run(agent)
        h4 = next(e for e in result["steps"]["evidence_investigator"]["evaluations"]
                  if e["theory_id"] == "H4")
        assert h4["verdict"] == "inconclusive" and h4["contested_by"] == ["H5"]
        assert "record" in h4["revised_after_critique"].lower() or "identity" in h4["revised_after_critique"]
        assert result["verified_cause"]["hypothesis_id"] == "H5"
        assert [t["id"] for t in fake.investigate_calls[1]] == ["H4"]
        records = _log(env)
        crit = next(r for r in records if r["action"] == "cross_critique")
        assert "H5->H4" in crit["output_summary"]
        assert "settle_claim" in _actions(records)

    def test_second_wave_then_insufficient_evidence(self, env, monkeypatch):
        evidence = make_evidence(h1_late_order={"late": False, "delivery_slipped": False})
        fake = Agents(evidence=evidence, verdicts={}, signals={"H4": "weak"}).install(monkeypatch)
        memory = FakeMemory()
        agent = StockyWhy(scout=FakeScout(contract=FakeContract(ALL_CAPS)), memory=memory,
                          loader=lambda d: make_dataset())
        result = _run(agent)
        assert [t["id"] for t in fake.investigate_calls[0]] == ["H4"]
        assert sorted(t["id"] for t in fake.investigate_calls[1]) == ["H1", "H2", "H3", "H5", "H6", "H7"]
        assert result["status"] == "insufficient_evidence"
        assert result["escalation"]["to"] == "pharmacist"
        assert result["verified_cause"] is None
        assert fake.strategist_input is None  # no fabricated cause-specific actions
        assert result["actions"][0]["pharmacist_review_required"] is True
        assert memory.stored == []
        acts = _actions(_log(env))
        assert "request_second_pass" in acts and "escalate_to_pharmacist" in acts

    def test_memory_recall_reorders_wave_one_and_store(self, env, monkeypatch):
        fake = Agents().install(monkeypatch)
        memory = FakeMemory(prior=[{"cause": "H6 expiry", "status": "approved"},
                                   {"cause": "H3 payment_arrears", "status": "rejected"}])
        agent = StockyWhy(scout=FakeScout(contract=FakeContract(ALL_CAPS)), memory=memory,
                          loader=lambda d: make_dataset())
        result = _run(agent)
        assert result["wave_plan"]["wave1"][0] == "H6"
        assert "H3" not in result["wave_plan"]["wave1"]  # rejected memory is not a priority
        assert [t["id"] for t in fake.investigate_calls[0]][:2] == ["H6", "H1"]
        finding, citations, run_id = memory.stored[0]
        assert finding["hypothesis_id"] == "H1" and citations == ["orders#3161"]
        assert result["memory"]["stored_status"] == "pending_approval"

    def test_without_memory_wave_one_is_flag_order(self, env, monkeypatch):
        fake = Agents().install(monkeypatch)
        _run()
        assert [t["id"] for t in fake.investigate_calls[0]] == ["H1"]


# ---------------------------------------------------------------------------
# Scout gate and contracts
# ---------------------------------------------------------------------------

class TestGateAndContracts:

    @pytest.mark.parametrize("decision", ["clarify", "refuse", "block"])
    def test_non_allow_short_circuits(self, env, monkeypatch, decision):
        fake = Agents().install(monkeypatch)
        agent = StockyWhy(scout=FakeScout(decision, reason="Which month?"), memory=FakeMemory(),
                          loader=lambda d: make_dataset())
        result = _run(agent)
        assert result["status"] == decision
        assert result["error"].startswith(f"Scout {decision}")
        assert result["message"] == "Which month?"
        assert fake.reader_calls == 0
        acts = _actions(_log(env))
        assert acts[:3] == ["run_start", "load_dataset", "scout_gate"]
        assert acts[-1] == "pipeline_complete"

    def test_gate_params_bind_the_run(self, env, monkeypatch):
        Agents().install(monkeypatch)
        scout = FakeScout(contract=FakeContract(ALL_CAPS), params={"facility_id": FAC, "commodity": MED})
        agent = StockyWhy(scout=scout, memory=False, loader=lambda d: make_dataset())
        result = agent.run(SAMPLE_DIR, "fac 9", "magnesium", MONTH, log_file="t.jsonl", interactive=False)
        assert result["facility_id"] == FAC and result["commodity"] == MED
        assert scout.requests[0]["role"] == "pharmacist"

    def test_missing_data_read_capability(self, env, monkeypatch):
        fake = Agents().install(monkeypatch)
        agent = StockyWhy(scout=FakeScout(contract=FakeContract(ALL_CAPS - {"data.read"})),
                          memory=FakeMemory(), loader=lambda d: make_dataset())
        result = _run(agent)
        assert result["status"] == "error"
        assert "Contract violation" in result["error"] and "data.read" in result["error"]
        assert fake.reader_calls == 0
        assert any(c["result"] == "denied" for c in result["contract_checks"])

    def test_strategist_needs_action_draft_in_child_contract(self, env, monkeypatch):
        fake = Agents().install(monkeypatch)
        contract = FakeContract(ALL_CAPS, child_caps={"data.read"})
        agent = StockyWhy(scout=FakeScout(contract=contract), memory=FakeMemory(),
                          loader=lambda d: make_dataset())
        result = _run(agent)
        assert result["status"] == "error" and "action.draft" in result["error"]
        assert fake.strategist_input is None
        assert contract.children[0][0] == "action.draft"

    def test_child_contract_used_when_granted(self, env, monkeypatch):
        Agents().install(monkeypatch)
        contract = FakeContract(ALL_CAPS)
        agent = StockyWhy(scout=FakeScout(contract=contract), memory=FakeMemory(),
                          loader=lambda d: make_dataset())
        result = _run(agent)
        assert result["status"] == "complete"
        assert contract.children == [("action.draft", {"data.read", "action.draft"})]
        assert result["contracts"]["child"]["id"] == "c-child"
        assert "contract_summary" in _actions(_log(env))

    def test_engines_absent_are_logged_as_skipped(self, env, monkeypatch):
        Agents().install(monkeypatch)
        agent = StockyWhy(scout=False, memory=False, loader=lambda d: make_dataset())
        result = _run(agent)
        assert result["status"] == "complete"
        statuses = {r["action"]: r["status"] for r in _log(env)}
        assert statuses["scout_gate"] == "skipped"
        assert statuses["memory_recall"] == "skipped"
        assert statuses["memory_store"] == "skipped"


# ---------------------------------------------------------------------------
# Logs, errors, review
# ---------------------------------------------------------------------------

class TestLogsErrorsReview:

    def test_every_log_record_has_all_fields(self, env, monkeypatch):
        monkeypatch.setenv("STOCKWHY_INJECT_FAULT", "H1")
        Agents().install(monkeypatch)
        _run()
        records = _log(env)
        assert len(records) >= 12
        for r in records:
            assert LOG_FIELDS <= set(r), (r["action"], LOG_FIELDS - set(r))
            assert isinstance(r["retry_count"], int)
            assert r["model"]
        start = records[0]
        assert start["action"] == "run_start"
        assert start["data_backend"] == "csv" and start["llm_mode"] == "rule-based"
        assert {r["model"] for r in records if r["agent_name"] == "data_analyst"} == {"rule-based"}

    def test_never_prompts_without_tty(self, env, monkeypatch):
        Agents().install(monkeypatch)

        def no_input(*a, **k):
            raise AssertionError("input() must not be called without a TTY")

        monkeypatch.setattr("builtins.input", no_input)
        result = _run(interactive=True)
        assert result["status"] == "complete"
        assert result["approved_actions"] == []

    def test_review_feeds_memory_when_tty(self, env, monkeypatch):
        Agents().install(monkeypatch)
        tty = io.StringIO("")
        tty.isatty = lambda: True
        monkeypatch.setattr(sys, "stdin", tty)
        monkeypatch.setattr("builtins.input", lambda *a, **k: "a")
        memory = FakeMemory()
        agent = StockyWhy(scout=FakeScout(contract=FakeContract(ALL_CAPS)), memory=memory,
                          loader=lambda d: make_dataset())
        result = _run(agent, interactive=True)
        assert len(result["approved_actions"]) == 1
        assert memory.feedbacks[0][:2] == ("mem-1", "approve")
        assert "memory_feedback" in _actions(_log(env))

    def test_dataset_failure_is_one_line_error(self, env, monkeypatch):
        Agents().install(monkeypatch)

        def boom(d):
            raise FileNotFoundError("Dataset directory not found: /nope\nsecond line")

        agent = StockyWhy(scout=False, memory=False, loader=boom)
        result = _run(agent, dataset_dir="/nope")
        assert result["status"] == "error"
        assert result["error"] == "Data Reader failed: Dataset directory not found: /nope"
        assert result["hint"]

    def test_data_reader_failure_returns_error(self, env, monkeypatch):
        fake = Agents().install(monkeypatch)

        def boom(*a):
            raise RuntimeError("Nightshift timed out")

        monkeypatch.setattr(orchestrator, "read_and_profile", boom)
        result = _run()
        assert "Data Reader" in result["error"] and "Traceback" not in result["error"]

    def test_unexpected_exception_never_escapes(self, env, monkeypatch):
        Agents().install(monkeypatch)
        monkeypatch.setattr(orchestrator.evaluator, "check_coverage",
                            lambda *a: (_ for _ in ()).throw(KeyError("x")))
        result = _run()
        assert result["status"] == "error" and result["error"].startswith("StockyWhy failed")

    def test_sample_mode_supplies_default_dataset_only(self, env, monkeypatch):
        monkeypatch.setenv("SAMPLE_MODE", "true")
        Agents().install(monkeypatch)
        seen = []
        agent = StockyWhy(scout=False, memory=False,
                          loader=lambda d: seen.append(d) or make_dataset())
        result = agent.run(None, FAC, MED, MONTH, log_file="t.jsonl", interactive=False)
        assert result["dataset_dir"].replace("\\", "/").endswith("data/sample")
        agent.run("/explicit/path", FAC, MED, MONTH, log_file="t.jsonl", interactive=False)
        assert seen[-1] == "/explicit/path"


# ---------------------------------------------------------------------------
# run.py: --question parsing and the shared JSON request path
# ---------------------------------------------------------------------------

class TestQuestionAndRequests:

    def test_parse_full_question(self):
        import run
        out = run.parse_question("Why did FAC-009 run out of magnesium sulphate in March 2026?",
                                 SAMPLE_DIR)
        assert out == {"facility_id": "FAC-009", "commodity": "magnesium sulphate inj",
                       "month": "2026-03"}

    def test_parse_variants(self):
        import run
        out = run.parse_question("oxytocin stock-out at fac 16 in 2026-02", SAMPLE_DIR)
        assert out == {"facility_id": "FAC-016", "commodity": "oxytocin 10IU inj", "month": "2026-02"}
        out = run.parse_question("Why was FAC-011 out of ORS in Sept 2025?", SAMPLE_DIR)
        assert out["commodity"] == "ORS sachet" and out["month"] == "2025-09"
        out = run.parse_question("FAC-020 magnesium sulfate Mar 2026", SAMPLE_DIR)
        assert out["commodity"] == "magnesium sulphate inj"

    def test_parse_ambiguous_or_missing_clarifies(self):
        import run
        out = run.parse_question("Why did FAC-009 run out of zinc and ORS in March 2026?", SAMPLE_DIR)
        assert out["status"] == "clarify" and "commodity" in out["missing"]
        assert set(out["candidates"]["commodity"]) == {"zinc 20mg tab", "ORS sachet"}
        out = run.parse_question("Why did FAC-009 run out of oxytocin in March?", SAMPLE_DIR)
        assert out["status"] == "clarify" and out["missing"] == ["year"]
        out = run.parse_question("Why did we run out of oxytocin in March 2026?", SAMPLE_DIR)
        assert out["missing"] == ["facility"]

    def test_execute_request_question_and_clarify(self):
        import run

        class FakeAgent:
            def __init__(self):
                self.calls = []

            def run(self, **kw):
                self.calls.append(kw)
                return {"status": "complete", **kw}

        agent = FakeAgent()
        result, code = run.execute_request(
            {"question": "Why did FAC-009 run out of magnesium sulphate in March 2026?"}, agent=agent)
        assert code == 200 and agent.calls[0]["facility_id"] == "FAC-009"
        assert agent.calls[0]["role"] == "pharmacist" and agent.calls[0]["interactive"] is False
        result, code = run.execute_request({"question": "Why did stock run out?"}, agent=agent)
        assert code == 200 and result["status"] == "clarify" and len(agent.calls) == 1
        assert run.exit_code(result) == 0
        result, code = run.execute_request({"facility_id": "FAC-009"}, agent=agent)
        assert code == 400 and result["status"] == "invalid_request"
        result, code = run.execute_request({"question": ["not", "a", "string"]}, agent=agent)
        assert code == 400
        result, code = run.execute_request(
            {"facility": "FAC-001", "commodity": "ORS sachet", "month": "2026-03",
             "dataset": "data/sample"}, agent=agent)
        assert agent.calls[-1]["dataset_dir"] == "data/sample"
        assert run.exit_code({"status": "error"}) == 1
        assert run.exit_code({"status": "insufficient_evidence"}) == 0


# ---------------------------------------------------------------------------
# CLI tests (subprocess; never reach the network)
# ---------------------------------------------------------------------------

class TestCLI:
    """Test that run.py CLI parses arguments and rejects invalid input."""

    def _run_cli(self, args: list, env=None) -> subprocess.CompletedProcess:
        """Run run.py as a subprocess with explicit UTF-8 decoding."""
        cmd = [sys.executable, "run.py"] + args
        my_env = os.environ.copy()
        my_env.pop("METERLESS_BASE_URL", None)
        if env:
            my_env.update(env)
        my_env.setdefault("PYTHONIOENCODING", "utf-8")
        return subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(ROOT), env=my_env, timeout=60,
        )

    def test_help_shows_banner(self):
        result = self._run_cli(["help"])
        assert result.returncode == 0
        assert "STOCKYWHY" in result.stdout.upper()
        assert "--question" in result.stdout
        assert "GROQ" not in result.stdout

    def test_missing_required_args_exits_nonzero(self):
        result = self._run_cli(["--dataset", "data/sample"])
        assert result.returncode != 0
        output = (result.stdout or "") + (result.stderr or "")
        assert "missing" in output.lower() or "error" in output.lower()

    def test_nonexistent_dataset_exits_nonzero(self, tmp_path):
        """A nonexistent dataset should fail without an uncaught traceback, even in sample mode."""
        for env in ({"STOCKWHY_LOGS_DIR": str(tmp_path)},
                    {"STOCKWHY_LOGS_DIR": str(tmp_path), "SAMPLE_MODE": "true"}):
            result = self._run_cli([
                "--dataset", "/nonexistent/path", "--facility", "FAC-001",
                "--commodity", "ORS sachet", "--month", "2026-03", "--no-review",
            ], env=env)
            output = (result.stdout or "") + (result.stderr or "")
            assert result.returncode != 0
            assert "Traceback" not in output

    def test_json_clarify_for_ambiguous_question(self):
        result = self._run_cli(["--question", "Why did FAC-009 run out of medicine?", "--json"])
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "clarify"
        assert "commodity" in payload["missing"] and "month" in payload["missing"]

    def test_input_file_json_errors_are_structured(self, tmp_path):
        bad = tmp_path / "req.json"
        bad.write_text("{not json", encoding="utf-8")
        result = self._run_cli(["--input", str(bad), "--json"])
        assert result.returncode == 1
        assert json.loads(result.stdout)["status"] == "invalid_request"

    def test_help_flag_works(self):
        result = self._run_cli(["--help"])
        assert result.returncode == 0
        for flag in ("--dataset", "--facility", "--question", "--input", "--json"):
            assert flag in result.stdout

    def test_env_example_has_provider_configuration(self):
        """The example environment file should document provider settings."""
        env_example = ROOT / ".env.example"
        assert env_example.exists()
        content = env_example.read_text(encoding="utf-8")
        has_nightshift = "METERLESS_BASE_URL" in content and "METERLESS_RUNTIME_TOKEN" in content
        has_legacy_groq = "GROQ_API_KEY" in content and "GROQ_MODEL" in content
        assert has_nightshift or has_legacy_groq
        assert "gsk_" not in content
