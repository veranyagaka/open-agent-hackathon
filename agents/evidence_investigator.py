"""
agents/evidence_investigator.py

Evidence Investigator Agent: evaluates theories against computed evidence.
Supports sequential (investigate) and parallel (investigate_parallel) modes.
"""

import concurrent.futures
from llm_client import ask_agent


SYSTEM = """
You are the StockyWhy Evidence Investigator.

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
You are the StockyWhy Evidence Investigator.

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

# Maps hypothesis ID to snake_case name
HYPOTHESIS_NAMES = {
    "H1": "late_order",
    "H2": "supplier_underfill",
    "H3": "payment_arrears",
    "H4": "demand_surge",
    "H5": "record_error",
    "H6": "expiry",
    "H7": "national_disruption",
}

# Maps hypothesis ID to computed_evidence key
EVIDENCE_KEYS = {
    "H1": "h1_late_order",
    "H2": "h2_supplier_underfill",
    "H3": "h3_payment_arrears",
    "H4": "h4_demand_surge",
    "H5": "h5_record_error",
    "H6": "h6_expiry",
    "H7": "h7_national_disruption",
}


def investigate(
    question: str,
    theories: dict,
    data_analysis: dict,
    test_results: list,
) -> dict:
    """Original sequential investigate function — kept intact."""
    return ask_agent(
        SYSTEM,
        {
            "research_question": question,
            "theories": theories,
            "data_analysis": data_analysis,
            "computed_test_results": test_results,
        },
    )


def _deterministic_verdict(hypothesis_id: str, hypothesis_evidence: dict) -> str:
    """
    Assign a verdict deterministically based on computed flags.

    This is the source of truth — the LLM explains the reasoning but
    the verdict itself comes from the deterministic calculations.

    Returns "supported", "weakened", or "inconclusive".
    """
    if hypothesis_evidence.get("data_missing"):
        return "inconclusive"

    if hypothesis_id == "H1":
        if hypothesis_evidence.get("late") or hypothesis_evidence.get("delivery_slipped"):
            return "supported"
        return "weakened"

    elif hypothesis_id == "H2":
        if hypothesis_evidence.get("underfill"):
            return "supported"
        return "weakened"

    elif hypothesis_id == "H3":
        if hypothesis_evidence.get("major_arrears"):
            return "supported"
        return "weakened"

    elif hypothesis_id == "H4":
        pct = hypothesis_evidence.get("pct_change")
        if hypothesis_evidence.get("surge") or (pct is not None and pct > 25):
            return "supported"
        return "weakened"

    elif hypothesis_id == "H5":
        # Record error: identity_holds=False means there IS an error (supported)
        if hypothesis_evidence.get("identity_holds") is False:
            return "supported"
        if hypothesis_evidence.get("stockout_days_plausible") is False:
            return "supported"
        return "weakened"

    elif hypothesis_id == "H6":
        if hypothesis_evidence.get("high_wastage"):
            return "supported"
        return "weakened"

    elif hypothesis_id == "H7":
        fill_drop = hypothesis_evidence.get("county_fill_drop") or 0
        if hypothesis_evidence.get("web_notice_found") and fill_drop > 0:
            return "supported"
        if hypothesis_evidence.get("web_notice_found") or fill_drop > 0.1:
            return "inconclusive"
        return "weakened"

    return "inconclusive"


def _investigate_one(
    question: str,
    theory: dict,
    hypothesis_evidence: dict,
) -> dict:
    """Investigate a single hypothesis in isolation."""
    h_id = theory.get("id", "H?")
    h_name = theory.get("hypothesis_name", HYPOTHESIS_NAMES.get(h_id, "unknown"))

    # Step 1: Assign the verdict deterministically from computed flags
    deterministic = _deterministic_verdict(h_id, hypothesis_evidence)

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
        result = ask_agent(system, payload)
        # Step 2: Always override the LLM's verdict with the deterministic one
        # The LLM is responsible for reasoning/explanation, not the verdict
        result["theory_id"] = h_id
        result["hypothesis_name"] = h_name
        result["verdict"] = deterministic  # authoritative
        result["verdict_source"] = "deterministic"
        result["explanation_source"] = (
            "meterless_nightshift"
            if result.get("_provider") == "Meterless Nightshift"
            else "local_provider"
        )
        return result
    except Exception as exc:
        request_metadata = getattr(exc, "request_metadata", None)
        return {
            "theory_id": h_id,
            "hypothesis_name": h_name,
            "verdict": deterministic,
            "verdict_source": "deterministic",
            "explanation_source": "local_deterministic_fallback",
            "_provider": "Local deterministic fallback",
            "_requested_model": (
                request_metadata.get("requested_model")
                if isinstance(request_metadata, dict) else None
            ),
            "_served_model": None,
            "_request_metadata": request_metadata,
            "_request_error_category": (
                request_metadata.get("error_category")
                if isinstance(request_metadata, dict) else "unclassified_error"
            ),
            "supporting_evidence_ids": [],
            "contradicting_evidence_ids": [],
            "reasoning": (
                f"Deterministic verdict: {deterministic}. "
                "Nightshift explanation unavailable; see request telemetry."
            ),
            "limitations": ["Agent call error"],
            "additional_analysis_needed": [],
        }


def investigate_parallel(
    question: str,
    theories: dict,
    computed_evidence: dict,
) -> dict:
    """
    Investigate each of the 7 theories in parallel using a ThreadPoolExecutor.
    Each hypothesis gets its own LLM call with only the relevant evidence slice.

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
                    "explanation_source": "local_parallel_fallback",
                    "_provider": "Local parallel fallback",
                    "_served_model": None,
                    "_request_metadata": getattr(
                        exc, "request_metadata", None
                    ),
                    "_request_error_category": "parallel_execution_error",
                    "limitations": ["Thread execution error"],
                    "additional_analysis_needed": [],
                })

    # Sort by hypothesis ID for deterministic output
    id_order = ["H1", "H2", "H3", "H4", "H5", "H6", "H7"]
    evaluations.sort(key=lambda e: id_order.index(e.get("theory_id", "H7"))
                     if e.get("theory_id") in id_order else 99)

    return {
        "evaluations": evaluations,
        "analysis_requests": [],
    }
