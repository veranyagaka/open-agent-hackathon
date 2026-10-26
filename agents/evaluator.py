"""
agents/evaluator.py

Evaluator Agent: the independent checker that sits between the Evidence
Investigators and the Action Strategist. Deterministic, no LLM.

It does four things with every evaluation an investigator returns:

  1. verify_citations   — every row id the evaluation cites must exist in the
                          loaded dataset, and every number it relies on must
                          match that row when the row is re-read.
  2. check_consistency  — the verdict must agree with the deterministic flag
                          in computed_evidence (its own rule, not the
                          investigator's).
  3. cross_critique     — one hypothesis's evidence can undermine another's
                          verdict (e.g. a "demand surge" read from a ledger
                          whose stock identity is broken).
  4. check_coverage     — do the verified supported causes explain the
                          stock-out? If not, ask for a second wave; if still
                          nothing, say "insufficient evidence" and escalate.

The orchestrator uses the reports to send failed evaluations back to the
investigator once (with the critique), then drops whatever is still
unverified. Nothing reaches the final result without a verified row id.
"""

import math
import re

from agents import rules

HYPOTHESIS_NAMES = {
    "H1": "late_order",
    "H2": "supplier_underfill",
    "H3": "payment_arrears",
    "H4": "demand_surge",
    "H5": "record_error",
    "H6": "expiry",
    "H7": "national_disruption",
}

EVIDENCE_KEYS = {
    "H1": "h1_late_order",
    "H2": "h2_supplier_underfill",
    "H3": "h3_payment_arrears",
    "H4": "h4_demand_surge",
    "H5": "h5_record_error",
    "H6": "h6_expiry",
    "H7": "h7_national_disruption",
}

HYPOTHESIS_ORDER = ["H1", "H2", "H3", "H4", "H5", "H6", "H7"]

# A citation looks like "stock#1506", "orders#3161", "payments#17", "web_notes#0".
ROW_ID_RE = re.compile(r"^(stock|orders|payments|web_notes|facilities)#([\w\-.]+)$")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _prev_months(month: str, n: int) -> list:
    y, mo = int(month[:4]), int(month[5:7])
    out = []
    for _ in range(n):
        mo -= 1
        if mo == 0:
            mo, y = 12, y - 1
        out.append(f"{y:04d}-{mo:02d}")
    return out


def _num(value):
    """Return a finite float or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _text(value) -> str:
    """Normalise a cell for string comparison (dates compare as YYYY-MM-DD)."""
    if value is None:
        return ""
    if hasattr(value, "date") and callable(value.date) and hasattr(value, "year"):
        try:
            return str(value.date())
        except Exception:
            pass
    return str(value).strip()


def _values_match(claimed, actual) -> bool:
    c, a = _num(claimed), _num(actual)
    if c is not None and a is not None:
        tol = 0.001 if abs(a) <= 1.0 and abs(c) <= 1.0 else 0.5
        return abs(c - a) <= tol
    ct, at = _text(claimed), _text(actual)
    if ct == at:
        return True
    # "2026-03-08" vs "2026-03-08 00:00:00"
    return len(ct) >= 7 and at.startswith(ct) or len(at) >= 7 and ct.startswith(at)


def is_row_id(value) -> bool:
    return isinstance(value, str) and bool(ROW_ID_RE.match(value.strip()))


def hypothesis_evidence(computed_evidence: dict, h_id: str) -> dict:
    ev = (computed_evidence or {}).get(EVIDENCE_KEYS.get(h_id, ""), {})
    return ev if isinstance(ev, dict) else {}


# ---------------------------------------------------------------------------
# Row lookup — re-read the row from the loaded dataset
# ---------------------------------------------------------------------------

def lookup_row(dataset: dict, row_id: str):
    """Return the row a citation points at as a dict, or None if it does not exist."""
    if not dataset or not is_row_id(row_id):
        return None
    table, key = ROW_ID_RE.match(row_id.strip()).groups()

    if table == "web_notes":
        notes = dataset.get("web_notes") or []
        try:
            idx = int(key)
        except ValueError:
            return None
        return dict(notes[idx]) if 0 <= idx < len(notes) else None

    df = dataset.get(table)
    if df is None or not hasattr(df, "columns"):
        return None
    id_col = "facility_id" if table == "facilities" else "id"
    if id_col not in df.columns:
        return None
    hit = df[df[id_col].astype(str).str.strip() == key]
    if hit.empty:
        return None
    return hit.iloc[0].to_dict()


def _field_value(table: str, row: dict, field: str):
    """Read a field from a row, including two derived fields."""
    if field == "fill_rate" and table == "orders":
        req, dlv = _num(row.get("qty_requested")), _num(row.get("qty_delivered"))
        if req and req > 0 and dlv is not None:
            return min(dlv / req, 1.0)
        return None
    if field == "computed_closing" and table == "stock":
        parts = [_num(row.get(k)) for k in ("opening", "received", "wastage", "consumed")]
        if any(p is None for p in parts):
            return None
        opening, received, wastage, consumed = parts
        return opening + received - wastage - consumed
    if field not in row:
        raise KeyError(field)
    return row[field]


# ---------------------------------------------------------------------------
# Claims: which rows and numbers does an evaluation rely on?
# ---------------------------------------------------------------------------

def derive_claims(h_id: str, evidence: dict, dataset: dict = None, month: str = None) -> dict:
    """
    Turn a hypothesis's computed evidence into row-level claims:
    {row_id: {field: value}}. These are the numbers the investigator's
    verdict rests on, so they are what the Evaluator re-reads.
    """
    ev = evidence or {}
    claims = {}

    def put(row_id, **fields):
        if not row_id:
            return
        clean = {k: v for k, v in fields.items() if v is not None}
        claims.setdefault(row_id, {}).update(clean)

    if h_id == "H1":
        put(ev.get("order_id"), order_date=ev.get("order_date"),
            cutoff_date=ev.get("cutoff_date"), delivery_month=ev.get("delivery_month"))
    elif h_id == "H2":
        put(ev.get("order_id"), fill_rate=ev.get("facility_fill_rate"))
    elif h_id == "H4":
        put(ev.get("stock_id"), consumed=ev.get("consumed_this_month"))
    elif h_id == "H5":
        put(ev.get("stock_id"), closing=ev.get("reported_closing"),
            reported_stockout_days=ev.get("reported_stockout_days"),
            computed_closing=ev.get("computed_closing"))
    elif h_id == "H6":
        put(ev.get("stock_id"), wastage=ev.get("wastage_this_month"))
    elif h_id == "H3" and dataset is not None and month and ev.get("arrears_in_month"):
        payments = dataset.get("payments")
        if payments is not None and hasattr(payments, "columns") and "id" in payments.columns:
            window = {month, *_prev_months(month, 3)}
            for _, row in payments[payments["month"].isin(window)].iterrows():
                if _num(row.get("county_arrears_flag")) == 1:
                    put(f"payments#{row['id']}", county_arrears_flag=1,
                        amount_owed_kes=_num(row.get("amount_owed_kes")))
    elif h_id == "H7" and dataset is not None and ev.get("web_notice_found"):
        notice = ev.get("notice_details") or {}
        for i, note in enumerate(dataset.get("web_notes") or []):
            if (note.get("month") == notice.get("month")
                    and note.get("commodity") == notice.get("commodity")
                    and note.get("title") == notice.get("title")):
                put(f"web_notes#{i}", month=note.get("month"), commodity=note.get("commodity"))
                break
    return claims


def attach_claims(evaluation: dict, computed_evidence: dict, dataset: dict = None,
                  month: str = None) -> dict:
    """Add `cited_values` (row-level claims) to an evaluation, keeping any it already has."""
    h_id = evaluation.get("theory_id", "")
    derived = derive_claims(h_id, hypothesis_evidence(computed_evidence, h_id), dataset, month)
    own = evaluation.get("cited_values")
    if isinstance(own, dict):
        for rid, fields in own.items():
            if isinstance(fields, dict):
                derived.setdefault(rid, {}).update(fields)
    evaluation["cited_values"] = derived
    return evaluation


def cited_row_ids(evaluation: dict) -> list:
    """Every row id an evaluation cites (claims first, then the investigator's lists)."""
    ids = list((evaluation.get("cited_values") or {}).keys())
    for key in ("supporting_evidence_ids", "contradicting_evidence_ids"):
        for rid in evaluation.get(key) or []:
            if is_row_id(rid) and rid not in ids:
                ids.append(rid.strip())
    return ids


# ---------------------------------------------------------------------------
# 1. Citations
# ---------------------------------------------------------------------------

def verify_citations(evaluation: dict, dataset: dict) -> dict:
    """
    Re-read every cited row. A claim fails if its row does not exist or a
    cited number does not match the row.

    Returns {"ok", "verified": [row ids], "failures": [...], "core_failed": bool}
    `core_failed` means a number the verdict rests on is wrong; a failure that
    only touches an extra id from the investigator's lists is not core.
    """
    claims = evaluation.get("cited_values") or {}
    verified, failures = [], []
    core_failed = False

    for rid in cited_row_ids(evaluation):
        row = lookup_row(dataset, rid)
        is_core = rid in claims
        if row is None:
            failures.append({"row_id": rid, "reason": "row not found in dataset", "core": is_core})
            core_failed = core_failed or is_core
            continue
        table = ROW_ID_RE.match(rid).group(1)
        row_ok = True
        for field, claimed in (claims.get(rid) or {}).items():
            try:
                actual = _field_value(table, row, field)
            except KeyError:
                failures.append({"row_id": rid, "field": field, "reason": "field not in row", "core": True})
                row_ok = False
                continue
            if actual is None or (isinstance(actual, float) and math.isnan(actual)):
                failures.append({"row_id": rid, "field": field, "claimed": claimed,
                                 "actual": None, "reason": "row has no value", "core": True})
                row_ok = False
            elif not _values_match(claimed, actual):
                failures.append({"row_id": rid, "field": field, "claimed": claimed,
                                 "actual": _text(actual), "reason": "value does not match row",
                                 "core": True})
                row_ok = False
        if row_ok:
            verified.append(rid)
        else:
            core_failed = True

    return {"ok": not failures, "verified": verified, "failures": failures,
            "core_failed": core_failed}


# ---------------------------------------------------------------------------
# 2. Consistency with the deterministic flag
# ---------------------------------------------------------------------------

def expected_verdict(h_id: str, evidence: dict) -> str:
    """The verdict the computed flags imply. Independent of the investigator's code."""
    ev = evidence or {}
    if not ev or ev.get("data_missing"):
        return "inconclusive"
    if h_id == "H1":
        return "supported" if ev.get("late") or ev.get("delivery_slipped") else "weakened"
    if h_id == "H2":
        return "supported" if ev.get("underfill") else "weakened"
    if h_id == "H3":
        return "supported" if ev.get("major_arrears") else "weakened"
    if h_id == "H4":
        pct = _num(ev.get("pct_change"))
        return "supported" if ev.get("surge") or (pct is not None and pct > 25) else "weakened"
    if h_id == "H5":
        if ev.get("identity_holds") is False or ev.get("stockout_days_plausible") is False:
            return "supported"
        return "weakened"
    if h_id == "H6":
        return "supported" if ev.get("high_wastage") else "weakened"
    if h_id == "H7":
        drop = _num(ev.get("county_fill_drop")) or 0.0
        if ev.get("web_notice_found") and drop > 0.1:
            return "supported"
        if ev.get("web_notice_found") or drop > 0.1:
            return "inconclusive"
        return "weakened"
    return "inconclusive"


def check_consistency(evaluation: dict, computed_evidence: dict) -> dict:
    """
    Reject a verdict that disagrees with the computed flag on whether the
    hypothesis is supported. (inconclusive vs weakened is tolerated.)
    """
    h_id = evaluation.get("theory_id", "")
    verdict = evaluation.get("verdict", "inconclusive")
    expected = expected_verdict(h_id, hypothesis_evidence(computed_evidence, h_id))
    ok = (verdict == "supported") == (expected == "supported")
    reason = "" if ok else (
        f"{h_id} verdict '{verdict}' disagrees with the computed flags, which give '{expected}'"
    )
    return {"ok": ok, "verdict": verdict, "expected": expected, "reason": reason}


# ---------------------------------------------------------------------------
# 3. Cross-critique between hypotheses
# ---------------------------------------------------------------------------

def cross_critique(evaluations: list, computed_evidence: dict, month: str = None) -> list:
    """
    Check each supported verdict against the evidence of the other hypotheses.
    Returns [{"target", "raised_by", "kind", "reason"}].
    """
    critiques = []
    by_id = {e.get("theory_id"): e for e in evaluations}
    h1 = hypothesis_evidence(computed_evidence, "H1")
    h3 = hypothesis_evidence(computed_evidence, "H3")
    h5 = hypothesis_evidence(computed_evidence, "H5")

    def supported(h_id):
        return (by_id.get(h_id) or {}).get("verdict") == "supported"

    # Demand surge read from a ledger that is broken or still shows stock on hand.
    if supported("H4"):
        if h5.get("identity_holds") is False:
            critiques.append({
                "target": "H4", "raised_by": "H5", "kind": "record_conflict",
                "reason": (f"Demand surge rests on {h5.get('stock_id', 'the stock row')}, but its stock "
                           f"identity does not hold (computed closing {h5.get('computed_closing')} vs "
                           f"reported {h5.get('reported_closing')}). Revise: is the consumption figure real?"),
            })
        elif h5.get("stockout_days_plausible") is False:
            critiques.append({
                "target": "H4", "raised_by": "H5", "kind": "stock_on_hand",
                "reason": (f"{h5.get('stock_id', 'The stock row')} reports a stock-out but closing stock "
                           f"is {h5.get('reported_closing')}. A surge cannot explain a stock-out with "
                           "stock on hand. Revise."),
            })

    # Late order whose delivery landed before the stock-out month.
    if supported("H1") and month:
        delivered = str(h1.get("delivery_month") or "")
        if delivered and delivered < month:
            critiques.append({
                "target": "H1", "raised_by": "H1", "kind": "delivered_before_stockout",
                "reason": (f"{h1.get('order_id', 'The order')} was delivered in {delivered}, before the "
                           f"stock-out month {month}. A late order cannot explain this gap. Revise."),
            })

    # Arrears while the county was still fully supplied is not a supply mechanism.
    # Both cycles count: the previous month's orders are the ones delivered in the
    # stock-out month, so a low fill there is a real county-wide shortfall.
    if supported("H3"):
        fills = [_num(h3.get(k)) for k in ("county_fill_prev_month", "county_fill_this_month")]
        fills = [f for f in fills if f is not None]
        if fills and min(fills) >= 0.85:
            critiques.append({
                "target": "H3", "raised_by": "H2", "kind": "no_delivery_drop",
                "reason": (f"County arrears are present, but county deliveries stayed full "
                           f"(fill {', '.join(f'{f:.2f}' for f in fills)}). "
                           "Revise: what reduced this facility's supply?"),
            })
    return critiques


# ---------------------------------------------------------------------------
# One review pass over a batch of evaluations
# ---------------------------------------------------------------------------

def review(evaluations: list, computed_evidence: dict, dataset: dict, month: str = None) -> dict:
    """
    Run citations, consistency and cross-critique over a batch.

    Returns {
      "reports":   {h_id: {"citations", "consistency", "critiques", "ok", "confidence"}},
      "critiques": [...],
      "failed":    [h_id, ...]   # need revision
    }
    """
    critiques = cross_critique(evaluations, computed_evidence, month)
    reports, failed = {}, []
    for ev in evaluations:
        h_id = ev.get("theory_id")
        cites = verify_citations(ev, dataset)
        cons = check_consistency(ev, computed_evidence)
        mine = [c for c in critiques if c["target"] == h_id]
        ok = cites["ok"] and cons["ok"] and not mine
        n_cited = len(cited_row_ids(ev))
        confidence = round(len(cites["verified"]) / n_cited, 2) if n_cited else (1.0 if cons["ok"] else 0.0)
        if not cons["ok"]:
            confidence = 0.0
        reports[h_id] = {"citations": cites, "consistency": cons, "critiques": mine,
                         "ok": ok, "confidence": confidence}
        if not ok:
            failed.append(h_id)
    return {"reports": reports, "critiques": critiques, "failed": failed}


def critique_text(report: dict) -> str:
    """One paragraph the investigator receives when asked to revise."""
    parts = []
    for f in report["citations"]["failures"]:
        if "field" in f:
            parts.append(f"{f['row_id']}.{f['field']}: you cited {f.get('claimed')!r}, "
                         f"the row says {f.get('actual')!r}")
        else:
            parts.append(f"{f['row_id']}: {f['reason']}")
    if not report["consistency"]["ok"]:
        parts.append(report["consistency"]["reason"])
    for c in report["critiques"]:
        parts.append(f"[{c['raised_by']}] {c['reason']}")
    return "Evaluator critique: " + "; ".join(parts) if parts else ""


def settle(evaluation: dict, report: dict) -> tuple:
    """
    Decide what happens to an evaluation after its one revision.

    Returns (evaluation_or_None, note). None means the claim is dropped.
      - a core number still wrong / row missing  -> drop
      - verdict still contradicts the flags       -> drop
      - only extra citation ids unknown           -> strip those ids, keep
      - cross-critique still stands               -> keep as "inconclusive" (contested)
    """
    if report["citations"]["core_failed"]:
        return None, "cited numbers still do not match the dataset"
    if not report["consistency"]["ok"]:
        return None, report["consistency"]["reason"]
    note = ""
    bad = {f["row_id"] for f in report["citations"]["failures"]}
    if bad:
        for key in ("supporting_evidence_ids", "contradicting_evidence_ids"):
            evaluation[key] = [r for r in evaluation.get(key) or [] if r not in bad]
        note = f"removed unverifiable citations: {', '.join(sorted(bad))}"
    if report["critiques"]:
        evaluation["verdict"] = "inconclusive"
        evaluation["contested_by"] = [c["raised_by"] for c in report["critiques"]]
        evaluation["contest_reason"] = " ".join(c["reason"] for c in report["critiques"])
        note = (note + "; " if note else "") + "contested by cross-critique, downgraded to inconclusive"
    return evaluation, note


# ---------------------------------------------------------------------------
# 4. Coverage
# ---------------------------------------------------------------------------

def check_coverage(final_evaluations: dict, held_back: list) -> dict:
    """
    Does the set of verified supported causes explain the stock-out?

    final_evaluations: {h_id: evaluation} (already verified)
    held_back        : hypotheses not yet investigated

    Returns {"verdict": "explained"|"needs_second_pass"|"insufficient_evidence",
             "supported": [...], "request": [...]}
    """
    supported = [h for h in HYPOTHESIS_ORDER
                 if (final_evaluations.get(h) or {}).get("verdict") == "supported"
                 and (final_evaluations.get(h) or {}).get("verified_citations")]
    # Root cause first (see agents/rules.py ROOT_CAUSE_ORDER)
    supported.sort(key=rules.root_cause_rank)
    if supported:
        return {"verdict": "explained", "supported": supported, "request": [],
                "reason": f"verified supported cause(s): {', '.join(supported)}"}
    if held_back:
        return {"verdict": "needs_second_pass", "supported": [], "request": list(held_back),
                "reason": "no verified cause yet; investigate the held-back hypotheses"}
    return {"verdict": "insufficient_evidence", "supported": [], "request": [],
            "reason": "no hypothesis is supported by verified rows; escalate to the pharmacist"}
