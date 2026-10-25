"""
orchestrator.py

StockyWhy orchestrator: ties all agents together into a single investigation pipeline.
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


class StockyWhy:
    """
    Main investigation orchestrator.

    Steps:
      1. Data Reader   — load & profile data deterministically + LLM interpretation
      2. Data Analyst  — interpret computed evidence signals
      3. Theory Gen    — generate 7 theories (one per hypothesis)
      4. Investigator  — evaluate each theory in parallel
      5. Strategist    — rank causes, draft actions
      6. Review        — interactive pharmacist review loop (if terminal)
    """

    def run(
        self,
        dataset_dir: str,
        facility_id: str,
        commodity: str,
        month: str,
        log_file: str = None,
        interactive: bool = True,
    ) -> dict:
        """
        Run the full StockyWhy investigation pipeline.

        Parameters
        ----------
        dataset_dir  : path to the dataset folder (CSV/JSON files)
        facility_id  : e.g. "FAC-011"
        commodity    : e.g. "ORS sachet"
        month        : e.g. "2026-03"
        log_file     : JSONL filename in logs/ (auto-generated if None)
        interactive  : if True, prompt pharmacist for action review in terminal

        Returns
        -------
        Full result dict with all pipeline outputs.
        """
        # Resolve SAMPLE_MODE
        if os.environ.get("SAMPLE_MODE", "false").lower() == "true":
            dataset_dir = os.path.join(
                os.path.dirname(__file__), "data", "sample"
            )

        # Ensure logs directory exists
        Path("logs").mkdir(parents=True, exist_ok=True)

        # Generate a run ID
        run_id = str(uuid.uuid4())[:8]
        if log_file is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            log_file = f"run_{run_id}_{ts}.jsonl"

        question = (
            f"Why did facility {facility_id} report a stockout of "
            f"{commodity} in {month}?"
        )

        print(f"\n{'='*60}")
        print(f"  StockyWhy Investigation")
        print(f"  Facility : {facility_id}")
        print(f"  Commodity: {commodity}")
        print(f"  Month    : {month}")
        print(f"  Run ID   : {run_id}")
        print(f"{'='*60}\n")

        result = {
            "run_id": run_id,
            "facility_id": facility_id,
            "commodity": commodity,
            "month": month,
            "question": question,
            "dataset_dir": dataset_dir,
            "log_file": log_file,
            "steps": {},
            "approved_actions": [],
            "rejected_actions": [],
        }

        # -------------------------------------------------------------------
        # Step 1: Data Reader Agent
        # -------------------------------------------------------------------
        print("[1/5] Data Reader Agent — loading and profiling data...")
        try:
            profile = read_and_profile(dataset_dir, facility_id, commodity, month)
            result["steps"]["data_reader"] = profile
            log_event(
                log_file=log_file,
                run_id=run_id,
                agent_name="data_reader",
                action="read_and_profile",
                input_summary=f"{facility_id}/{commodity}/{month} from {dataset_dir}",
                output_summary=(
                    f"Profile complete. "
                    f"Warnings: {len(profile.get('missing_data_warnings', []))}"
                ),
                status="ok",
            )
            print("    ✓ Data profile complete")
        except Exception as exc:
            log_event(
                log_file=log_file,
                run_id=run_id,
                agent_name="data_reader",
                action="read_and_profile",
                input_summary=f"{facility_id}/{commodity}/{month}",
                output_summary=str(exc),
                status="error",
            )
            result["error"] = f"Data Reader failed: {exc}"
            return result

        # -------------------------------------------------------------------
        # Step 2: Data Analyst — interpret computed evidence
        # -------------------------------------------------------------------
        print("[2/5] Data Analyst — interpreting evidence signals...")
        try:
            computed_evidence = profile["computed_evidence"]
            analysis = analyze_evidence(computed_evidence, question)
            result["steps"]["data_analyst"] = analysis
            log_event(
                log_file=log_file,
                run_id=run_id,
                agent_name="data_analyst",
                action="analyze_evidence",
                input_summary=f"7 hypothesis evidence blocks",
                output_summary=analysis.get("analysis_summary", "")[:120],
                status="ok",
            )
            print("    ✓ Evidence analysis complete")
        except Exception as exc:
            log_event(
                log_file=log_file,
                run_id=run_id,
                agent_name="data_analyst",
                action="analyze_evidence",
                input_summary="computed_evidence",
                output_summary=str(exc),
                status="error",
            )
            result["error"] = f"Data Analyst failed: {exc}"
            return result

        # -------------------------------------------------------------------
        # Step 3: Theory Generator — 7 theories
        # -------------------------------------------------------------------
        print("[3/5] Theory Generator — generating 7 hypothesis theories...")
        try:
            theories = generate(question, analysis)
            result["steps"]["theory_generator"] = theories
            log_event(
                log_file=log_file,
                run_id=run_id,
                agent_name="theory_generator",
                action="generate",
                input_summary=f"question + analysis summary",
                output_summary=(
                    f"{len(theories.get('theories', []))} theories generated"
                ),
                status="ok",
            )
            print(f"    ✓ {len(theories.get('theories', []))} theories generated")
        except ValueError as exc:
            log_event(
                log_file=log_file,
                run_id=run_id,
                agent_name="theory_generator",
                action="generate",
                input_summary="question + analysis",
                output_summary=str(exc),
                status="error",
            )
            result["error"] = f"Theory Generator failed: {exc}"
            return result

        # -------------------------------------------------------------------
        # Step 4: Evidence Investigator — parallel evaluation
        # -------------------------------------------------------------------
        print("[4/5] Evidence Investigator — evaluating theories in parallel...")
        try:
            evaluations = investigate_parallel(question, theories, computed_evidence)
            result["steps"]["evidence_investigator"] = evaluations
            verdicts = [e.get("verdict", "?") for e in evaluations.get("evaluations", [])]
            log_event(
                log_file=log_file,
                run_id=run_id,
                agent_name="evidence_investigator",
                action="investigate_parallel",
                input_summary=f"7 theories + computed_evidence",
                output_summary=f"verdicts: {', '.join(verdicts)}",
                status="ok",
            )
            print(f"    ✓ Evaluations: {', '.join(verdicts)}")
        except Exception as exc:
            log_event(
                log_file=log_file,
                run_id=run_id,
                agent_name="evidence_investigator",
                action="investigate_parallel",
                input_summary="theories + evidence",
                output_summary=str(exc),
                status="error",
            )
            result["error"] = f"Evidence Investigator failed: {exc}"
            return result

        # -------------------------------------------------------------------
        # Step 5: Action Strategist — rank causes + draft actions
        # -------------------------------------------------------------------
        print("[5/5] Action Strategist — ranking causes and drafting actions...")
        try:
            actions = recommend_actions(question, evaluations)
            result["steps"]["action_strategist"] = actions
            result["most_likely_cause"] = actions.get("most_likely_cause", "")
            result["ranked_hypotheses"] = actions.get("ranked_hypotheses", [])
            result["actions"] = actions.get("actions", [])
            log_event(
                log_file=log_file,
                run_id=run_id,
                agent_name="action_strategist",
                action="recommend_actions",
                input_summary=f"evaluations for {facility_id}/{commodity}/{month}",
                output_summary=(
                    f"Most likely: {actions.get('most_likely_cause', 'unknown')}. "
                    f"{len(actions.get('actions', []))} actions proposed."
                ),
                status="ok",
            )
            print(f"    ✓ {len(actions.get('actions', []))} actions proposed")
        except Exception as exc:
            log_event(
                log_file=log_file,
                run_id=run_id,
                agent_name="action_strategist",
                action="recommend_actions",
                input_summary="evaluations",
                output_summary=str(exc),
                status="error",
            )
            result["error"] = f"Action Strategist failed: {exc}"
            return result

        # -------------------------------------------------------------------
        # Step 6: Pharmacist review (interactive)
        # -------------------------------------------------------------------
        if interactive and sys.stdin.isatty():
            result = self._pharmacist_review_step(result)

        log_event(
            log_file=log_file,
            run_id=run_id,
            agent_name="orchestrator",
            action="pipeline_complete",
            input_summary=f"{facility_id}/{commodity}/{month}",
            output_summary=(
                f"Most likely cause: {result.get('most_likely_cause', 'unknown')}. "
                f"Approved actions: {len(result.get('approved_actions', []))}"
            ),
            status="ok",
        )

        print(f"\n✓ Investigation complete. Log: logs/{log_file}")
        return result

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
