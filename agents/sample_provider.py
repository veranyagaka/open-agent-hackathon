"""Credential-free, evidence-grounded responses for the documented sample mode."""

import json
import re


HYPOTHESES = (
    ("H1", "late_order", "Late ordering"),
    ("H2", "supplier_underfill", "Supplier underfill"),
    ("H3", "payment_arrears", "Payment arrears"),
    ("H4", "demand_surge", "Demand surge"),
    ("H5", "record_error", "Stock record error"),
    ("H6", "expiry", "Expiry or wastage"),
    ("H7", "national_disruption", "National supply disruption"),
)


def _records(payload, key):
    records = payload.get(key, [])
    return records if isinstance(records, list) else []


def _record_ids(rows, table):
    return [
        f"{table}#{row['id']}"
        for row in rows
        if isinstance(row, dict) and row.get("id") is not None
    ]


def _sample_data_reader(payload):
    stock = _records(payload, "stock_record")
    orders = _records(payload, "order_record")
    payments = _records(payload, "payments_history")
    history = _records(payload, "stock_history")
    web_notes = _records(payload, "web_notes")
    computed = payload.get("computed_evidence", {})
    warnings = []
    if not stock:
        warnings.append("No stock row matched the requested facility, commodity, and month.")
    if not orders:
        warnings.append("No order row matched the requested facility, commodity, and month.")

    return {
        "dataset_summary": {
            "stock_rows": len(stock),
            "order_rows": len(orders),
            "history_months_available": len(history),
            "has_payment_records": bool(payments),
            "has_web_notes": bool(web_notes),
        },
        "relevant_records": {
            "stock_ids": _record_ids(stock, "stock"),
            "order_ids": _record_ids(orders, "orders"),
            "payment_months": sorted({
                str(row["month"])
                for row in payments
                if isinstance(row, dict) and row.get("month") is not None
            }),
        },
        "data_quality_flags": [],
        "evidence_for_hypotheses": {
            key: json.dumps(value, sort_keys=True, default=str)
            for key, value in computed.items()
        },
        "missing_data_warnings": warnings,
        "_sample_mode": True,
    }


def _sample_analysis(payload):
    computed = payload.get("computed_evidence", {})
    signals = {}
    descriptions = []
    for hypothesis_id, key, name in HYPOTHESES:
        evidence = computed.get(f"h{hypothesis_id[1:]}_{key}", {})
        missing = evidence.get("data_missing", False)
        primary = {
            "H1": bool(evidence.get("late") or evidence.get("delivery_slipped")),
            "H2": evidence.get("underfill"),
            "H3": evidence.get("major_arrears"),
            "H4": evidence.get("surge"),
            "H5": (
                evidence.get("identity_holds") is False
                or evidence.get("stockout_days_plausible") is False
            ),
            "H6": evidence.get("high_wastage"),
            "H7": bool(
                evidence.get("web_notice_found")
                and (evidence.get("county_fill_drop") or 0) > 0
            ),
        }[hypothesis_id]
        if missing:
            signal = "inconclusive"
        elif primary is True:
            signal = "strong"
        elif primary is False:
            signal = "none"
        else:
            signal = "inconclusive"
        signals[hypothesis_id] = {
            "signal": signal,
            "reasoning": (
                f"Deterministic evidence for {name}: "
                f"{json.dumps(evidence, sort_keys=True, default=str)}"
            ),
        }
        descriptions.append(f"{name}: {signal}")

    return {
        "analysis_summary": (
            "Offline analysis of computed records only. " + "; ".join(descriptions)
        ),
        "hypothesis_signals": signals,
        "data_quality_issues": [],
        "observed_patterns": [],
        "evidence_gaps": [],
        "recommended_tests": [],
        "primary_leads": [],
        "data_limitations": [],
        "_sample_mode": True,
    }


def _sample_theories():
    return {
        "theories": [
            {
                "id": hypothesis_id,
                "hypothesis_name": key,
                "title": name,
                "mechanism": (
                    f"{name} could contribute to a stockout; this is a "
                    "hypothesis, not a finding."
                ),
                "evidence_needed": ["Relevant source records and computed evidence"],
                "disconfirming_evidence": ["Records inconsistent with the proposed mechanism"],
                "predictions": ["A matching pattern in source records"],
            }
            for hypothesis_id, key, name in HYPOTHESES
        ],
        "_sample_mode": True,
    }


def _sample_investigation(payload):
    theory = payload.get("theory", {})
    hypothesis_id = theory.get("id", "")
    evidence = payload.get("computed_evidence_for_this_hypothesis", {})
    verdict = payload.get("deterministic_verdict", "inconclusive")
    citations = sorted(set(re.findall(
        r"(?:stock|orders|payments|facilities)#[-A-Za-z0-9_.]+",
        json.dumps(evidence, default=str),
    )))
    return {
        "theory_id": hypothesis_id,
        "hypothesis_name": theory.get("hypothesis_name", "unknown"),
        "verdict": verdict,
        "supporting_evidence_ids": citations if verdict == "supported" else [],
        "contradicting_evidence_ids": citations if verdict == "weakened" else [],
        "reasoning": (
            f"Deterministic result: {verdict}. "
            f"Evidence identifiers present: {', '.join(citations) or 'none'}."
        ),
        "limitations": (
            ["Source data is missing."]
            if evidence.get("data_missing")
            else ["Offline sample mode does not use an external language model."]
        ),
        "additional_analysis_needed": [],
        "_sample_mode": True,
    }


def _sample_actions(payload):
    evaluations = payload.get("evidence_evaluations", {}).get("evaluations", [])
    supported = [item for item in evaluations if item.get("verdict") == "supported"]
    ranked_hypotheses = [
        {
            "hypothesis_id": item.get("theory_id"),
            "hypothesis_name": item.get("hypothesis_name", "unknown"),
            "verdict": item.get("verdict", "inconclusive"),
            "likelihood": "not assessed (offline)",
        }
        for item in evaluations
    ]
    actions = []
    for index, evaluation in enumerate(supported, 1):
        name = evaluation.get("hypothesis_name", "the supported hypothesis")
        citations = evaluation.get("supporting_evidence_ids", [])
        actions.append({
            "action_id": f"A{index}",
            "action": (
                f"Verify the {name.replace('_', ' ')} finding with the relevant "
                "supply-chain records and prepare a response for pharmacist review."
            ),
            "linked_hypothesis_ids": [evaluation.get("theory_id", "")],
            "evidence_basis": ", ".join(citations) or "Deterministic evidence; no row identifier returned.",
            "priority": "medium",
            "proposed_owner": "Facility pharmacist",
            "timeframe": "Before the next ordering decision",
            "expected_outcome": "The finding is checked against source records.",
            "success_measure": "Pharmacist records a review outcome.",
            "risks_and_caveats": "Do not implement without pharmacist approval.",
            "pharmacist_review_required": True,
        })
    if not actions:
        actions.append({
            "action_id": "A1",
            "action": (
                "Review the available stock and order records with the pharmacist "
                "before drawing a cause or taking action."
            ),
            "linked_hypothesis_ids": [],
            "evidence_basis": "No hypothesis was deterministically supported.",
            "priority": "low",
            "proposed_owner": "Facility pharmacist",
            "timeframe": "Before the next ordering decision",
            "expected_outcome": "Data gaps or contradictory records are identified.",
            "success_measure": "Pharmacist records a review outcome.",
            "risks_and_caveats": "This is a review proposal, not a clinical recommendation.",
            "pharmacist_review_required": True,
        })

    return {
        "most_likely_cause": (
            supported[0].get("hypothesis_name", "inconclusive")
            if len(supported) == 1
            else "multiple supported hypotheses; no probability ranking in offline mode"
            if supported
            else "inconclusive"
        ),
        "ranked_hypotheses": ranked_hypotheses,
        "actions": actions,
        "medical_disclaimer": (
            "This system provides decision-support information only. It does not "
            "constitute medical advice. All proposed actions require pharmacist "
            "review and approval."
        ),
        "communication_draft": "",
        "open_questions": ["Confirm the records and review the proposal with a pharmacist."],
        "_sample_mode": True,
    }


def respond(system_prompt, payload):
    """Return an offline response for StockWhy's known stages."""
    prompt = system_prompt.lower()
    if "data reader agent" in prompt:
        response = _sample_data_reader(payload)
    elif "theory generator" in prompt:
        response = _sample_theories()
    elif "action strategist" in prompt:
        response = _sample_actions(payload)
    elif "evidence investigator" in prompt:
        response = _sample_investigation(payload)
    elif "data analyst" in prompt:
        if "computed_evidence" in payload:
            response = _sample_analysis(payload)
        else:
            response = {
                "dataset_overview": "Offline analysis of the supplied profile.",
                "data_quality_issues": [],
                "observed_patterns": [],
                "evidence_gaps": [],
                "recommended_tests": [],
            }
    else:
        raise RuntimeError(
            "SAMPLE_MODE has no offline response for this agent stage. "
            "Configure Meterless Nightshift or use a supported StockWhy agent."
        )
    response.update({
        "_provider": "StockWhy offline sample provider",
        "_requested_model": None,
        "_served_model": None,
    })
    return response
