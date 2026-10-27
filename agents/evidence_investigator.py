"""
agents/evidence_investigator.py

Evidence Investigator Agent: evaluates theories against computed evidence.
Supports sequential (investigate) and parallel (investigate_parallel) modes.

The verdict always comes from the computed flags (agents/rules.py). The LLM
(fast lane) writes the explanation; with the LLM disabled
(llm_client.llm_enabled) the explanation is rule-based and cites the
computed numbers and row ids.
"""

import concurrent.futures

from agents import rules
from llm_client import RULE_BASED, LLMError, ask_agent, llm_enabled


SYSTEM = """
You are the StockWhy Evidence Investigator.

Evaluate every proposed theory using the supplied data profile,
actual computed test results, and evidence references.

For each theory:
- assess whether evidence supports its predictions
- identify contradictory or missing evidence
- distinguish statistical association from causation
- state what the tests cannot establish
- assign supported, weakened, or inconclusive

Never invent a test result, statistic, row, or citation.
A low p-value alone does not establish causation or importance.

Hypotheses reference:
  H1 late_order, H2 supplier_underfill, H3 payment_arrears,
  H4 demand_surge, H5 record_error, H6 expiry, H7 national_disruption

Return JSON:
{
  "evaluations": [
    {
      "theory_id": "H1",
      "hypothesis_name": "late_order",
      "verdict": "supported|weakened|inconclusive",
      "supporting_evidence_ids": [],
      "contradicting_evidence_ids": [],
      "reasoning": "...",
      "limitations": [],
      "additional_analysis_needed": []
    }
  ],
  "analysis_requests": []
}
"""

SINGLE_HYPOTHESIS_SYSTEM = """
You are the StockWhy Evidence Investigator.

You are evaluating ONE specific hypothesis about a drug stockout.

Hypothesis being evaluated: {hypothesis_id} — {hypothesis_name}

You receive pre-computed deterministic evidence for this hypothesis. The computations
are already done — your job is to interpret them, not redo them.

VERDICT RULES (apply strictly):
- "supported"    : the primary computed flag is TRUE and no strong counter-evidence exists
- "weakened"     : the primary flag is FALSE, OR contradicting evidence is present
- "inconclusive" : data is missing or the signal is borderline

Primary computed flags for each hypothesis:
  H1 late_order:           "late"==true OR "delivery_slipped"==true  → supported
  H2 supplier_underfill:   "underfill"==true                         → supported
  H3 payment_arrears:      "major_arrears"==true                     → supported
  H4 demand_surge:         "surge"==true (pct_change > 25%)          → supported
  H5 record_error:         "identity_holds"==false                   → supported
  H6 expiry:               "high_wastage"==true                      → supported
  H7 national_disruption:  "web_notice_found"==true AND fill_drop>0  → supported

If the primary flag is FALSE → verdict is "weakened" (not inconclusive).
Only use "inconclusive" when data is genuinely missing ("data_missing"==true).

Rules:
- Do NOT invent statistics, row IDs, or citations
- Use only the evidence provided
- Cite record IDs where they appear in the evidence (e.g. stock#1506, orders#1505)
- Be definitive: if the computed flag is clear, match your verdict to it

Return valid JSON matching exactly this structure (no extra fields, no markdown):
{{
  "theory_id": "{hypothesis_id}",
  "hypothesis_name": "{hypothesis_name}",
  "verdict": "supported|weakened|inconclusive",
  "supporting_evidence_ids": [],
  "contradicting_evidence_ids": [],
  "reasoning": "...",
  "limitations": [],
  "additional_analysis_needed": []
}}
"""

HYPOTHESIS_NAMES = rules.HYPOTHESIS_NAMES
EVIDENCE_KEYS = rules.EVIDENCE_KEYS
VERDICTS = ("supported", "weakened", "inconclusive")

# What each computed check cannot establish (rule-based limitations).
LIMITATIONS = {
    "H1": ["Order and cutoff dates show timing, not why the order was late."],
    "H2": ["County average covers one cycle; a single under-fill may be routine."],
    "H3": ["Arrears are county-level; they cannot be tied to this facility's delivery directly."],
    "H4": ["A 3-month average is a short baseline; seasonality is not modelled."],
    "H5": ["The identity check cannot detect errors that keep the ledger balanced."],
    "H6": ["Wastage is not split into expiry versus damage."],
    "H7": ["Public notices are sparse; absence of a notice does not rule out a disruption."],
}

FOLLOW_UPS = {
    "H1": ["Confirm the order submission date with the facility pharmacist."],
    "H2": ["Compare the delivery note with the order for this cycle."],
    "H3": ["Check the county's payment status with the supplier."],
    "H4": ["Check clinic records for an outbreak or caseload change."],
    "H5": ["Do a physical stock count and reconcile the ledger."],
    "H6": ["Review expiry dates and FEFO practice for current batches."],
    "H7": ["Check KEMSA / supplier notices for this commodity."],
}

def investigate(
    question: str,
    theories: dict,
    data_analysis: dict,
    test_results: list,
) -> dict:
    """Sequential mode: one call for all theories; falls back to rules on any LLM failure."""
    if llm_enabled():
        try:
            result = ask_agent(
                SYSTEM,
                {
                    "research_question": question,
                    "theories": theories,
                    "data_analysis": data_analysis,
                    "computed_test_results": test_results,
                },
            )
            _check_sequential_shape(result)
            return result
        except (LLMError, ValueError) as exc:
            result = investigate_rule_based(theories, data_analysis)
            result["_fallback_reason"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            return result
    return investigate_rule_based(theories, data_analysis)


def _check_sequential_shape(result) -> None:
    if not isinstance(result, dict) or not isinstance(result.get("evaluations"), list):
        raise ValueError("LLM reply has no 'evaluations' list")
    for e in result["evaluations"]:
        if not isinstance(e, dict) or e.get("theory_id") not in rules.ID_ORDER \
                or e.get("verdict") not in VERDICTS:
            raise ValueError("LLM evaluation lacks a valid theory_id H1-H7 or verdict")


def investigate_rule_based(theories: dict, data_analysis: dict) -> dict:
    """
    Offline sequential mode: map the analyst's computed signal per hypothesis
    to a verdict (strong -> supported, weak -> inconclusive, none -> weakened).
    """
    signal_to_verdict = {"strong": "supported", "weak": "inconclusive", "none": "weakened"}
    signals = (data_analysis or {}).get("hypothesis_signals") or {}
    evaluations = []
    for theory in (theories or {}).get("theories", []):
        h_id = theory.get("id", "H?")
        entry = signals.get(h_id) or signals.get(EVIDENCE_KEYS.get(h_id, "")) or {}
        if isinstance(entry, str):
            entry = {"signal": entry}
        sig = entry.get("signal")
        ids = entry.get("evidence_ids", [])
        verdict = signal_to_verdict.get(sig, "inconclusive")
        evaluations.append({
            "theory_id": h_id,
            "hypothesis_name": theory.get("hypothesis_name", HYPOTHESIS_NAMES.get(h_id, "unknown")),
            "verdict": verdict,
            "supporting_evidence_ids": ids if verdict == "supported" else [],
            "contradicting_evidence_ids": ids if verdict == "weakened" else [],
            "reasoning": entry.get("reasoning") or f"Analyst signal: {sig or 'not available'}.",
            "limitations": list(LIMITATIONS.get(h_id, [])),
            "additional_analysis_needed": list(FOLLOW_UPS.get(h_id, [])),
            "_produced_by": RULE_BASED,
        })
    return {"evaluations": evaluations, "analysis_requests": [], "_produced_by": RULE_BASED}


def _deterministic_verdict(hypothesis_id: str, hypothesis_evidence: dict) -> str:
    """
    Assign a verdict deterministically based on computed flags.

    This is the source of truth — the LLM explains the reasoning but
    the verdict itself comes from the deterministic calculations.

    Returns "supported", "weakened", or "inconclusive".
    """
    return rules.deterministic_verdict(hypothesis_id, hypothesis_evidence)


def _rule_based_evaluation(h_id: str, h_name: str, hypothesis_evidence: dict, verdict: str) -> dict:
    """Explanation built only from the computed numbers and row ids."""
    ids = rules.evidence_ids(hypothesis_evidence)
    rule = {
        "supported": "the computed flag passes its threshold",
        "weakened": "the computed flag does not pass its threshold",
        "inconclusive": "the data needed for this check is missing or borderline",
    }[verdict]
    return {
        "theory_id": h_id,
        "hypothesis_name": h_name,
        "verdict": verdict,
        "verdict_source": "deterministic",
        "supporting_evidence_ids": ids if verdict == "supported" else [],
        "contradicting_evidence_ids": ids if verdict == "weakened" else [],
        "reasoning": f"{rules.describe(h_id, hypothesis_evidence)} Verdict '{verdict}': {rule}.",
        "limitations": list(LIMITATIONS.get(h_id, [])),
        "additional_analysis_needed": list(FOLLOW_UPS.get(h_id, [])),
        "_produced_by": RULE_BASED,
    }


def _investigate_one(
    question: str,
    theory: dict,
    hypothesis_evidence: dict,
) -> dict:
    """Investigate a single hypothesis in isolation."""
    h_id = theory.get("id", "H?")
    h_name = theory.get("hypothesis_name", HYPOTHESIS_NAMES.get(h_id, "unknown"))

    # Revision: the Evaluator re-read the stock row and found stock on hand,
    # so demand is recomputed from issues only (no stock-out adjustment).
    recomputed = False
    if (h_id == "H4" and theory.get("revision_request")
            and "issues only" in str(theory.get("evaluator_critique", "")).lower()
            and (hypothesis_evidence or {}).get("demand_basis") == "stockout_adjusted"):
        hypothesis_evidence = rules.h4_issues_only(hypothesis_evidence)
        recomputed = True

    # Step 1: Assign the verdict deterministically from computed flags
    deterministic = _deterministic_verdict(h_id, hypothesis_evidence)
    strength = rules.evidence_strength(h_id, hypothesis_evidence)

    def finish(result: dict) -> dict:
        result["evidence_strength"] = strength
        if h_id == "H4" and (hypothesis_evidence or {}).get("demand_basis"):
            result["demand_basis"] = hypothesis_evidence["demand_basis"]
        if recomputed:
            result["recomputed_after_critique"] = (
                "demand recomputed from issues only: "
                f"{rules.describe(h_id, hypothesis_evidence)}")
        return result

    if not llm_enabled():
        return finish(_rule_based_evaluation(h_id, h_name, hypothesis_evidence, deterministic))

    system = SINGLE_HYPOTHESIS_SYSTEM.format(
        hypothesis_id=h_id,
        hypothesis_name=h_name,
    )

    payload = {
        "research_question": question,
        "theory": theory,
        "computed_evidence_for_this_hypothesis": hypothesis_evidence,
        "deterministic_verdict": deterministic,
        "instruction": (
            f"The deterministic computed flags show verdict='{deterministic}'. "
            f"Use this verdict in your response and explain why in the reasoning field. "
            f"Do not change the verdict unless data is genuinely missing."
        ),
    }

    try:
        result = ask_agent(system, payload, lane="fast")
        if not isinstance(result, dict) or not isinstance(result.get("reasoning"), str):
            raise ValueError("LLM reply has no 'reasoning' text")
        # Step 2: Always override the LLM's verdict with the deterministic one
        # The LLM is responsible for reasoning/explanation, not the verdict
        result["theory_id"] = h_id
        result["hypothesis_name"] = h_name
        result["verdict"] = deterministic  # authoritative
        result["verdict_source"] = "deterministic"
        result["explanation_source"] = "llm"
        for key in ("supporting_evidence_ids", "contradicting_evidence_ids", "limitations",
                    "additional_analysis_needed"):
            if not isinstance(result.get(key), list):
                result[key] = []
        return finish(result)
    except Exception as exc:  # LLMError, bad JSON shape, or any client failure
        # The explanation falls back to rules; the label says so.
        result = _rule_based_evaluation(h_id, h_name, hypothesis_evidence, deterministic)
        result["limitations"] = result["limitations"] + ["Agent call error"]
        result["_fallback_reason"] = f"LLM explanation unavailable: {str(exc)[:200]}"
        result["explanation_source"] = "local_deterministic_fallback"
        result["_provider"] = "Local deterministic fallback"
        result["_served_model"] = None
        return finish(result)


def investigate_parallel(
    question: str,
    theories: dict,
    computed_evidence: dict,
) -> dict:
    """
    Investigate each of the 7 theories in parallel using a ThreadPoolExecutor.
    Each hypothesis gets its own LLM call (or rule-based explanation when the
    LLM is disabled) with only the relevant evidence slice.

    Parameters
    ----------
    question         : the investigation question
    theories         : output of theory_generator.generate() — has 'theories' list
    computed_evidence: output of data_loader.profile_stockout()['computed_evidence']

    Returns
    -------
    {
        "evaluations": [...],   # one per hypothesis
        "analysis_requests": []
    }
    """
    theory_list = theories.get("theories", [])

    def run_one(theory: dict) -> dict:
        h_id = theory.get("id", "")
        evidence_key = EVIDENCE_KEYS.get(h_id, f"h{h_id[1:]}_unknown")
        hypothesis_evidence = computed_evidence.get(evidence_key, {})
        return _investigate_one(question, theory, hypothesis_evidence)

    evaluations = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as executor:
        futures = {executor.submit(run_one, t): t for t in theory_list}
        for future in concurrent.futures.as_completed(futures):
            try:
                evaluations.append(future.result())
            except Exception as exc:
                theory = futures[future]
                evaluations.append({
                    "theory_id": theory.get("id", "unknown"),
                    "hypothesis_name": theory.get("hypothesis_name", "unknown"),
                    "verdict": "inconclusive",
                    "supporting_evidence_ids": [],
                    "contradicting_evidence_ids": [],
                    "reasoning": f"Parallel investigation failed: {exc}",
                    "limitations": ["Thread execution error"],
                    "additional_analysis_needed": [],
                    "_produced_by": RULE_BASED,
                })

    # Sort by hypothesis ID for deterministic output
    id_order = rules.ID_ORDER
    evaluations.sort(key=lambda e: id_order.index(e.get("theory_id", "H7"))
                     if e.get("theory_id") in id_order else 99)

    producers = sorted({str(e.get("_produced_by", RULE_BASED)) for e in evaluations})
    return {
        "evaluations": evaluations,
        "analysis_requests": [],
        "_produced_by": producers[0] if len(producers) == 1 else "mixed: " + ", ".join(producers),
    }
