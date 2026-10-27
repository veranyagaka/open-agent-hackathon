"""
agents/rules.py

Deterministic reasoning shared by the agents' rule-based (offline) mode.

Everything here reads only computed_evidence from tools/data_loader.py.
Text quotes the computed numbers and the row ids they came from
(e.g. stock#1506, orders#3161); nothing is estimated or invented.
"""

HYPOTHESES = [
    ("H1", "late_order", "h1_late_order", "Late order"),
    ("H2", "supplier_underfill", "h2_supplier_underfill", "Supplier under-fill"),
    ("H3", "payment_arrears", "h3_payment_arrears", "County payment arrears"),
    ("H4", "demand_surge", "h4_demand_surge", "Demand surge"),
    ("H5", "record_error", "h5_record_error", "Stock record error"),
    ("H6", "expiry", "h6_expiry", "Expiry or wastage"),
    ("H7", "national_disruption", "h7_national_disruption", "National supply disruption"),
]

HYPOTHESIS_NAMES = {h_id: name for h_id, name, _, _ in HYPOTHESES}
EVIDENCE_KEYS = {h_id: key for h_id, _, key, _ in HYPOTHESES}
TITLES = {h_id: title for h_id, _, _, title in HYPOTHESES}
ID_ORDER = [h_id for h_id, _, _, _ in HYPOTHESES]

VERDICT_RANK = {"supported": 0, "inconclusive": 1, "weakened": 2}

# When several causes are supported, the deeper (root) cause leads. A national
# disruption or county payment arrears is why the supplier under-delivers; a
# broken stock record makes every other signal unreliable; expired stock is
# lost at the facility whatever was delivered. Supplier underfill on its own
# is the symptom most other causes produce, so it comes last.
ROOT_CAUSE_ORDER = ["H7", "H3", "H5", "H6", "H1", "H4", "H2"]

ARREARS_THRESHOLD_KES = 30_000_000


def _num(value, digits: int = 4):
    """Format a computed number without adding precision it does not have."""
    if value is None:
        return "n/a"
    if isinstance(value, float):
        value = round(value, digits)
        if value == int(value):
            return str(int(value))
    return str(value)


def evidence_for(computed_evidence: dict, h_id: str) -> dict:
    return (computed_evidence or {}).get(EVIDENCE_KEYS.get(h_id, ""), {}) or {}


def deterministic_verdict(hypothesis_id: str, hypothesis_evidence: dict) -> str:
    """
    Assign a verdict deterministically based on computed flags.

    Returns "supported", "weakened", or "inconclusive".
    """
    ev = hypothesis_evidence or {}
    if ev.get("data_missing"):
        return "inconclusive"

    if hypothesis_id == "H1":
        if ev.get("late") or ev.get("delivery_slipped"):
            return "supported"
        return "weakened"

    if hypothesis_id == "H2":
        return "supported" if ev.get("underfill") else "weakened"

    if hypothesis_id == "H3":
        return "supported" if ev.get("major_arrears") else "weakened"

    if hypothesis_id == "H4":
        pct = ev.get("pct_change")
        if ev.get("surge") or (pct is not None and pct > 25):
            return "supported"
        return "weakened"

    if hypothesis_id == "H5":
        # identity_holds=False means the ledger contradicts itself (supported)
        if ev.get("identity_holds") is False:
            return "supported"
        if ev.get("stockout_days_plausible") is False:
            return "supported"
        return "weakened"

    if hypothesis_id == "H6":
        return "supported" if ev.get("high_wastage") else "weakened"

    if hypothesis_id == "H7":
        fill_drop = ev.get("county_fill_drop") or 0
        if ev.get("web_notice_found") and fill_drop > 0.1:
            return "supported"
        if ev.get("web_notice_found") or fill_drop > 0.1:
            return "inconclusive"
        return "weakened"

    return "inconclusive"


def evidence_strength(hypothesis_id: str, hypothesis_evidence: dict) -> float:
    """
    0-1 score of how far the computed signal sits past its threshold.
    Used only to order hypotheses that share the same verdict.
    """
    ev = hypothesis_evidence or {}
    if ev.get("data_missing"):
        return 0.0

    def clamp(x):
        return round(max(0.0, min(1.0, float(x))), 3)

    if hypothesis_id == "H1":
        if not (ev.get("late") or ev.get("delivery_slipped")):
            return 0.0
        days = ev.get("days_late") or 0
        return clamp(0.6 + min(max(days, 0), 30) / 100 + (0.1 if ev.get("delivery_slipped") else 0))

    if hypothesis_id == "H2":
        shortfall = ev.get("relative_shortfall") or 0
        return clamp(shortfall / 0.3) if shortfall > 0 else 0.0

    if hypothesis_id == "H3":
        owed = ev.get("amount_owed_kes") or 0
        base = owed / (2 * ARREARS_THRESHOLD_KES)
        drop = ev.get("fill_drop_vs_prev") or 0
        return clamp(base + (0.2 if drop > 0 else 0))

    if hypothesis_id == "H4":
        pct = ev.get("pct_change") or 0
        return clamp(pct / 100) if pct > 0 else 0.0

    if hypothesis_id == "H5":
        if ev.get("identity_holds") is False:
            return 0.9
        if ev.get("stockout_days_plausible") is False:
            return 0.6
        return 0.0

    if hypothesis_id == "H6":
        wastage = ev.get("wastage_this_month") or 0
        avg_c = ev.get("avg_consumed_3m") or 0
        if not ev.get("high_wastage"):
            return 0.0
        return clamp(wastage / avg_c) if avg_c else 0.5

    if hypothesis_id == "H7":
        drop = ev.get("county_fill_drop") or 0
        return clamp((0.5 if ev.get("web_notice_found") else 0) + max(drop, 0) * 2)

    return 0.0


def evidence_ids(hypothesis_evidence: dict) -> list:
    """Row ids present in one hypothesis' computed evidence."""
    ev = hypothesis_evidence or {}
    ids = []
    for key in ("order_id", "stock_id"):
        value = ev.get(key)
        if value and value not in ids:
            ids.append(str(value))
    return ids


def describe(hypothesis_id: str, hypothesis_evidence: dict) -> str:
    """One factual sentence built only from computed values and row ids."""
    ev = hypothesis_evidence or {}

    if hypothesis_id == "H1":
        if ev.get("data_missing"):
            return (
                "No order from the previous month was found for this facility and "
                "commodity, so the late-order check could not run."
            )
        days = ev.get("days_late")
        timing = (
            "timing unknown" if days is None
            else f"{days} days after the cutoff" if days > 0
            else f"{abs(days)} days before the cutoff" if days < 0
            else "on the cutoff day"
        )
        return (
            f"{ev.get('order_id', 'The order')} was placed {ev.get('order_date')} against "
            f"cutoff {ev.get('cutoff_date')} ({timing}); delivery month "
            f"{ev.get('delivery_month')} vs expected {ev.get('expected_delivery_month')}."
        )

    if hypothesis_id == "H2":
        if ev.get("data_missing"):
            return "No order record for the delivery cycle, so fill rate could not be computed."
        return (
            f"{ev.get('order_id', 'The order')} fill rate {_num(ev.get('facility_fill_rate'))} "
            f"vs county average {_num(ev.get('county_avg_fill_rate'))} across "
            f"{ev.get('n_facilities_in_cycle', 'n/a')} orders in the cycle "
            f"(shortfall {_num(ev.get('relative_shortfall'))}; under-fill threshold 0.05)."
        )

    if hypothesis_id == "H3":
        owed = ev.get("amount_owed_kes")
        owed_text = f"{owed:,.0f} KES" if isinstance(owed, (int, float)) else "n/a"
        return (
            f"County payment records: arrears flag "
            f"{'set' if ev.get('arrears_in_month') else 'not set'} in the 4-month window, "
            f"amount owed {owed_text} (threshold {ARREARS_THRESHOLD_KES:,} KES); "
            f"county fill-rate drop vs previous month {_num(ev.get('fill_drop_vs_prev'))}."
        )

    if hypothesis_id == "H4":
        if ev.get("data_missing"):
            return "No stock record for the month, so consumption could not be compared."
        pct = ev.get("pct_change")
        pct_text = "n/a" if pct is None else f"{pct:+}%"
        if ev.get("demand_basis") == "stockout_adjusted":
            issues = ev.get("pct_change_issues_only")
            issues_text = "n/a" if issues is None else f"{issues:+}%"
            days = _num(ev.get("reported_stockout_days"))
            return (
                f"{ev.get('stock_id', 'Stock record')}: consumed {_num(ev.get('consumed_this_month'))} "
                f"with {days} reported stock-out days; stock-out-adjusted demand "
                f"{_num(ev.get('consumed_this_month'))} x 30 / (30 - {days}) = "
                f"{_num(ev.get('adjusted_demand'))} vs 3-month average "
                f"{_num(ev.get('avg_consumed_3m'))} ({pct_text}; issues only {issues_text}; "
                f"surge threshold +25%)."
            )
        return (
            f"{ev.get('stock_id', 'Stock record')}: consumed {_num(ev.get('consumed_this_month'))} "
            f"vs 3-month average {_num(ev.get('avg_consumed_3m'))} ({pct_text}; surge threshold +25%)."
        )

    if hypothesis_id == "H5":
        if ev.get("data_missing"):
            return "No stock record for the month, so the stock identity could not be checked."
        holds = ev.get("identity_holds")
        return (
            f"{ev.get('stock_id', 'Stock record')}: computed closing {_num(ev.get('computed_closing'))} "
            f"vs reported {_num(ev.get('reported_closing'))} (discrepancy {_num(ev.get('discrepancy'))}, "
            f"identity {'holds' if holds else 'broken'}); reported stockout days "
            f"{_num(ev.get('reported_stockout_days'))} "
            f"{'plausible' if ev.get('stockout_days_plausible') else 'implausible'}."
        )

    if hypothesis_id == "H6":
        if ev.get("data_missing"):
            return "No stock record for the month, so wastage could not be compared."
        return (
            f"{ev.get('stock_id', 'Stock record')}: wastage {_num(ev.get('wastage_this_month'))} "
            f"vs 3-month average {_num(ev.get('avg_wastage_3m'))}, with average consumption "
            f"{_num(ev.get('avg_consumed_3m'))} (high-wastage rule: >2x average and >10% of consumption)."
        )

    if hypothesis_id == "H7":
        notice = ev.get("notice_details") or {}
        notice_text = (
            f"public notice found ({notice.get('source', 'source n/a')}, {notice.get('month', '')}: "
            f"\"{notice.get('title', '')}\")"
            if ev.get("web_notice_found") else "no public notice for this commodity in the window"
        )
        return (
            f"{notice_text}; county fill-rate drop vs previous month "
            f"{_num(ev.get('county_fill_drop'))}."
        )

    return "No computed evidence for this hypothesis."


def signal(hypothesis_id: str, hypothesis_evidence: dict) -> str:
    """strong | weak | none, from verdict and strength."""
    verdict = deterministic_verdict(hypothesis_id, hypothesis_evidence)
    if verdict == "supported":
        return "strong" if evidence_strength(hypothesis_id, hypothesis_evidence) >= 0.5 else "weak"
    if verdict == "inconclusive":
        return "weak"
    return "none"


def root_cause_rank(h_id: str) -> int:
    return ROOT_CAUSE_ORDER.index(h_id) if h_id in ROOT_CAUSE_ORDER else 99


def rank_key(verdict: str, strength, h_id: str) -> tuple:
    """Supported causes by root-cause order; the rest by strength, then H-order."""
    order = ID_ORDER.index(h_id) if h_id in ID_ORDER else 99
    if verdict == "supported":
        return (0, root_cause_rank(h_id), -(strength or 0.0), order)
    return (VERDICT_RANK.get(verdict, 3), 0, -(strength or 0.0), order)


def rank_hypotheses(computed_evidence: dict) -> list:
    """
    All seven hypotheses ordered most-likely first:
    supported causes in root-cause order, then the rest by strength and H-order.
    """
    rows = []
    for h_id in ID_ORDER:
        ev = evidence_for(computed_evidence, h_id)
        verdict = deterministic_verdict(h_id, ev)
        strength = evidence_strength(h_id, ev)
        rows.append({
            "hypothesis_id": h_id,
            "hypothesis_name": HYPOTHESIS_NAMES[h_id],
            "verdict": verdict,
            "evidence_strength": strength,
            "evidence_ids": evidence_ids(ev),
            "summary": describe(h_id, ev),
        })
    rows.sort(key=lambda r: rank_key(r["verdict"], r["evidence_strength"], r["hypothesis_id"]))
    return rows


# ---------------------------------------------------------------------------
# H4: demand basis
# ---------------------------------------------------------------------------

def h4_issues_only(hypothesis_evidence: dict) -> dict:
    """
    H4 evidence recomputed from issues (consumed) only, without the
    stock-out adjustment. Used when the Evaluator's record check shows the
    facility had stock on hand, so the reported stock-out days cannot have
    suppressed demand.
    """
    ev = dict(hypothesis_evidence or {})
    if ev.get("demand_basis") != "stockout_adjusted":
        return ev
    pct = ev.get("pct_change_issues_only")
    ev["pct_change"] = pct
    ev["surge"] = bool(pct is not None and pct > 25)
    ev["demand_basis"] = "issues_only"
    ev.pop("adjusted_demand", None)
    return ev


# ---------------------------------------------------------------------------
# Transfer candidates (deterministic, from the dataset)
# ---------------------------------------------------------------------------

def _prev_months(month: str, n: int) -> list:
    """The n calendar months strictly before *month* (YYYY-MM), newest first."""
    y, mo = int(month[:4]), int(month[5:7])
    out = []
    for _ in range(n):
        mo -= 1
        if mo == 0:
            mo, y = 12, y - 1
        out.append(f"{y:04d}-{mo:02d}")
    return out


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    import math
    r = 6371.0088
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp = p2 - p1
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _finite(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def facility_name(dataset: dict, facility_id: str):
    """facilities.csv `facility_name` for an id, or None when the column or row is missing."""
    df = (dataset or {}).get("facilities")
    if df is None or not hasattr(df, "columns") or "facility_name" not in df.columns:
        return None
    hit = df[df["facility_id"].astype(str).str.strip() == str(facility_id)]
    if hit.empty:
        return None
    name = hit.iloc[0]["facility_name"]
    return str(name).strip() if isinstance(name, str) and name.strip() else None


def facility_label(facility_id: str, name: str = None) -> str:
    """'Katutu Dispensary (FAC-009)' when a name is known, else the id."""
    return f"{name} ({facility_id})" if name else str(facility_id)


def transfer_candidates(dataset: dict, facility: str, commodity: str, month: str,
                        k: float = 1.0) -> list:
    """
    Facilities that could lend stock, nearest first.

    surplus = closing stock in *month* - k x the facility's average `consumed`
    over the 3 previous months. Only surplus > 0 counts; units = floor(surplus).
    Every number cites the rows it came from: the source's stock row, its three
    history rows and both facilities# rows. Facilities with missing coordinates
    or fewer than 3 history months are skipped.
    """
    import math
    stock = (dataset or {}).get("stock")
    facilities = (dataset or {}).get("facilities")
    if stock is None or facilities is None or not hasattr(stock, "columns") \
            or not hasattr(facilities, "columns") or not month:
        return []
    coords = {}
    for _, row in facilities.iterrows():
        lat, lon = _finite(row.get("lat")), _finite(row.get("lon"))
        if lat is not None and lon is not None:
            coords[str(row.get("facility_id")).strip()] = (lat, lon)
    if facility not in coords:
        return []
    window = _prev_months(month, 3)
    rows = stock[stock["commodity"] == commodity]
    out = []
    for source, group in rows.groupby("facility_id"):
        source = str(source).strip()
        if source == facility or source not in coords:
            continue
        current = group[group["month"] == month]
        history = group[group["month"].isin(window)].sort_values("month")
        if current.empty or len(history) < 3:
            continue
        closing = _finite(current.iloc[0].get("closing"))
        used = [_finite(v) for v in history["consumed"]]
        if closing is None or any(v is None for v in used):
            continue
        avg = sum(used) / len(used)
        surplus = closing - k * avg
        if surplus <= 0:
            continue
        distance = haversine_km(*coords[facility], *coords[source])
        out.append({
            "source_facility": source,
            "source_facility_name": facility_name(dataset, source),
            "units": int(math.floor(surplus)),
            "distance_km": round(distance, 1),
            "source_closing": closing,
            "source_avg_consumed_3m": round(avg, 2),
            "k": k,
            "stock_row": f"stock#{current.iloc[0]['id']}",
            "history_rows": [f"stock#{i}" for i in history["id"]],
            "citations": ([f"stock#{current.iloc[0]['id']}"]
                          + [f"stock#{i}" for i in history["id"]]
                          + [f"facilities#{facility}", f"facilities#{source}"]),
        })
    out.sort(key=lambda c: (c["distance_km"], c["source_facility"]))
    return out


def transfer_rule_text(k: float = 1.0) -> str:
    months = "1 month" if k == 1 else f"{_num(k)} months"
    return f"surplus beyond {months} of the source's 3-month average use"
