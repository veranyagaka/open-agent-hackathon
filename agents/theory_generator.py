"""
agents/theory_generator.py

Theory Generator Agent: generates exactly 7 theories, one per StockyWhy hypothesis.
"""

from llm_client import ask_agent


SYSTEM = """
You are the StockyWhy Theory Generator.

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


def generate(question: str, data_analysis: dict) -> dict:
    """
    Generate 7 theories (one per hypothesis) from the data analysis.
    """
    result = ask_agent(
        SYSTEM,
        {
            "research_question": question,
            "data_analysis": data_analysis,
        },
    )

    theories = result.get("theories", [])

    if len(theories) != 7:
        raise ValueError(
            f"Expected 7 theories (one per hypothesis), got {len(theories)}"
        )

    # Validate hypothesis IDs
    expected_ids = {"H1", "H2", "H3", "H4", "H5", "H6", "H7"}
    returned_ids = {t.get("id") for t in theories}
    missing = expected_ids - returned_ids
    if missing:
        raise ValueError(
            f"Missing hypothesis IDs in theories: {missing}"
        )

    return result
