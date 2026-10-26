"""
orchestrator.py

StockyWhy orchestrator: runs the agents as a loop with a checker in the middle,
not as a straight A -> B -> C chain.

  Scout gate        -> allow / clarify / refuse / block (early result if not allow)
  Memory recall     -> prior findings for this facility + medicine set wave-1 priority
  Data Reader       -> load + profile (needs contract capability "data.read")
  Data Analyst      -> signal per hypothesis
  Theory Generator  -> 7 theories
  Investigators     -> wave 1: hypotheses with a signal or memory priority
  Evaluator         -> citations re-read from the dataset, verdict vs flags, cross-critique
     -> failed investigator re-runs ONCE with the critique (retry_count=1)
     -> anything still unverified is dropped
     -> coverage: no verified cause? wave 2 on held-back hypotheses; still none?
        "insufficient evidence", escalate to the pharmacist
  Action Strategist -> drafts actions under a child contract "action.draft"
  Memory store      -> finding saved as pending_approval
  Pharmacist review -> optional, terminal only; decision fed back to memory

Every step writes one JSONL event (logger.log_event) with agent_name, action,
target_agent, model, confidence, retry_count and status.
"""

import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

from logger import log_event
from agents.data_reader import read_and_profile
from agents.data_analyst import analyze_evidence
from agents.theory_generator import generate
from agents.evidence_investigator import investigate_parallel
from agents.action_strategist import recommend_actions
from agents import evaluator
from tools.data_loader import load_dataset
import llm_client


MEDICAL_DISCLAIMER = (
    "This system provides decision-support information only. It does not "
    "constitute medical advice, clinical guidance, or authorisation to act. "
    "All proposed actions must be reviewed and approved by a qualified "
    "pharmacist or supply-chain officer before implementation."
)

_TRUE = {"1", "true", "yes", "on"}


def _sample_mode() -> bool:
    return os.environ.get("SAMPLE_MODE", "false").strip().lower() == "true"


def llm_enabled() -> bool:
    """STOCKWHY_USE_LLM wins when set; otherwise the LLM is used unless SAMPLE_MODE."""
    shared = getattr(llm_client, "llm_enabled", None)
    if callable(shared):
        return bool(shared())
    flag = os.environ.get("STOCKWHY_USE_LLM")
    if flag is not None and flag.strip():
        return flag.strip().lower() in _TRUE
    return not _sample_mode()


def _one_line(exc) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text.splitlines()[0][:300]


def _model_of(output, llm_mode: bool) -> str:
    """Which model produced an agent output (llm_client metadata), else the mode."""
    candidates = [output] if isinstance(output, dict) else []
    if isinstance(output, dict) and isinstance(output.get("evaluations"), list):
        candidates += [e for e in output["evaluations"] if isinstance(e, dict)]
    for item in candidates:
        for key in ("_produced_by", "_served_model", "_requested_model"):
            if item.get(key):
                return str(item[key])
    return "unreported" if llm_mode else "rule-based"


def _confidence_of(output):
    value = output.get("confidence") if isinstance(output, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1:
        return float(value)
    return None


def _mean(values):
    nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return round(sum(nums) / len(nums), 2) if nums else None


def _share_decided(evals):
    if not evals:
        return None
    return round(sum(1 for e in evals if e.get("verdict") != "inconclusive") / len(evals), 2)


def _default_scout():
    try:
        from engines import scout_intent
        return scout_intent
    except Exception:
        return None


def _default_memory():
    try:
        from engines.hmem import CaseMemory
        path = os.environ.get("STOCKWHY_MEMORY_PATH", "logs/memory/hmem.json")
        return CaseMemory(path)
    except Exception:
        return None


def _inject_fault(evaluation: dict) -> str:
    """Fault drill: corrupt one cited value (first pass only) so the Evaluator must catch it."""
    claims = evaluation.get("cited_values") or {}
    for rid, fields in claims.items():
        for field, value in fields.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                bad = round(value + 0.25, 4) if abs(value) <= 1 else value + max(1, abs(value) * 0.5)
                fields[field] = bad
                return f"{rid}.{field} changed from {value} to {bad}"
            if isinstance(value, str) and value:
                fields[field] = "1900-01-01"
                return f"{rid}.{field} changed from {value!r} to '1900-01-01'"
    fake = "stock#999999"
    evaluation["supporting_evidence_ids"] = list(evaluation.get("supporting_evidence_ids") or []) + [fake]
    return f"added a citation to a row that does not exist ({fake})"


class ContractDenied(Exception):
    """A step tried to act without the capability its contract grants."""


class _Run:
    """Per-run state: ids, log file, trace, contract checks."""

    def __init__(self, run_id, log_file, llm_mode):
        self.run_id = run_id
        self.log_file = log_file
        self.llm_mode = llm_mode
        self.trace = []
        self.contract_checks = []
        self.child_contract = None

    def log(self, agent, action, input_summary, output_summary, *, target="none",
            model=None, confidence=None, retry=0, status="ok", **extra):
        log_event(
            log_file=self.log_file,
            run_id=self.run_id,
            agent_name=agent,
            action=action,
            input_summary=input_summary,
            output_summary=output_summary,
            model=model or "none",
            confidence=confidence,
            status=status,
            target_agent=target,
            retry_count=retry,
            **extra,
        )
        self.trace.append({
            "agent": agent, "action": action, "target_agent": target,
            "retry_count": retry, "status": status, "summary": str(output_summary)[:200],
        })


class StockyWhy:
    """
    Main investigation orchestrator.

    scout  : object with gate(request, dataset) (default: engines.scout_intent if
             importable). Pass False to switch the gate off.
    memory : object with recall/store/feedback (default: engines.hmem.CaseMemory
             if importable). Pass False to switch memory off.
    loader : callable(dataset_dir) -> dataset dict (default: tools.data_loader.load_dataset)
    """

    def __init__(self, scout=None, memory=None, loader=None):
        self.scout = _default_scout() if scout is None else (scout or None)
        self.memory = _default_memory() if memory is None else (memory or None)
        self.loader = loader or load_dataset

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def run(
        self,
        dataset_dir: str,
        facility_id: str,
        commodity: str,
        month: str,
        log_file: str = None,
        interactive: bool = True,
        question: str = None,
        role: str = "pharmacist",
    ) -> dict:
        """
        Run the full StockyWhy investigation.

        Parameters
        ----------
        dataset_dir  : path to the dataset folder (CSV/JSON files)
        facility_id  : e.g. "FAC-011"
        commodity    : e.g. "ORS sachet"
        month        : e.g. "2026-03"
        log_file     : JSONL filename in logs/ (auto-generated if None)
        interactive  : if True and stdin is a terminal, prompt the pharmacist
        question     : the user's own wording (optional; passed to the Scout gate)
        role         : who is asking (Scout checks it); default "pharmacist"

        Returns
        -------
        Result dict. Never raises: failures come back as
        {"status": "error", "error": "<one line>", "hint": "..."}.
        """
        if not dataset_dir:
            # Sample mode only supplies the default dataset; an explicit path is honoured.
            dataset_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sample")

        Path(os.environ.get("STOCKWHY_LOGS_DIR") or "logs").mkdir(parents=True, exist_ok=True)
        reset = getattr(llm_client, "reset_call_budget", None)
        if callable(reset):
            reset()
        run_id = str(uuid.uuid4())[:8]
        if log_file is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            log_file = f"run_{run_id}_{ts}.jsonl"

        ctx = _Run(run_id, log_file, llm_enabled())
        result = {
            "run_id": run_id,
            "status": "running",
            "facility_id": facility_id,
            "commodity": commodity,
            "month": month,
            "question": question or (
                f"Why did facility {facility_id} report a stockout of {commodity} in {month}?"
            ),
            "dataset_dir": dataset_dir,
            "log_file": log_file,
            "llm_mode": "llm" if ctx.llm_mode else "rule-based",
            "steps": {},
            "approved_actions": [],
            "rejected_actions": [],
            "medical_disclaimer": MEDICAL_DISCLAIMER,
            "requires_pharmacist_approval": True,
        }
        try:
            result = self._run(ctx, result, dataset_dir, role, interactive)
        except Exception as exc:  # last resort: never a traceback to the caller
            result = self._fail(ctx, result, "orchestrator", "run", "StockyWhy failed", exc,
                                "Re-run with the same inputs; if it repeats, check the log file.")
        result["trace"] = ctx.trace
        result["contract_checks"] = ctx.contract_checks
        return result

    @staticmethod
    def _llm_calls():
        counter = getattr(llm_client, "calls_made", None)
        try:
            return int(counter()) if callable(counter) else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # The loop
    # ------------------------------------------------------------------
    def _run(self, ctx, result, dataset_dir, role, interactive):
        facility_id, commodity, month = result["facility_id"], result["commodity"], result["month"]
        data_backend = os.environ.get("STOCKWHY_DATA_SOURCE", "csv").strip().lower() or "csv"

        print(f"\n{'='*60}")
        print(f"  StockyWhy Investigation")
        print(f"  Facility : {facility_id}")
        print(f"  Commodity: {commodity}")
        print(f"  Month    : {month}")
        print(f"  Run ID   : {ctx.run_id}")
        print(f"{'='*60}\n")

        ctx.log("orchestrator", "run_start",
                f"{facility_id}/{commodity}/{month} from {dataset_dir}",
                f"data_backend={data_backend}; llm_mode={result['llm_mode']}; "
                f"scout={'on' if self.scout else 'off'}; memory={'on' if self.memory else 'off'}",
                target="scout", model="none", confidence=1.0,
                data_backend=data_backend, llm_mode=result["llm_mode"])

        # -- 0. Load the dataset once (Scout binds to it, the Evaluator re-reads rows from it)
        try:
            dataset = self.loader(dataset_dir)
        except Exception as exc:
            return self._fail(ctx, result, "data_reader", "load_dataset", "Data Reader failed", exc,
                              "Check --dataset points to a folder with stock.csv, orders.csv, "
                              "payments.csv and facilities.csv (or the STOCKWHY_DATA_SOURCE settings).")
        data_backend = (dataset or {}).get("_source") or data_backend
        result["data_backend"] = data_backend
        ctx.log("data_reader", "load_dataset", dataset_dir,
                f"loaded from {data_backend}: "
                + ", ".join(f"{k}={len(v)}" for k, v in (dataset or {}).items()
                            if k in ("stock", "orders", "payments", "web_notes")),
                target="scout", model="deterministic", confidence=1.0, data_backend=data_backend)

        # -- 1. Scout gate
        contract = None
        print("[1/7] Scout — checking the request...")
        if self.scout is None:
            ctx.log("scout", "scout_gate", "request", "Scout engine not installed; gate skipped",
                    target="memory", model="deterministic", status="skipped")
        else:
            request = {"question": result["question"], "facility_id": facility_id,
                       "commodity": commodity, "month": month, "role": role or "pharmacist"}
            try:
                gate = self.scout.gate(request, dataset) or {}
            except Exception as exc:
                return self._fail(ctx, result, "scout", "scout_gate", "Scout gate failed", exc,
                                  "The request could not be checked, so it was not run.")
            decision = gate.get("decision", "block")
            contract = gate.get("contract")
            result["scout"] = {k: gate.get(k) for k in
                               ("decision", "intent", "band", "reason", "params", "suggestions")}
            if contract is not None and hasattr(contract, "to_dict"):
                result["contract"] = contract.to_dict()
            ctx.log("scout", "scout_gate", f"role={role}; {facility_id}/{commodity}/{month}",
                    f"{decision} ({gate.get('intent')}, band {gate.get('band')}): {gate.get('reason', '')}",
                    target="memory" if decision == "allow" else "user",
                    model="deterministic",
                    confidence={"high": 0.9, "medium": 0.7, "low": 0.45}.get(gate.get("band")),
                    status="ok" if decision == "allow" else decision)
            if decision != "allow":
                result["status"] = decision
                result["message"] = gate.get("reason", "")
                result["error"] = f"Scout {decision}: {gate.get('reason', '')}"
                result["hint"] = {
                    "clarify": "Answer the question above (facility, medicine, month) and run again.",
                    "refuse": "StockWhy explains stock-outs and drafts actions for a pharmacist only.",
                    "block": "Remove instructions or secrets from the request and ask again.",
                }.get(decision, "")
                self._finish(ctx, result)
                return result
            params = gate.get("params") or {}
            for key in ("facility_id", "commodity", "month"):
                if params.get(key) and params[key] != result[key]:
                    result[key] = params[key]
            facility_id, commodity, month = result["facility_id"], result["commodity"], result["month"]

        # Untrusted text in web notes must not become evidence.
        rejected_notes = self._scan_web_notes(ctx, dataset)

        # -- 2. Memory recall
        prior, memory_priority = [], []
        if self.memory is None:
            ctx.log("memory", "memory_recall", f"{facility_id}/{commodity}",
                    "Case memory not installed; recall skipped", target="data_reader",
                    model="deterministic", status="skipped")
        else:
            try:
                self._require(ctx, contract, "memory.read", "memory_recall")
                prior = list(self.memory.recall(facility_id, commodity, limit=5) or [])
                memory_priority = self._memory_priority(prior)
                ctx.log("memory", "memory_recall", f"{facility_id}/{commodity}",
                        f"{len(prior)} prior finding(s); prioritise {memory_priority or 'none'}",
                        target="data_reader", model="deterministic", confidence=1.0)
            except ContractDenied as exc:
                return self._fail(ctx, result, "memory", "memory_recall", "Contract violation", exc,
                                  "The Scout contract does not allow reading case memory.")
            except Exception as exc:
                ctx.log("memory", "memory_recall", f"{facility_id}/{commodity}",
                        f"recall failed, continuing without memory: {_one_line(exc)}",
                        target="data_reader", model="deterministic", status="warning")
        result["memory"] = {"recalled": prior, "prioritised": memory_priority}

        # -- 3. Data Reader
        print("[2/7] Data Reader Agent — loading and profiling data...")
        try:
            self._require(ctx, contract, "data.read", "data_reader")
            self._require_llm(ctx, contract, "data_reader")
            profile = read_and_profile(dataset_dir, facility_id, commodity, month, dataset=dataset)
        except ContractDenied as exc:
            return self._fail(ctx, result, "data_reader", "read_and_profile", "Contract violation", exc,
                              "The Scout contract does not allow this step.")
        except Exception as exc:
            return self._fail(ctx, result, "data_reader", "read_and_profile", "Data Reader failed", exc,
                              "Check the dataset folder and that the facility, medicine and month exist.")
        result["steps"]["data_reader"] = profile
        computed_evidence = profile.get("computed_evidence") or {}
        if rejected_notes:
            self._neutralise_notes(ctx, computed_evidence, rejected_notes)
        ctx.log("data_reader", "read_and_profile",
                f"{facility_id}/{commodity}/{month} from {dataset_dir}",
                f"Profile complete. Warnings: {len(profile.get('missing_data_warnings', []))}",
                target="data_analyst", model=_model_of(profile.get("evidence"), ctx.llm_mode),
                confidence=1.0 if not profile.get("missing_data_warnings") else 0.7)
        print("    ✓ Data profile complete")

        # -- 4. Data Analyst
        print("[3/7] Data Analyst — interpreting evidence signals...")
        try:
            self._require_llm(ctx, contract, "data_analyst")
            analysis = analyze_evidence(computed_evidence, result["question"])
        except ContractDenied as exc:
            return self._fail(ctx, result, "data_analyst", "analyze_evidence", "Contract violation", exc,
                              "The Scout contract does not allow this step.")
        except Exception as exc:
            return self._fail(ctx, result, "data_analyst", "analyze_evidence", "Data Analyst failed", exc,
                              "Retry; to run offline set SAMPLE_MODE=true or STOCKWHY_USE_LLM=false.")
        result["steps"]["data_analyst"] = analysis
        ctx.log("data_analyst", "analyze_evidence", "7 hypothesis evidence blocks",
                str(analysis.get("analysis_summary", ""))[:160] or "analysis complete",
                target="theory_generator", model=_model_of(analysis, ctx.llm_mode),
                confidence=_confidence_of(analysis))
        print("    ✓ Evidence analysis complete")

        # -- 5. Theory Generator
        print("[4/7] Theory Generator — generating 7 hypothesis theories...")
        try:
            self._require_llm(ctx, contract, "theory_generator")
            theories = generate(result["question"], analysis)
        except ContractDenied as exc:
            return self._fail(ctx, result, "theory_generator", "generate", "Contract violation", exc,
                              "The Scout contract does not allow this step.")
        except Exception as exc:
            return self._fail(ctx, result, "theory_generator", "generate", "Theory Generator failed", exc,
                              "Retry; the generator must return one theory per hypothesis H1-H7.")
        result["steps"]["theory_generator"] = theories
        theory_by_id = {t.get("id"): t for t in theories.get("theories", []) if t.get("id")}
        ctx.log("theory_generator", "generate", "question + analysis summary",
                f"{len(theory_by_id)} theories generated", target="orchestrator",
                model=_model_of(theories, ctx.llm_mode), confidence=_confidence_of(theories))
        print(f"    ✓ {len(theory_by_id)} theories generated")

        # -- 6. Plan waves
        wave1, held, reasons = self._plan_waves(theory_by_id, computed_evidence, analysis, memory_priority)
        ctx.log("orchestrator", "plan_waves", "computed flags + analyst signals + memory",
                f"wave 1: {wave1 or 'none'}; held back: {held or 'none'}"
                + ("; " + "; ".join(f"{h}: {r}" for h, r in reasons.items()) if reasons else ""),
                target="evidence_investigator", model="deterministic", confidence=1.0)
        result["wave_plan"] = {"wave1": wave1, "held_back": list(held), "reasons": reasons}

        # -- 7. Investigate / evaluate loop
        final, dropped, waves = {}, [], []
        fault_id = (os.environ.get("STOCKWHY_INJECT_FAULT") or "").strip().upper() or None
        result["fault_drill"] = ({"target": fault_id, "injected": False, "caught": False,
                                  "recovered": False} if fault_id else None)
        pending, wave_no = wave1, 1
        while True:
            if pending:
                print(f"[5/7] Evidence Investigators — wave {wave_no}: {', '.join(pending)}")
                try:
                    self._investigate_and_evaluate(
                        ctx, result, theory_by_id, pending, computed_evidence, dataset,
                        month, wave_no, final, dropped, contract)
                except ContractDenied as exc:
                    return self._fail(ctx, result, "evidence_investigator", "investigate_wave",
                                      "Contract violation", exc, "The Scout contract does not allow this step.")
                except Exception as exc:
                    return self._fail(ctx, result, "evidence_investigator", "investigate_wave",
                                      "Evidence Investigator failed", exc, "Retry the run.")
                waves.append({"wave": wave_no, "hypotheses": list(pending)})

            coverage = evaluator.check_coverage(final, held)
            ctx.log("evaluator", "coverage_check",
                    f"verified: {sorted(final) or 'none'}; held back: {held or 'none'}",
                    f"{coverage['verdict']}: {coverage['reason']}",
                    target=("evidence_investigator" if coverage["verdict"] == "needs_second_pass"
                            else "action_strategist" if coverage["verdict"] == "explained"
                            else "pharmacist"),
                    model="deterministic", confidence=1.0,
                    status="ok" if coverage["verdict"] == "explained" else "warning")
            if coverage["verdict"] != "needs_second_pass":
                break
            ctx.log("evaluator", "request_second_pass", "coverage gap",
                    f"asking investigators to look at held-back hypotheses {coverage['request']}",
                    target="evidence_investigator", model="deterministic", confidence=1.0)
            pending, held, wave_no = coverage["request"], [], wave_no + 1

        evaluations = [final[h] for h in evaluator.HYPOTHESIS_ORDER if h in final]
        result["steps"]["evidence_investigator"] = {
            "evaluations": evaluations, "analysis_requests": [], "waves": waves,
        }
        result["dropped_claims"] = dropped
        result["not_investigated"] = held
        result["coverage"] = coverage
        supported = coverage["supported"]
        result["verified_citations"] = {
            h: final[h].get("verified_citations", []) for h in evaluator.HYPOTHESIS_ORDER if h in final
        }

        # -- 8. Strategist (or escalation)
        if coverage["verdict"] == "insufficient_evidence":
            self._escalate(ctx, result, final)
        else:
            print("[6/7] Action Strategist — ranking causes and drafting actions...")
            try:
                child = self._child_contract(ctx, contract)
                self._require(ctx, child, "action.draft", "action_strategist")
                self._require_llm(ctx, child, "action_strategist")
                actions = recommend_actions(result["question"], {
                    "evaluations": evaluations,
                    "analysis_requests": [],
                    "evaluator": {"supported": supported, "dropped_claims": dropped,
                                  "verified_citations": result["verified_citations"]},
                })
            except ContractDenied as exc:
                return self._fail(ctx, result, "action_strategist", "recommend_actions",
                                  "Contract violation", exc,
                                  "The Scout contract does not allow drafting actions.")
            except Exception as exc:
                return self._fail(ctx, result, "action_strategist", "recommend_actions",
                                  "Action Strategist failed", exc, "Retry the run.")
            self._apply_strategy(ctx, result, actions, final, supported)

        # -- 9. Memory store (pending pharmacist approval)
        self._store_memory(ctx, result, final, supported, contract)

        # -- 10. Pharmacist review (terminal only)
        if interactive and sys.stdin is not None and sys.stdin.isatty():
            print("[7/7] Pharmacist review")
            result = self._pharmacist_review_step(result)
            self._memory_feedback(ctx, result)

        result["status"] = ("insufficient_evidence" if coverage["verdict"] == "insufficient_evidence"
                            else "complete")
        self._finish(ctx, result)
        print(f"\n✓ Investigation complete. Log: logs/{ctx.log_file}")
        return result

    # ------------------------------------------------------------------
    # Investigation + evaluation of one wave
    # ------------------------------------------------------------------
    def _investigate(self, ctx, question, theory_by_id, ids, computed_evidence, contract,
                     critiques=None):
        self._require_llm(ctx, contract, "evidence_investigator")
        batch = []
        for h in ids:
            theory = dict(theory_by_id.get(h) or
                          {"id": h, "hypothesis_name": evaluator.HYPOTHESIS_NAMES.get(h, "unknown")})
            if critiques and critiques.get(h):
                theory["evaluator_critique"] = critiques[h]
                theory["revision_request"] = True
            batch.append(theory)
        out = investigate_parallel(question, {"theories": batch}, computed_evidence) or {}
        by_id = {e.get("theory_id"): e for e in out.get("evaluations", []) if isinstance(e, dict)}
        evals = []
        for h in ids:
            evals.append(dict(by_id.get(h) or {
                "theory_id": h, "hypothesis_name": evaluator.HYPOTHESIS_NAMES.get(h, "unknown"),
                "verdict": "inconclusive", "supporting_evidence_ids": [],
                "contradicting_evidence_ids": [], "reasoning": "Investigator returned no evaluation.",
                "limitations": ["missing evaluation"], "additional_analysis_needed": [],
            }))
        return evals, out

    def _investigate_and_evaluate(self, ctx, result, theory_by_id, ids, computed_evidence,
                                  dataset, month, wave_no, final, dropped, contract):
        question = result["question"]
        drill = result.get("fault_drill")
        evals, raw = self._investigate(ctx, question, theory_by_id, ids, computed_evidence, contract)
        for ev in evals:
            evaluator.attach_claims(ev, computed_evidence, dataset, month)
        if drill and drill["target"] in ids and not drill["injected"]:
            for ev in evals:
                if ev.get("theory_id") == drill["target"]:
                    drill["detail"] = _inject_fault(ev)
                    drill["injected"] = True
                    ctx.log("orchestrator", "inject_fault", f"STOCKWHY_INJECT_FAULT={drill['target']}",
                            f"fault drill: {drill['detail']}", target="evaluator",
                            model="deterministic", status="warning")
        ctx.log("evidence_investigator", "investigate_wave", f"wave {wave_no}: {', '.join(ids)}",
                "verdicts: " + ", ".join(f"{e['theory_id']}={e.get('verdict')}" for e in evals),
                target="evaluator", model=_model_of(raw, ctx.llm_mode),
                confidence=_share_decided(evals), wave=wave_no)

        review = self._evaluate(ctx, evals, computed_evidence, dataset, month, retry=0)
        if drill and drill["injected"] and drill["target"] in review["failed"]:
            drill["caught"] = True

        accepted = {}
        for ev in evals:
            h = ev["theory_id"]
            if h not in review["failed"]:
                ev["verified_citations"] = review["reports"][h]["citations"]["verified"]
                ev["evaluator_confidence"] = review["reports"][h]["confidence"]
                accepted[h] = ev

        if review["failed"]:
            failed = review["failed"]
            critiques = {h: evaluator.critique_text(review["reports"][h]) for h in failed}
            for h in failed:
                ctx.log("evaluator", "request_revision", f"{h} evaluation", critiques[h][:400],
                        target="evidence_investigator", model="deterministic",
                        confidence=review["reports"][h]["confidence"], retry=1, status="warning",
                        hypothesis_id=h)
            revised, raw2 = self._investigate(ctx, question, theory_by_id, failed, computed_evidence,
                                              contract, critiques=critiques)
            for ev in revised:
                evaluator.attach_claims(ev, computed_evidence, dataset, month)
                ev["revised_after_critique"] = critiques[ev["theory_id"]]
            ctx.log("evidence_investigator", "retry_investigation",
                    f"revise {', '.join(failed)} with the Evaluator critique",
                    "verdicts: " + ", ".join(f"{e['theory_id']}={e.get('verdict')}" for e in revised),
                    target="evaluator", model=_model_of(raw2, ctx.llm_mode),
                    confidence=_share_decided(revised), retry=1, wave=wave_no)
            # Re-review the revised ones alongside the accepted ones (cross-critique needs the set).
            second = self._evaluate(ctx, list(accepted.values()) + revised, computed_evidence,
                                    dataset, month, retry=1, only=[e["theory_id"] for e in revised])
            for ev in revised:
                h = ev["theory_id"]
                report = second["reports"][h]
                if report["ok"]:
                    ev["verified_citations"] = report["citations"]["verified"]
                    ev["evaluator_confidence"] = report["confidence"]
                    accepted[h] = ev
                    if drill and h == drill["target"] and drill["caught"]:
                        drill["recovered"] = True
                    ctx.log("evaluator", "accept_revision", f"{h} revised evaluation",
                            f"{h} verified after revision ({ev.get('verdict')}; rows "
                            f"{', '.join(ev['verified_citations']) or 'none'})",
                            target="action_strategist", model="deterministic",
                            confidence=report["confidence"], retry=1, hypothesis_id=h)
                    continue
                kept, note = evaluator.settle(ev, report)
                if kept is None:
                    dropped.append({"hypothesis_id": h, "verdict": ev.get("verdict"), "reason": note,
                                    "failures": report["citations"]["failures"]})
                    ctx.log("evaluator", "drop_unverified", f"{h} after one revision",
                            f"dropped {h}: {note}", target="action_strategist", model="deterministic",
                            confidence=0.0, retry=1, status="warning", hypothesis_id=h)
                else:
                    kept["verified_citations"] = report["citations"]["verified"]
                    kept["evaluator_confidence"] = report["confidence"]
                    kept["evaluator_note"] = note
                    accepted[h] = kept
                    ctx.log("evaluator", "settle_claim", f"{h} after one revision", f"{h}: {note}",
                            target="action_strategist", model="deterministic",
                            confidence=report["confidence"], retry=1, status="warning", hypothesis_id=h)
        final.update(accepted)

    def _evaluate(self, ctx, evals, computed_evidence, dataset, month, retry, only=None):
        review = evaluator.review(evals, computed_evidence, dataset, month)
        scope = only or [e["theory_id"] for e in evals]
        reports = {h: review["reports"][h] for h in scope}

        cite_fail = [h for h, r in reports.items() if not r["citations"]["ok"]]
        n_rows = sum(len(r["citations"]["verified"]) for r in reports.values())
        failures = "; ".join(
            f"{h}: " + ", ".join(
                f"{f['row_id']}{'.' + f['field'] if 'field' in f else ''} ({f['reason']})"
                for f in reports[h]["citations"]["failures"])
            for h in cite_fail)
        ctx.log("evaluator", "verify_citations", f"{len(scope)} evaluation(s): {', '.join(scope)}",
                f"{n_rows} cited row(s) re-read and matched; failures: {failures or 'none'}",
                target="evidence_investigator" if cite_fail else "evaluator",
                model="deterministic", confidence=_mean([r["confidence"] for r in reports.values()]),
                retry=retry, status="warning" if cite_fail else "ok")

        cons_fail = [h for h, r in reports.items() if not r["consistency"]["ok"]]
        ctx.log("evaluator", "check_consistency", "verdicts vs computed flags",
                "; ".join(reports[h]["consistency"]["reason"] for h in cons_fail)
                or "all verdicts agree with the computed flags",
                target="evidence_investigator" if cons_fail else "evaluator",
                model="deterministic",
                confidence=round(1.0 - len(cons_fail) / max(len(scope), 1), 2),
                retry=retry, status="warning" if cons_fail else "ok")

        crit = [c for c in review["critiques"] if c["target"] in scope]
        ctx.log("evaluator", "cross_critique", "supported verdicts vs other hypotheses' evidence",
                "; ".join(f"{c['raised_by']}->{c['target']} ({c['kind']}): {c['reason']}" for c in crit)
                or "no conflicts between hypotheses",
                target="evidence_investigator" if crit else "action_strategist",
                model="deterministic", confidence=1.0, retry=retry,
                status="warning" if crit else "ok")
        review["failed"] = [h for h in review["failed"] if h in scope]
        return review

    # ------------------------------------------------------------------
    # Planning, strategy, escalation, memory
    # ------------------------------------------------------------------
    @staticmethod
    def _plan_waves(theory_by_id, computed_evidence, analysis, memory_priority):
        """Wave 1 = memory priority first, then computed flags, then analyst signals."""
        signals = (analysis or {}).get("hypothesis_signals") or {}
        known = [h for h in evaluator.HYPOTHESIS_ORDER if h in theory_by_id] or list(evaluator.HYPOTHESIS_ORDER)
        reasons, ordered = {}, []
        for h in memory_priority:
            if h in known and h not in ordered:
                ordered.append(h)
                reasons[h] = "prior finding in case memory"
        for h in known:
            if h in ordered:
                continue
            ev = evaluator.hypothesis_evidence(computed_evidence, h)
            expected = evaluator.expected_verdict(h, ev)
            if expected == "supported" or (expected == "inconclusive" and ev and not ev.get("data_missing")):
                ordered.append(h)
                reasons[h] = f"computed flags -> {expected}"
                continue
            sig = signals.get(h) or signals.get(evaluator.EVIDENCE_KEYS[h])
            level = sig.get("signal") if isinstance(sig, dict) else sig
            if isinstance(level, str) and level.strip().lower() in ("strong", "weak"):
                ordered.append(h)
                reasons[h] = f"analyst signal {level.strip().lower()}"
        held = [h for h in known if h not in ordered]
        return ordered, held, reasons

    @staticmethod
    def _memory_priority(prior):
        """Hypothesis ids named by prior (not rejected) findings, newest first."""
        ids = []
        for rec in prior:
            if not isinstance(rec, dict) or rec.get("status") == "rejected":
                continue
            text = " ".join(str(rec.get(k, "")) for k in ("cause", "hypothesis_id", "top_cause"))
            tokens = text.upper().replace("_", " ").replace(",", " ").split()
            for h in evaluator.HYPOTHESIS_ORDER:
                if (h in tokens or evaluator.HYPOTHESIS_NAMES[h] in text) and h not in ids:
                    ids.append(h)
        return ids

    def _apply_strategy(self, ctx, result, actions, final, supported):
        """Keep only what verified rows back; attach those rows to every ranked cause and action."""
        result["steps"]["action_strategist"] = actions
        verified = {h: final[h].get("verified_citations", []) for h in final}
        support_rows = sorted({r for h in supported for r in verified.get(h, [])})

        ranked = []
        for item in actions.get("ranked_hypotheses", []) or []:
            h = item.get("hypothesis_id")
            if h in final:
                item = dict(item)
                item["verdict"] = final[h].get("verdict", item.get("verdict"))
                item["citations"] = verified.get(h, [])
                ranked.append(item)
        listed = {r.get("hypothesis_id") for r in ranked}
        for h in evaluator.HYPOTHESIS_ORDER:  # anything verified that the strategist skipped
            if h in final and h not in listed:
                ranked.append({"hypothesis_id": h, "hypothesis_name": evaluator.HYPOTHESIS_NAMES[h],
                               "verdict": final[h].get("verdict"),
                               "likelihood": "high" if h in supported else "low",
                               "summary": str(final[h].get("reasoning", ""))[:200],
                               "citations": verified.get(h, [])})
        ranked.sort(key=lambda r: supported.index(r["hypothesis_id"])
                    if r.get("hypothesis_id") in supported else len(supported))

        kept, removed = [], []
        for action in actions.get("actions", []) or []:
            links = action.get("linked_hypothesis_ids") or action.get("linked_theory_ids") or []
            links = [h for h in links if isinstance(h, str)]
            if links and not any(h in supported for h in links):
                removed.append(action.get("action_id", "?"))
                continue
            action["pharmacist_review_required"] = True
            rows = sorted({r for h in links for r in verified.get(h, [])})
            action["verified_citations"] = rows or support_rows
            kept.append(action)

        top = supported[0] if supported else None
        cause = actions.get("most_likely_cause", "")
        if top and ranked and ranked[0].get("hypothesis_id") == top and cause:
            most_likely = cause
        elif top:
            most_likely = (f"{evaluator.HYPOTHESIS_NAMES[top]} ({top}) — verified from "
                           f"{', '.join(verified.get(top, [])) or 'the dataset'}")
        else:
            most_likely = cause
        result["most_likely_cause"] = most_likely
        result["verified_cause"] = ({"hypothesis_id": top, "hypothesis_name": evaluator.HYPOTHESIS_NAMES[top],
                                     "citations": verified.get(top, [])} if top else None)
        result["ranked_hypotheses"] = ranked
        result["actions"] = kept
        result["removed_actions"] = removed
        if actions.get("medical_disclaimer"):
            result["medical_disclaimer"] = actions["medical_disclaimer"]
        ctx.log("action_strategist", "recommend_actions",
                f"verified evaluations: {sorted(final)}; supported: {supported}",
                f"Most likely: {str(most_likely)[:120]}. {len(kept)} action(s) drafted for pharmacist approval"
                + (f"; removed actions without verified backing {removed}" if removed else ""),
                target="pharmacist", model=_model_of(actions, ctx.llm_mode),
                confidence=_confidence_of(actions)
                or _mean([final[h].get("evaluator_confidence") for h in supported]))
        print(f"    ✓ {len(kept)} actions proposed")

    def _escalate(self, ctx, result, final):
        checked = sorted({r for ev in final.values() for r in ev.get("verified_citations", [])})
        reason = ("No hypothesis is supported by rows the Evaluator could verify. StockWhy will not "
                  "name a cause it cannot back with data.")
        result["most_likely_cause"] = "Insufficient evidence — escalated to the pharmacist"
        result["verified_cause"] = None
        result["escalation"] = {"to": "pharmacist", "reason": reason, "rows_checked": checked}
        result["ranked_hypotheses"] = [
            {"hypothesis_id": h, "hypothesis_name": evaluator.HYPOTHESIS_NAMES[h],
             "verdict": final[h].get("verdict"), "likelihood": "low",
             "summary": str(final[h].get("reasoning", ""))[:200],
             "citations": final[h].get("verified_citations", [])}
            for h in evaluator.HYPOTHESIS_ORDER if h in final
        ]
        result["actions"] = [{
            "action_id": "A1",
            "action": ("Pharmacist to physically count stock and check the ledger, delivery notes and "
                       "requisitions for this month; the data does not explain the stock-out."),
            "linked_hypothesis_ids": [],
            "evidence_basis": ", ".join(checked) or "no verified rows",
            "verified_citations": checked,
            "priority": "high",
            "proposed_owner": "Facility pharmacist",
            "timeframe": "within 48 hours",
            "expected_outcome": "A confirmed cause, or corrected records",
            "success_measure": "Cause recorded with evidence",
            "risks_and_caveats": "No cause has been established by the data.",
            "pharmacist_review_required": True,
        }]
        result["steps"]["action_strategist"] = {
            "skipped": "insufficient evidence; escalated instead of drafting cause-specific actions",
            "medical_disclaimer": MEDICAL_DISCLAIMER,
            "open_questions": ["Which records or events are missing from the data for this month?"],
        }
        ctx.log("orchestrator", "escalate_to_pharmacist", "coverage: insufficient evidence", reason,
                target="pharmacist", model="deterministic", confidence=1.0, status="escalated")
        print("    ! Insufficient evidence — escalated to the pharmacist")

    def _store_memory(self, ctx, result, final, supported, contract):
        if self.memory is None:
            ctx.log("memory", "memory_store", "finding", "Case memory not installed; store skipped",
                    target="pharmacist", model="deterministic", status="skipped")
            return
        top = supported[0] if supported else None
        citations = sorted({r for h in supported for r in final[h].get("verified_citations", [])})
        if not top or not citations:
            ctx.log("memory", "memory_store", "finding",
                    "nothing stored: no verified cause with cited rows", target="pharmacist",
                    model="deterministic", status="skipped")
            return
        finding = {
            "facility_id": result["facility_id"], "commodity": result["commodity"],
            "month": result["month"], "cause": f"{top} {evaluator.HYPOTHESIS_NAMES[top]}",
            "hypothesis_id": top, "supported_hypotheses": supported,
            "summary": str(result.get("most_likely_cause", ""))[:300] or evaluator.HYPOTHESIS_NAMES[top],
            "confidence": final[top].get("evaluator_confidence"),
        }
        try:
            self._require(ctx, contract, "memory.write", "memory_store")
            memory_id = self.memory.store(finding, citations, ctx.run_id)
            result.setdefault("memory", {})["stored_id"] = memory_id
            result["memory"]["stored_status"] = "pending_approval"
            ctx.log("memory", "memory_store", f"{finding['cause']} with {len(citations)} citation(s)",
                    f"stored {memory_id} as pending_approval", target="pharmacist",
                    model="deterministic", confidence=finding["confidence"])
        except Exception as exc:
            ctx.log("memory", "memory_store", "finding", f"not stored: {_one_line(exc)}",
                    target="pharmacist", model="deterministic", status="warning")

    def _memory_feedback(self, ctx, result):
        memory_id = (result.get("memory") or {}).get("stored_id")
        if not memory_id or self.memory is None:
            return
        approved, rejected = result.get("approved_actions", []), result.get("rejected_actions", [])
        if not approved and not rejected:
            return
        decision = "approve" if approved else "reject"
        note = f"{len(approved)} action(s) approved, {len(rejected)} rejected by pharmacist"
        try:
            self.memory.feedback(memory_id, decision, note=note)
            result["memory"]["stored_status"] = "approved" if decision == "approve" else "rejected"
            ctx.log("memory", "memory_feedback", f"pharmacist review of {memory_id}",
                    f"{decision}: {note}", target="memory", model="human", confidence=1.0)
        except Exception as exc:
            ctx.log("memory", "memory_feedback", memory_id, f"feedback failed: {_one_line(exc)}",
                    target="memory", model="human", status="warning")

    # ------------------------------------------------------------------
    # Contracts and guards
    # ------------------------------------------------------------------
    @staticmethod
    def _require(ctx, contract, capability, step):
        if contract is None:
            ctx.contract_checks.append({"step": step, "capability": capability, "result": "skipped"})
            return
        try:
            contract.check(capability)
        except Exception as exc:
            ctx.contract_checks.append({"step": step, "capability": capability, "result": "denied",
                                        "contract_id": getattr(contract, "id", None)})
            raise ContractDenied(f"{step} lacks capability '{capability}': {_one_line(exc)}") from exc
        ctx.contract_checks.append({"step": step, "capability": capability, "result": "granted",
                                    "contract_id": getattr(contract, "id", None)})

    def _require_llm(self, ctx, contract, step):
        if ctx.llm_mode:
            self._require(ctx, contract, "llm.call", step)

    @staticmethod
    def _child_contract(ctx, contract):
        if contract is None or not hasattr(contract, "child"):
            return contract
        caps = {"data.read", "action.draft"} | ({"llm.call"} if ctx.llm_mode else set())
        try:
            child = contract.child("action.draft", caps)
        except Exception as exc:
            raise ContractDenied(f"action_strategist: child contract refused: {_one_line(exc)}") from exc
        ctx.child_contract = child
        ctx.log("orchestrator", "child_contract", f"parent {getattr(contract, 'id', '?')}",
                f"child contract {getattr(child, 'id', '?')} for action.draft ({sorted(caps)})",
                target="action_strategist", model="deterministic", confidence=1.0)
        return child

    def _scan_web_notes(self, ctx, dataset):
        """Scan web-note text with the Scout guard before it can become evidence."""
        try:
            from engines.scout_intent import scan_injection
        except Exception:
            return []
        notes = (dataset or {}).get("web_notes") or []
        flagged = []
        for i, note in enumerate(notes):
            if not isinstance(note, dict):
                continue
            text = " ".join(str(note.get(k, "")) for k in ("title", "summary", "text", "source"))
            kinds = scan_injection(text)
            if kinds:
                flagged.append({"index": i, "title": note.get("title"), "month": note.get("month"),
                                "commodity": note.get("commodity"), "kinds": kinds})
        ctx.log("scout", "scan_web_notes", f"{len(notes)} web note(s)",
                f"{len(flagged)} note(s) carry instructions and will not count as evidence"
                if flagged else "no injection text found",
                target="memory", model="deterministic", confidence=1.0,
                status="warning" if flagged else "ok")
        return flagged

    @staticmethod
    def _neutralise_notes(ctx, computed_evidence, flagged):
        h7 = computed_evidence.get("h7_national_disruption") or {}
        notice = h7.get("notice_details") or {}
        for f in flagged:
            if notice and notice.get("title") == f["title"] and notice.get("month") == f["month"]:
                h7["web_notice_found"] = False
                h7["notice_details"] = None
                h7["notice_rejected_by_guard"] = f["kinds"]
                ctx.log("scout", "reject_web_note", f"web_notes#{f['index']}",
                        "notice removed from H7 evidence (instruction text in the note)",
                        target="data_analyst", model="deterministic", status="warning")

    # ------------------------------------------------------------------
    # Finish / fail
    # ------------------------------------------------------------------
    def _finish(self, ctx, result):
        checks = ctx.contract_checks
        granted = [c for c in checks if c["result"] == "granted"]
        skipped = [c for c in checks if c["result"] == "skipped"]
        denied = [c for c in checks if c["result"] == "denied"]
        child = ctx.child_contract
        result["contracts"] = {
            "main": result.get("contract"),
            "child": child.to_dict() if child is not None and hasattr(child, "to_dict") else None,
            "checks": len(checks), "granted": len(granted),
            "skipped": len(skipped), "denied": len(denied),
        }
        ctx.log("orchestrator", "contract_summary", f"{len(checks)} capability check(s)",
                f"{len(granted)} granted, {len(denied)} denied, {len(skipped)} skipped (no Scout contract)",
                target="none", model="deterministic", confidence=1.0,
                status="error" if denied else ("skipped" if skipped and not granted else "ok"))
        ctx.log("orchestrator", "pipeline_complete",
                f"{result['facility_id']}/{result['commodity']}/{result['month']}",
                f"status={result.get('status')}. Most likely cause: "
                f"{result.get('most_likely_cause', 'n/a')}. "
                f"Approved actions: {len(result.get('approved_actions', []))}. "
                f"LLM calls: {self._llm_calls() if self._llm_calls() is not None else 'n/a'}",
                target="user", model="deterministic", confidence=1.0, llm_calls=self._llm_calls(),
                status="ok" if result.get("status") in ("complete", "running") else result.get("status"))

    def _fail(self, ctx, result, agent, action, label, exc, hint):
        message = f"{label}: {_one_line(exc)}"
        ctx.log(agent, action, f"{result.get('facility_id')}/{result.get('commodity')}/{result.get('month')}",
                message, target="user", model="none", status="error")
        result["status"] = "error"
        result["error"] = message
        result["hint"] = hint
        self._finish(ctx, result)
        return result

    # ------------------------------------------------------------------
    # Interactive pharmacist review (unchanged behaviour)
    # ------------------------------------------------------------------
    def _pharmacist_review_step(self, result: dict) -> dict:
        """
        Interactive terminal loop: pharmacist reviews each proposed action
        and can accept, edit, or reject it.
        """
        actions = result.get("actions", [])
        if not actions:
            return result

        print("\n" + "="*60)
        print("  PHARMACIST REVIEW — Proposed Actions")
        print("  ⚠️  No action will execute without your approval.")
        print("="*60)
        print(
            "\n  Medical disclaimer: This system provides decision-support "
            "information only. It does not constitute medical advice or "
            "authorisation to act.\n"
        )

        approved = []
        rejected = []

        for action in actions:
            a_id = action.get("action_id", "?")
            priority = action.get("priority", "?").upper()
            print(f"\n--- Action {a_id} [{priority}] ---")
            print(f"  {action.get('action', '')}")
            print(f"  Owner   : {action.get('proposed_owner', '')}")
            print(f"  Timeframe: {action.get('timeframe', '')}")
            print(f"  Evidence: {action.get('evidence_basis', '')}")
            print(f"  Verified rows: {', '.join(action.get('verified_citations', [])) or 'none'}")
            print(f"  Caveats : {action.get('risks_and_caveats', '')}")
            print(f"  ⚠️  pharmacist_review_required: True")

            while True:
                choice = input(
                    "\n  [a]ccept / [e]dit / [r]eject / [s]kip all? "
                ).strip().lower()

                if choice in ("a", "accept"):
                    approved.append(action)
                    print("  → Accepted.")
                    break
                elif choice in ("e", "edit"):
                    note = input("  Enter your amendment note: ").strip()
                    action["pharmacist_amendment"] = note
                    approved.append(action)
                    print("  → Accepted with amendment.")
                    break
                elif choice in ("r", "reject"):
                    reason = input("  Rejection reason (optional): ").strip()
                    action["rejection_reason"] = reason
                    rejected.append(action)
                    print("  → Rejected.")
                    break
                elif choice in ("s", "skip"):
                    # Accept all remaining without prompting
                    approved.append(action)
                    for remaining in actions[actions.index(action) + 1:]:
                        approved.append(remaining)
                    print("  → Skipping remaining reviews. All remaining accepted.")
                    result["approved_actions"] = approved
                    result["rejected_actions"] = rejected
                    return result
                else:
                    print("  Please enter a, e, r, or s.")

        result["approved_actions"] = approved
        result["rejected_actions"] = rejected

        print(f"\n  Summary: {len(approved)} accepted, {len(rejected)} rejected.")
        return result
