"""
agents/theory_generator.py

Theory Generator Agent: generates exactly 7 theories, one per StockWhy hypothesis.
With the LLM disabled (llm_client.llm_enabled) the theories come from fixed
domain templates, annotated with the analyst's computed signal for each.
"""

from agents import rules
from llm_client import RULE_BASED, ask_agent, llm_enabled


SYSTEM = """
You are the StockWhy Theory Generator.

Generate exactly SEVEN theories answering the research question — one theory
per hypothesis below. Map each theory to its hypothesis ID.

Hypotheses (use these exact IDs):
  H1 late_order         — the facility ordered after the cutoff date, so delivery
                          slipped into the following month, leaving a gap
  H2 supplier_underfill — the supplier delivered significantly less than requested
                          to THIS facility compared to peer facilities in the same cycle
  H3 payment_arrears    — the county owed >=30M KES and the supplier reduced county-wide
                          deliveries in response to non-payment
  H4 demand_surge       — consumption spiked >25% above the 3-month average, exhausting
                          stock faster than anticipated
  H5 record_error       — the stockout days were recorded in error; the stock identity
                          equation contradicts a genuine stockout
  H6 expiry             — a large wastage write-off (expiry or damage) depleted usable
                          stock, causing the shortfall
  H7 national_disruption— a national supply disruption (tender failure, logistics
                          breakdown, public notice) reduced deliveries county-wide

Each theory must include:
- id: H1 through H7 (matching the hypothesis)
- hypothesis_name: the snake_case name above
- title: a concise human-readable label
- mechanism: how the proposed explanation leads to a stockout
- evidence_needed: what observations would support it
- disconfirming_evidence: what would weaken it
- predictions: observable outcomes if it is true

Use the supplied data analysis as leads, not as proof.
Do not invent data or claim causation without evidence.

Return JSON:
{
  "theories": [
    {
      "id": "H1",
      "hypothesis_name": "late_order",
      "title": "...",
      "mechanism": "...",
      "evidence_needed": [],
      "disconfirming_evidence": [],
      "predictions": []
    }
  ]
}
"""


# Domain templates for rule-based mode. They describe mechanisms and tests,
# never case-specific numbers.
THEORY_TEMPLATES = {
    "H1": {
        "mechanism": "The order meant to deliver this month was placed after the ordering cutoff, so delivery slipped to the following month and stock ran out before it arrived.",
        "evidence_needed": ["order_date later than cutoff_date on the previous month's order", "delivery_month later than the stockout month"],
        "disconfirming_evidence": ["Order placed on or before the cutoff", "Delivery arrived in the stockout month"],
        "predictions": ["received is 0 or low in the stockout month", "A delivery lands the following month"],
    },
    "H2": {
        "mechanism": "The supplier delivered much less than requested to this facility compared with peers in the same cycle, leaving too little stock.",
        "evidence_needed": ["Facility fill rate more than 5 points below the county average for the cycle"],
        "disconfirming_evidence": ["Facility fill rate at or above the county average"],
        "predictions": ["qty_delivered well below qty_requested for this facility only"],
    },
    "H3": {
        "mechanism": "The county owed the supplier at least 30M KES and the supplier cut deliveries county-wide until paid.",
        "evidence_needed": ["County arrears flag with amount owed >= 30,000,000 KES", "County-wide fill rate falling vs the previous month"],
        "disconfirming_evidence": ["No arrears flag, or arrears below the threshold", "County fill rate stable or rising"],
        "predictions": ["Many facilities under-filled in the same month"],
    },
    "H4": {
        "mechanism": "Consumption jumped more than 25% above the 3-month average, exhausting stock faster than the ordering cycle planned for.",
        "evidence_needed": ["consumed this month > 1.25 x the 3-month average"],
        "disconfirming_evidence": ["Consumption at or below the recent average"],
        "predictions": ["Stock reaches zero mid-month despite a normal delivery"],
    },
    "H5": {
        "mechanism": "The reported stockout is a recording error: the stock ledger does not add up, or stockout days conflict with stock on hand.",
        "evidence_needed": ["opening + received - wastage - consumed differs from reported closing", "Stockout days reported while closing stock is above zero"],
        "disconfirming_evidence": ["Stock identity holds and closing is zero"],
        "predictions": ["A physical count differs from the ledger"],
    },
    "H6": {
        "mechanism": "A large expiry or damage write-off removed usable stock, causing the shortfall.",
        "evidence_needed": ["Wastage more than 2x its 3-month average and above 10% of average consumption"],
        "disconfirming_evidence": ["Wastage near zero or at its normal level"],
        "predictions": ["Expired batches recorded in the stockout month"],
    },
    "H7": {
        "mechanism": "A national supply disruption (tender failure, logistics breakdown) reduced deliveries county-wide and was publicly announced.",
        "evidence_needed": ["Public notice for this commodity within 2 months", "County-wide fill-rate drop vs the previous month"],
        "disconfirming_evidence": ["No public notice", "County fill rate stable"],
        "predictions": ["Several facilities short of the same commodity at once"],
    },
}


def _analyst_signal(data_analysis: dict, h_id: str):
    """Read the analyst's signal for one hypothesis (accepts H-ids or evidence keys)."""
    signals = (data_analysis or {}).get("hypothesis_signals") or {}
    entry = signals.get(h_id) or signals.get(rules.EVIDENCE_KEYS[h_id])
    if isinstance(entry, dict):
        return entry.get("signal"), entry.get("reasoning")
    if isinstance(entry, str):
        return entry, None
    return None, None


def generate_rule_based(question: str, data_analysis: dict) -> dict:
    """Seven template theories, each tagged with the analyst's lead signal."""
    theories = []
    for h_id in rules.ID_ORDER:
        template = THEORY_TEMPLATES[h_id]
        lead_signal, lead_reasoning = _analyst_signal(data_analysis, h_id)
        theory = {
            "id": h_id,
            "hypothesis_name": rules.HYPOTHESIS_NAMES[h_id],
            "title": rules.TITLES[h_id],
            "mechanism": template["mechanism"],
            "evidence_needed": list(template["evidence_needed"]),
            "disconfirming_evidence": list(template["disconfirming_evidence"]),
            "predictions": list(template["predictions"]),
            "lead_signal": lead_signal or "unknown",
        }
        if lead_reasoning:
            theory["lead_reasoning"] = lead_reasoning
        theories.append(theory)
    return {"theories": theories, "_produced_by": RULE_BASED}


def generate(question: str, data_analysis: dict) -> dict:
    """
    Generate 7 theories (one per hypothesis) from the data analysis.
    """
    if not llm_enabled():
        return generate_rule_based(question, data_analysis)
    try:
        result = ask_agent(
            SYSTEM,
            {
                "research_question": question,
                "data_analysis": data_analysis,
            },
        )
        validate_theories(result)
        return result
    except Exception as exc:  # LLMError or a reply in the wrong shape
        result = generate_rule_based(question, data_analysis)
        result["_fallback_reason"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return result


def validate_theories(result) -> None:
    """Raise ValueError unless there is exactly one theory per hypothesis H1-H7."""
    theories = result.get("theories") if isinstance(result, dict) else None
    if not isinstance(theories, list) or len(theories) != 7:
        n = len(theories) if isinstance(theories, list) else 0
        raise ValueError(f"Expected 7 theories (one per hypothesis), got {n}")
    if any(not isinstance(t, dict) for t in theories):
        raise ValueError("Every theory must be an object")
    missing = set(rules.ID_ORDER) - {t.get("id") for t in theories}
    if missing:
        raise ValueError(f"Missing hypothesis IDs in theories: {sorted(missing)}")
