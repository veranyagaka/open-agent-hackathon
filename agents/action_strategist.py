"""
agents/action_strategist.py

Action Strategist Agent: turns evidence evaluations into actionable
recommendations that ALWAYS require pharmacist review before execution.
With the LLM disabled (llm_client.llm_enabled) the ranking, actions and
drafts are rule-based and cite the evaluations' row ids.
"""

import re

from agents import rules
from llm_client import RULE_BASED, LLMCallCapReached, ask_agent, llm_enabled

MEDICAL_DISCLAIMER = (
    "This system provides decision-support information only. "
    "It does not constitute medical advice, clinical guidance, "
    "or authorisation to act. All proposed actions must be reviewed "
    "and approved by a qualified pharmacist or supply-chain officer "
    "before implementation."
)


SYSTEM = """
You are the StockyWhy Action Strategist.

⚠️  CRITICAL SAFETY RULES — YOU MUST FOLLOW THESE WITHOUT EXCEPTION:
1. NEVER place orders, initiate transfers, or make payments autonomously.
2. NEVER instruct any system to execute a transaction.
3. Every single action you propose MUST include "pharmacist_review_required": true.
4. All documents you draft are PROPOSALS only — they require human sign-off.
5. Do not present an inconclusive theory as established fact.

MEDICAL DISCLAIMER (include in every response):
This system provides decision-support information only. It does not constitute
medical advice, clinical guidance, or authorisation to act. All proposed actions
must be reviewed and approved by a qualified pharmacist or supply-chain officer
before implementation.

Your task is to develop practical, proportionate action proposals from the
evidence investigator's evaluations of a drug stockout.

For each proposed action provide:
- action_id: A1, A2, ...
- action: description of what should happen
- linked_hypothesis_ids: which hypotheses this addresses
- evidence_basis: specific evidence citations (e.g. stock#1746, orders#2825)
- priority: critical|high|medium|low
- proposed_owner: role (not a specific person's name)
- timeframe: e.g. "within 24 hours", "next ordering cycle"
- expected_outcome: what success looks like
- success_measure: how to verify it worked
- risks_and_caveats: what could go wrong
- pharmacist_review_required: true  (ALWAYS true, no exceptions)

Also draft three specific documents:
1. emergency_requisition_memo: A formal request for emergency resupply if stock
   is critically low. Include commodity, quantity, justification, and urgency.
2. transfer_request: If the nearest facility likely has surplus stock, draft a
   transfer request noting the source facility, quantity, and rationale.
   Set to null if not applicable.
3. ordering_schedule_recommendation: A note for the next ordering cycle to prevent
   recurrence — adjusted timing, quantity, or process changes.

Rules:
- Do not recommend expensive or irreversible interventions based solely on weak evidence.
- For inconclusive findings, prefer investigation or reversible pilot actions.
- Do not invent stakeholder names or claim approval.
- Rank the hypotheses by likelihood (most supported first).

Return JSON:
{
  "medical_disclaimer": "This system provides decision-support information only...",
  "ranked_hypotheses": [
    {
      "hypothesis_id": "H1",
      "hypothesis_name": "late_order",
      "likelihood": "high|medium|low",
      "verdict": "supported|weakened|inconclusive",
      "summary": "..."
    }
  ],
  "most_likely_cause": "...",
  "actions": [
    {
      "action_id": "A1",
      "action": "...",
      "linked_hypothesis_ids": [],
      "evidence_basis": "...",
      "priority": "critical|high|medium|low",
      "proposed_owner": "...",
      "timeframe": "...",
      "expected_outcome": "...",
      "success_measure": "...",
      "risks_and_caveats": "...",
      "pharmacist_review_required": true
    }
  ],
  "emergency_requisition_memo": "...",
  "transfer_request": null,
  "ordering_schedule_recommendation": "...",
  "communication_draft": "...",
  "open_questions": []
}
"""


def recommend_actions(
    question: str,
    evaluations: dict,
) -> dict:
    """
    Produce ranked causes and actionable proposals from evidence evaluations.
    Every action includes pharmacist_review_required: true.
    """
    if llm_enabled():
        try:
            result = ask_agent(
                SYSTEM,
                {
                    "research_question": question,
                    "evidence_evaluations": evaluations,
                },
            )
        except LLMCallCapReached as exc:
            result = recommend_actions_rule_based(question, evaluations)
            result["_fallback_reason"] = str(exc)
    else:
        result = recommend_actions_rule_based(question, evaluations)

    # Enforce pharmacist_review_required on every action regardless of LLM output
    for action in result.get("actions", []):
        action["pharmacist_review_required"] = True

    # Ensure medical disclaimer is present
    if "medical_disclaimer" not in result:
        result["medical_disclaimer"] = MEDICAL_DISCLAIMER

    return result


# ---------------------------------------------------------------------------
# Rule-based mode
# ---------------------------------------------------------------------------

# Proportionate response per supported cause: (action, priority, owner, timeframe,
# expected outcome, success measure, caveats).
ACTION_TEMPLATES = {
    "H1": [
        ("Draft an emergency requisition for {commodity} to cover the gap until the slipped delivery arrives.",
         "critical", "Facility pharmacist", "within 24 hours",
         "Stock available until the delayed order is received.",
         "Closing stock above zero at the next stock report.",
         "Emergency supply may duplicate the slipped delivery; size it to the gap only."),
        ("Set an ordering reminder ahead of the cutoff date for the next cycle.",
         "high", "Facility in-charge", "next ordering cycle",
         "Next order submitted on or before the cutoff.",
         "order_date on or before cutoff_date next cycle.",
         "Depends on staff availability at month start."),
    ],
    "H2": [
        ("Raise the under-fill with the supplier and request the undelivered balance.",
         "high", "Sub-county pharmacist", "within 1 week",
         "Undelivered balance confirmed or scheduled.",
         "Facility fill rate back to the county average next cycle.",
         "Supplier may be rationing; confirm before escalating."),
    ],
    "H3": [
        ("Escalate the county arrears to the county finance office with the computed amount owed.",
         "high", "County pharmacist", "within 2 weeks",
         "Payment plan agreed with the supplier.",
         "County fill rate recovers in the following cycle.",
         "Finance decisions are outside the facility's control."),
    ],
    "H4": [
        ("Draft an emergency requisition for {commodity} sized to recent consumption.",
         "critical", "Facility pharmacist", "within 24 hours",
         "Stock covers current demand.",
         "No stockout days in the next stock report.",
         "Confirm the surge is real (not a recording artefact) before ordering extra."),
        ("Revise the next order quantity using the latest consumption instead of the 3-month average.",
         "high", "Facility pharmacist", "next ordering cycle",
         "Order quantity matches current demand.",
         "Closing stock stays above zero next month.",
         "If the surge is temporary, over-ordering raises expiry risk."),
    ],
    "H5": [
        ("Do a physical stock count and reconcile the ledger before any resupply decision.",
         "high", "Facility pharmacist", "within 48 hours",
         "Ledger matches physical stock.",
         "Stock identity holds on the corrected record.",
         "A count reflects today, not the reporting month."),
    ],
    "H6": [
        ("Review expiry and storage practice (FEFO) for {commodity} and record write-off reasons.",
         "medium", "Facility pharmacist", "within 1 week",
         "Avoidable wastage identified.",
         "Wastage back near its 3-month average.",
         "Some expiry is unavoidable with low-turnover items."),
    ],
    "H7": [
        ("Check supplier and KEMSA notices and ask the sub-county about redistribution between facilities.",
         "high", "Sub-county pharmacist", "within 72 hours",
         "Alternative source or transfer identified.",
         "Facility receives stock despite the disruption.",
         "Transfers can leave the source facility short."),
    ],
}

INVESTIGATE_ACTION = (
    "Gather the missing data for {hypothesis} before acting on it.",
    "medium", "Facility pharmacist", "within 1 week",
    "Hypothesis confirmed or ruled out.",
    "Computed check can be run with complete data.",
    "Do not act on an inconclusive finding.",
)

_QUESTION = re.compile(r"facility\s+(\S+)\s+report a stockout of\s+(.+?)\s+in\s+(\d{4}-\d{2})", re.I)


def _case_from_question(question: str) -> tuple:
    m = _QUESTION.search(question or "")
    if m:
        return m.group(1), m.group(2), m.group(3)
    return "the facility", "the commodity", "the reporting month"


def _likelihood(verdict: str, position: int) -> str:
    if verdict == "supported":
        return "high" if position == 0 else "medium"
    if verdict == "inconclusive":
        return "medium" if position == 0 else "low"
    return "low"


def _make_action(n: int, template: tuple, h_ids: list, basis: str, commodity: str, hypothesis: str = "") -> dict:
    text, priority, owner, timeframe, outcome, measure, caveats = template
    return {
        "action_id": f"A{n}",
        "action": text.format(commodity=commodity, hypothesis=hypothesis),
        "linked_hypothesis_ids": h_ids,
        "evidence_basis": basis,
        "priority": priority,
        "proposed_owner": owner,
        "timeframe": timeframe,
        "expected_outcome": outcome,
        "success_measure": measure,
        "risks_and_caveats": caveats,
        "pharmacist_review_required": True,
    }


def recommend_actions_rule_based(question: str, evaluations: dict) -> dict:
    """
    Rank hypotheses by verdict then evidence strength, and draft proportionate,
    reviewable actions for supported causes only.
    """
    facility, commodity, month = _case_from_question(question)
    evals = list((evaluations or {}).get("evaluations", []))
    evals.sort(key=lambda e: rules.rank_key(
        e.get("verdict"), e.get("evidence_strength"), e.get("theory_id", "")
    ))

    ranked = []
    for position, e in enumerate(evals):
        h_id = e.get("theory_id", "?")
        verdict = e.get("verdict", "inconclusive")
        ranked.append({
            "hypothesis_id": h_id,
            "hypothesis_name": e.get("hypothesis_name", rules.HYPOTHESIS_NAMES.get(h_id, "unknown")),
            "likelihood": _likelihood(verdict, position),
            "verdict": verdict,
            "evidence_strength": e.get("evidence_strength"),
            "summary": e.get("reasoning", ""),
            "evidence_ids": e.get("supporting_evidence_ids") or e.get("contradicting_evidence_ids") or [],
        })

    supported = [r for r in ranked if r["verdict"] == "supported"]
    inconclusive = [r for r in ranked if r["verdict"] == "inconclusive"]

    if supported:
        top = supported[0]
        most_likely = f"{top['hypothesis_name']} ({top['hypothesis_id']}): {top['summary']}"
        most_likely_id = top["hypothesis_id"]
    else:
        most_likely = (
            "undetermined: no hypothesis passes its computed threshold; "
            "investigate before acting."
        )
        most_likely_id = None

    actions = []
    for r in supported:
        missing_ids = [i for i in r["evidence_ids"] if i not in r["summary"]]
        basis = r["summary"] if not missing_ids else f"{', '.join(missing_ids)}: {r['summary']}"
        for template in ACTION_TEMPLATES.get(r["hypothesis_id"], []):
            actions.append(_make_action(len(actions) + 1, template, [r["hypothesis_id"]], basis, commodity))
    for r in inconclusive:
        actions.append(_make_action(
            len(actions) + 1, INVESTIGATE_ACTION, [r["hypothesis_id"]],
            r["summary"], commodity, f"{r['hypothesis_id']} {r['hypothesis_name']}",
        ))
    if not actions:
        actions.append(_make_action(
            1, INVESTIGATE_ACTION, [], "No supported hypothesis in the evaluations.",
            commodity, "the stockout",
        ))

    cited = ", ".join(i for r in supported for i in r["evidence_ids"]) or "the computed evidence"
    cause_line = (
        f"Most likely cause: {supported[0]['hypothesis_name']} ({supported[0]['hypothesis_id']})."
        if supported else "Cause not established by the computed checks."
    )
    memo = (
        f"DRAFT — requires pharmacist sign-off.\n"
        f"Subject: Emergency requisition, {commodity}, {facility}\n"
        f"{facility} reported a stockout of {commodity} in {month}. {cause_line}\n"
        f"Evidence: {cited}.\n"
        f"Quantity: to be set by the pharmacist from current consumption records."
    )
    schedule = {
        "H1": "Submit the order before the cutoff date; set a reminder several days ahead.",
        "H4": "Base the next order on the most recent month's consumption, not only the 3-month average.",
        "H2": "Check delivery notes against orders on receipt and report short deliveries the same week.",
        "H6": "Apply FEFO and review expiry dates monthly.",
    }.get(most_likely_id, "Keep the current ordering schedule and re-check after the next stock report.")
    communication = (
        f"DRAFT — for pharmacist review.\nTo: County pharmacist\n"
        f"Re: {commodity} stockout at {facility}, {month}\n"
        f"{cause_line} Evidence: {cited}. Proposed actions are attached for review; "
        f"none will be executed without approval."
    )

    open_questions = [
        f"{r['hypothesis_id']} {r['hypothesis_name']}: data missing or borderline." for r in inconclusive
    ]
    if len(supported) > 1:
        open_questions.append(
            "More than one cause passes its threshold: "
            + ", ".join(r["hypothesis_id"] for r in supported)
            + ". Their relative contribution is not established."
        )

    return {
        "medical_disclaimer": MEDICAL_DISCLAIMER,
        "ranked_hypotheses": ranked,
        "most_likely_cause": most_likely,
        "most_likely_hypothesis_id": most_likely_id,
        "actions": actions,
        "emergency_requisition_memo": memo,
        "transfer_request": None,
        "ordering_schedule_recommendation": schedule,
        "communication_draft": communication,
        "open_questions": open_questions,
        "_produced_by": RULE_BASED,
    }
