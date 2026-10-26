"""
tools/data_loader.py

Deterministic data loading and hypothesis-evidence calculations.
NO LLM calls here — pure pandas/numpy arithmetic only.
"""

import json
import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------

def _load_csv_dataset(dataset_dir: str) -> dict:
    """
    Load all CSV/JSON files from a dataset directory.

    Returns a dict with keys:
        stock, orders, payments, facilities, web_notes
    Values are pandas DataFrames (or a list of dicts for web_notes).
    """
    d = Path(dataset_dir)
    if not d.exists():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")

    def read_csv(name: str) -> pd.DataFrame:
        path = d / name
        if not path.exists():
            raise FileNotFoundError(f"Expected file not found: {path}")
        return pd.read_csv(path, dtype=str)  # load as str, coerce below

    stock = read_csv("stock.csv")
    orders = read_csv("orders.csv")
    payments = read_csv("payments.csv")
    facilities = read_csv("facilities.csv")

    # Numeric coercions for stock
    for col in ("opening", "received", "wastage", "consumed",
                "closing", "reported_stockout_days"):
        stock[col] = pd.to_numeric(stock[col], errors="coerce")

    # Numeric coercions for orders
    for col in ("qty_requested", "qty_delivered"):
        orders[col] = pd.to_numeric(orders[col], errors="coerce")

    # Date coercions for orders
    orders["order_date"] = pd.to_datetime(orders["order_date"], errors="coerce")
    orders["cutoff_date"] = pd.to_datetime(orders["cutoff_date"], errors="coerce")

    # Numeric coercions for payments
    payments["county_arrears_flag"] = pd.to_numeric(
        payments["county_arrears_flag"], errors="coerce"
    )
    payments["amount_owed_kes"] = pd.to_numeric(
        payments["amount_owed_kes"], errors="coerce"
    )

    # Lat/lon for facilities
    facilities["lat"] = pd.to_numeric(facilities["lat"], errors="coerce")
    facilities["lon"] = pd.to_numeric(facilities["lon"], errors="coerce")

    # web_notes
    web_notes_path = d / "web_notes.json"
    if web_notes_path.exists():
        with open(web_notes_path, "r") as f:
            web_notes = json.load(f)
    else:
        web_notes = []

    return {
        "stock": stock,
        "orders": orders,
        "payments": payments,
        "facilities": facilities,
        "web_notes": web_notes,
    }


def _coerce_dataset(dataset: dict) -> dict:
    """Apply the same type coercions to CSV and Zetaris table results."""
    stock = dataset["stock"]
    orders = dataset["orders"]
    payments = dataset["payments"]
    facilities = dataset["facilities"]

    for col in ("opening", "received", "wastage", "consumed",
                "closing", "reported_stockout_days"):
        if col in stock.columns:
            stock[col] = pd.to_numeric(stock[col], errors="coerce")

    for col in ("qty_requested", "qty_delivered"):
        if col in orders.columns:
            orders[col] = pd.to_numeric(orders[col], errors="coerce")

    for col in ("order_date", "cutoff_date"):
        if col in orders.columns:
            orders[col] = pd.to_datetime(orders[col], errors="coerce")

    for col in ("county_arrears_flag", "amount_owed_kes"):
        if col in payments.columns:
            payments[col] = pd.to_numeric(payments[col], errors="coerce")

    for col in ("lat", "lon"):
        if col in facilities.columns:
            facilities[col] = pd.to_numeric(facilities[col], errors="coerce")
    return dataset


def _zetaris_rows(response: dict) -> list:
    """Normalize common Zetaris SQL-editor row response shapes."""
    if not isinstance(response, dict):
        raise RuntimeError("Unexpected Zetaris response: expected a JSON object")
    data = response.get("data")
    if isinstance(data, list):
        if not data:
            return []
        if all(isinstance(row, dict) for row in data):
            return data
        # Zetaris SQL-editor commonly returns positional rows in ``data``
        # and the matching column names in ``headers``. Other deployments or
        # endpoints may use ``columns`` / ``columnNames`` instead.
        columns = (
            response.get("headers")
            or response.get("columns")
            or response.get("columnNames")
            or response.get("column_names")
        )
        if isinstance(columns, list) and all(isinstance(row, (list, tuple)) for row in data):
            names = []
            for column in columns:
                if isinstance(column, dict):
                    name = column.get("name") or column.get("label") or column.get("columnName")
                    if name is None:
                        raise RuntimeError(
                            f"Zetaris returned column metadata without a name: {column!r}"
                        )
                    names.append(str(name))
                else:
                    names.append(str(column))
            if data and any(len(row) != len(names) for row in data):
                raise RuntimeError(
                    "Zetaris row width does not match returned column metadata: "
                    f"{len(names)} columns, row widths {[len(row) for row in data[:3]]}"
                )
            return [dict(zip(names, row)) for row in data]
    for key in ("rows", "results"):
        rows = response.get(key)
        if isinstance(rows, list):
            if not rows or all(isinstance(row, dict) for row in rows):
                return rows
    if data is None:
        raise RuntimeError(
            "Zetaris SQL response did not contain a 'data' row list; "
            f"response keys: {list(response.keys())}"
        )
    raise RuntimeError(
        "Unsupported Zetaris row format; expected a list of row objects "
        "or rows with column metadata."
    )


def load_zetaris_dataset(dataset_dir: str) -> dict:
    """Load all StockWhy tables from Zetaris, preserving the CSV schema."""
    # Reuse the proven authentication, endpoint, and request headers.
    from scripts.check_zetaris import run_sql

    def query_all(table: str) -> pd.DataFrame:
        rows = []
        offset = 0
        page_size = 100  # check_zetaris.run_sql applies a server-side limit of 100
        while True:
            response = run_sql(
                f"SELECT * FROM STOCKWHY_PG.{table} LIMIT {page_size} OFFSET {offset}"
            )
            page = _zetaris_rows(response)
            rows.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
            if offset > 1_000_000:
                raise RuntimeError(f"Aborting Zetaris pagination for {table}: safety limit exceeded")
        return pd.DataFrame(rows)

    d = Path(dataset_dir)
    web_notes_path = d / "web_notes.json"
    if not web_notes_path.exists():
        raise FileNotFoundError(
            f"web_notes.json is required for the Zetaris source so existing evidence is preserved: {web_notes_path}"
        )
    with web_notes_path.open("r", encoding="utf-8") as f:
        web_notes = json.load(f)

    dataset = {
        "stock": query_all("stock"),
        "orders": query_all("orders"),
        "payments": query_all("payments"),
        "facilities": query_all("facilities"),
        "web_notes": web_notes,
    }
    expected = {
        "stock": {"id", "facility_id", "commodity", "month", "opening", "received", "wastage", "consumed", "closing", "reported_stockout_days"},
        "orders": {"id", "facility_id", "commodity", "month", "cutoff_date", "order_date", "qty_requested", "qty_delivered", "delivery_month"},
        "payments": {"id", "month", "county_arrears_flag", "amount_owed_kes"},
        "facilities": {"facility_id", "lat", "lon"},
    }
    for table, required in expected.items():
        missing = required - set(dataset[table].columns)
        if missing:
            raise RuntimeError(
                f"Zetaris table {table!r} is missing required columns: {sorted(missing)}"
            )
        if dataset[table].empty:
            raise RuntimeError(f"Zetaris returned no rows for required table {table!r}")
    return _coerce_dataset(dataset)


def load_dataset(dataset_dir: str) -> dict:
    """Load data from CSV by default, or Zetaris when configured."""
    source = os.getenv("STOCKWHY_DATA_SOURCE", "csv").strip().lower()
    if source == "zetaris":
        return load_zetaris_dataset(dataset_dir)
    if source != "csv":
        raise ValueError(
            "STOCKWHY_DATA_SOURCE must be either 'csv' or 'zetaris', "
            f"not {source!r}"
        )
    return _load_csv_dataset(dataset_dir)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val, default: float = 0.0) -> float:
    """Convert a value to float, returning default if impossible."""
    try:
        v = float(val)
        return v if np.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _month_sort_key(m: str) -> str:
    """YYYY-MM string is already lexicographically sortable."""
    return m


def _prev_months(month: str, n: int) -> list:
    """Return the n calendar months strictly before *month* as YYYY-MM strings."""
    y, mo = int(month[:4]), int(month[5:7])
    months = []
    for _ in range(n):
        mo -= 1
        if mo == 0:
            mo = 12
            y -= 1
        months.append(f"{y:04d}-{mo:02d}")
    return months


# ---------------------------------------------------------------------------
# Main profiling function
# ---------------------------------------------------------------------------

def profile_stockout(
    dataset: dict,
    facility_id: str,
    commodity: str,
    month: str,
) -> dict:
    """
    Build a complete evidence profile for one stockout investigation.

    Parameters
    ----------
    dataset    : output of load_dataset()
    facility_id: e.g. "FAC-011"
    commodity  : e.g. "ORS sachet"
    month      : e.g. "2026-03"

    Returns a dict with raw records + computed_evidence for all 7 hypotheses.
    """
    stock_df = dataset["stock"]
    orders_df = dataset["orders"]
    payments_df = dataset["payments"]
    facilities_df = dataset["facilities"]
    web_notes = dataset["web_notes"]

    # -----------------------------------------------------------------------
    # 1. Pull the target stock record
    # -----------------------------------------------------------------------
    mask_s = (
        (stock_df["facility_id"] == facility_id)
        & (stock_df["commodity"] == commodity)
        & (stock_df["month"] == month)
    )
    stock_record = stock_df[mask_s].copy()

    # -----------------------------------------------------------------------
    # 2. Pull order records relevant to the stockout month.
    #
    #    Two orders matter:
    #    (a) The order placed in month-1 (previous month) — this order is
    #        normally delivered IN `month`.  If it was late it slips to
    #        month+1, leaving `month` with no delivery → stockout.
    #    (b) The order placed in `month` itself — useful for fill-rate and
    #        future-cycle context, but late-order logic focuses on (a).
    # -----------------------------------------------------------------------
    prev_month = _prev_months(month, 1)[0]

    # (a) Previous month's order — the one that should have delivered in `month`
    mask_prev_o = (
        (orders_df["facility_id"] == facility_id)
        & (orders_df["commodity"] == commodity)
        & (orders_df["month"] == prev_month)
    )
    prev_order_record = orders_df[mask_prev_o].copy()

    # (b) This month's order (for fill-rate comparison)
    mask_o = (
        (orders_df["facility_id"] == facility_id)
        & (orders_df["commodity"] == commodity)
        & (orders_df["month"] == month)
    )
    order_record = orders_df[mask_o].copy()

    # All orders for this commodity in the same ordering cycle
    # (use the month whose delivery falls in `month`, i.e. prev_month)
    mask_all_o = (
        (orders_df["commodity"] == commodity)
        & (orders_df["month"] == prev_month)
    )
    all_orders = orders_df[mask_all_o].copy()
    # Fall back to current month if no previous-month orders found
    if all_orders.empty:
        mask_all_o = (
            (orders_df["commodity"] == commodity)
            & (orders_df["month"] == month)
        )
        all_orders = orders_df[mask_all_o].copy()

    # -----------------------------------------------------------------------
    # 3. Payment history
    # -----------------------------------------------------------------------
    payments_history = payments_df.copy()

    # -----------------------------------------------------------------------
    # 4. Stock history: last 6 months for this facility/commodity
    # -----------------------------------------------------------------------
    prev_6 = _prev_months(month, 6)
    mask_hist = (
        (stock_df["facility_id"] == facility_id)
        & (stock_df["commodity"] == commodity)
        & (stock_df["month"].isin(prev_6))
    )
    stock_history = stock_df[mask_hist].copy()

    # -----------------------------------------------------------------------
    # 5. Web notes for this commodity (any month)
    # -----------------------------------------------------------------------
    commodity_notes = [
        n for n in web_notes
        if n.get("commodity", "").lower() == commodity.lower()
    ]

    # -----------------------------------------------------------------------
    # Compute all 7 hypothesis checks deterministically
    # -----------------------------------------------------------------------
    computed_evidence = {}

    # --- H1: Late order ---
    # The order that should have delivered IN `month` is the one placed in
    # `prev_month`.  Check if that order was late.
    computed_evidence["h1_late_order"] = _check_h1(prev_order_record, expected_delivery_month=month)

    # --- H2: Supplier underfill (facility vs county) ---
    # Use the previous month's order cycle — that's what delivered (or didn't) in `month`
    computed_evidence["h2_supplier_underfill"] = _check_h2(
        facility_id, prev_order_record, all_orders
    )

    # --- H3: Payment arrears ---
    computed_evidence["h3_payment_arrears"] = _check_h3(
        month, payments_df, orders_df, commodity
    )

    # --- H4: Demand surge ---
    computed_evidence["h4_demand_surge"] = _check_h4(
        stock_record, stock_history
    )

    # --- H5: Record error ---
    computed_evidence["h5_record_error"] = _check_h5(stock_record)

    # --- H6: Expiry / wastage ---
    computed_evidence["h6_expiry"] = _check_h6(stock_record, stock_history)

    # --- H7: National disruption ---
    computed_evidence["h7_national_disruption"] = _check_h7(
        month, commodity, orders_df, web_notes
    )

    return {
        "facility_id": facility_id,
        "commodity": commodity,
        "month": month,
        "stock_record": stock_record.to_dict(orient="records"),
        "order_record": order_record.to_dict(orient="records"),
        "prev_order_record": prev_order_record.to_dict(orient="records"),
        "all_orders": all_orders.to_dict(orient="records"),
        "payments_history": payments_history.to_dict(orient="records"),
        "stock_history": stock_history.sort_values("month").to_dict(orient="records"),
        "facilities": facilities_df.to_dict(orient="records"),
        "web_notes": commodity_notes,
        "computed_evidence": computed_evidence,
    }


# ---------------------------------------------------------------------------
# Hypothesis checkers
# ---------------------------------------------------------------------------

def _check_h1(order_record: pd.DataFrame, expected_delivery_month: str = None) -> dict:
    """
    H1 Late order: was the order placed after the cutoff date?

    The order that matters is the one placed in the PREVIOUS month, which should
    normally deliver IN the stockout month.  If that order was late (order_date >
    cutoff_date) its delivery slips to the following month, leaving a gap.

    Parameters
    ----------
    order_record              : the previous month's order for this facility/commodity
    expected_delivery_month   : the stockout month (i.e. what the delivery month
                                should be if the order was on time)
    """
    if order_record.empty:
        return {
            "order_date": None,
            "cutoff_date": None,
            "days_late": None,
            "late": False,
            "delivery_month": None,
            "expected_delivery_month": expected_delivery_month,
            "delivery_slipped": False,
            "data_missing": True,
        }

    row = order_record.iloc[0]
    order_date = row["order_date"]
    cutoff_date = row["cutoff_date"]

    if pd.isna(order_date) or pd.isna(cutoff_date):
        days_late = None
        late = False
    else:
        delta = (order_date - cutoff_date).days
        days_late = int(delta)
        late = delta > 0

    # Also check if the actual delivery_month differs from expected
    delivery_month = str(row.get("delivery_month", "")) or None
    delivery_slipped = (
        late and
        delivery_month is not None and
        expected_delivery_month is not None and
        delivery_month != expected_delivery_month
    )

    # If not flagged as late by date but delivery still slipped, flag it
    if (not late and delivery_month and expected_delivery_month and
            delivery_month != expected_delivery_month):
        delivery_slipped = True
        # If the delivery month is later than expected, effectively late
        late = delivery_month > expected_delivery_month

    return {
        "order_date": str(order_date.date()) if not pd.isna(order_date) else None,
        "cutoff_date": str(cutoff_date.date()) if not pd.isna(cutoff_date) else None,
        "days_late": days_late,
        "late": bool(late),
        "delivery_month": delivery_month,
        "expected_delivery_month": expected_delivery_month,
        "delivery_slipped": bool(delivery_slipped),
        "order_id": f"orders#{row['id']}",
        "order_month": str(row.get("month", "")),
    }


def _check_h2(
    facility_id: str,
    order_record: pd.DataFrame,
    all_orders: pd.DataFrame,
) -> dict:
    """
    H2 Supplier underfill: this facility's fill rate vs county average.
    fill_rate = qty_delivered / qty_requested  (clamped to [0,1]).
    """
    if order_record.empty:
        return {
            "facility_fill_rate": None,
            "county_avg_fill_rate": None,
            "relative_shortfall": None,
            "underfill": False,
            "data_missing": True,
        }

    row = order_record.iloc[0]
    requested = _safe_float(row["qty_requested"])
    delivered = _safe_float(row["qty_delivered"])

    if requested > 0:
        fac_fill = min(delivered / requested, 1.0)
    else:
        fac_fill = None

    # County average across all facilities in same cycle (excluding zeroes)
    valid = all_orders[all_orders["qty_requested"] > 0].copy()
    if not valid.empty:
        valid = valid.copy()
        valid["fill_rate"] = (
            pd.to_numeric(valid["qty_delivered"], errors="coerce")
            / pd.to_numeric(valid["qty_requested"], errors="coerce")
        ).clip(0, 1)
        county_avg = float(valid["fill_rate"].mean())
    else:
        county_avg = None

    if fac_fill is not None and county_avg is not None:
        relative_shortfall = round(county_avg - fac_fill, 4)
        underfill = relative_shortfall > 0.05  # >5 pp below county average
    else:
        relative_shortfall = None
        underfill = False

    return {
        "facility_fill_rate": round(fac_fill, 4) if fac_fill is not None else None,
        "county_avg_fill_rate": round(county_avg, 4) if county_avg is not None else None,
        "relative_shortfall": relative_shortfall,
        "underfill": bool(underfill),
        "n_facilities_in_cycle": len(all_orders),
        "order_id": f"orders#{row['id']}",
    }


def _check_h3(
    month: str,
    payments_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    commodity: str,
) -> dict:
    """
    H3 Payment arrears: county owed >=30M KES in or just before *month*,
    AND county-wide fill rate dropped compared to the prior month.
    """
    # Find arrears record at/before this month
    prev_months = _prev_months(month, 3)  # look back 3 months
    relevant_months = [month] + prev_months

    pay_mask = payments_df["month"].isin(relevant_months)
    relevant_pay = payments_df[pay_mask].copy()

    arrears_in_month = False
    amount_owed_kes = 0.0
    if not relevant_pay.empty:
        # Take the most recent record with a flag
        flagged = relevant_pay[
            pd.to_numeric(relevant_pay["county_arrears_flag"], errors="coerce") == 1
        ]
        if not flagged.empty:
            arrears_in_month = True
            amount_owed_kes = float(
                flagged["amount_owed_kes"].apply(
                    lambda x: pd.to_numeric(x, errors="coerce")
                ).max()
            )

    major_arrears = arrears_in_month and amount_owed_kes >= 30_000_000

    # County-wide fill rate this month vs previous month for this commodity
    def county_fill(m: str) -> Optional[float]:
        mask = (orders_df["commodity"] == commodity) & (orders_df["month"] == m)
        sub = orders_df[mask].copy()
        sub = sub[sub["qty_requested"].apply(
            lambda x: pd.to_numeric(x, errors="coerce") > 0
        )]
        if sub.empty:
            return None
        rates = (
            pd.to_numeric(sub["qty_delivered"], errors="coerce")
            / pd.to_numeric(sub["qty_requested"], errors="coerce")
        ).clip(0, 1)
        return float(rates.mean())

    prev_1 = _prev_months(month, 1)[0]
    fill_this = county_fill(month)
    fill_prev = county_fill(prev_1)

    if fill_this is not None and fill_prev is not None and fill_prev > 0:
        fill_drop = round(fill_prev - fill_this, 4)
    else:
        fill_drop = None

    return {
        "arrears_in_month": bool(arrears_in_month),
        "amount_owed_kes": amount_owed_kes,
        "major_arrears": bool(major_arrears),
        "fill_drop_vs_prev": fill_drop,
        "county_fill_this_month": fill_this,
        "county_fill_prev_month": fill_prev,
    }


def _check_h4(
    stock_record: pd.DataFrame,
    stock_history: pd.DataFrame,
) -> dict:
    """
    H4 Demand surge: consumed this month vs 3-month rolling average.
    """
    if stock_record.empty:
        return {
            "consumed_this_month": None,
            "avg_consumed_3m": None,
            "pct_change": None,
            "surge": False,
            "data_missing": True,
        }

    consumed_this = _safe_float(stock_record.iloc[0]["consumed"])

    # Last 3 months from history
    hist_sorted = stock_history.sort_values("month", ascending=False)
    last_3 = hist_sorted.head(3)

    if last_3.empty:
        avg_3m = None
        pct_change = None
        surge = False
    else:
        avg_3m = float(
            last_3["consumed"].apply(
                lambda x: pd.to_numeric(x, errors="coerce")
            ).mean()
        )
        if avg_3m and avg_3m > 0:
            pct_change = round((consumed_this - avg_3m) / avg_3m * 100, 2)
            surge = pct_change > 25  # >25% above 3-month average
        else:
            pct_change = None
            surge = False

    return {
        "consumed_this_month": consumed_this,
        "avg_consumed_3m": round(avg_3m, 2) if avg_3m is not None else None,
        "pct_change": pct_change,
        "surge": bool(surge),
        "stock_id": f"stock#{stock_record.iloc[0]['id']}",
    }


def _check_h5(stock_record: pd.DataFrame) -> dict:
    """
    H5 Record error: does the stock identity equation hold?
      opening - wastage + received - consumed == closing

    Also: are stockout_days plausible given closing stock and consumption rate?
    """
    if stock_record.empty:
        return {
            "computed_closing": None,
            "reported_closing": None,
            "discrepancy": None,
            "identity_holds": False,
            "stockout_days_plausible": False,
            "data_missing": True,
        }

    row = stock_record.iloc[0]
    opening = _safe_float(row["opening"])
    received = _safe_float(row["received"])
    wastage = _safe_float(row["wastage"])
    consumed = _safe_float(row["consumed"])
    reported_closing = _safe_float(row["closing"])
    stockout_days = _safe_float(row["reported_stockout_days"])

    computed_closing = opening + received - wastage - consumed
    discrepancy = round(computed_closing - reported_closing, 4)
    identity_holds = abs(discrepancy) < 1.0  # allow rounding of 1 unit

    # Plausibility: if closing > 0 AND consumption > 0, daily rate would exhaust
    # stock in (closing / (consumed / 30)) days. If reported_stockout_days is
    # non-zero but closing > 0, that's suspicious.
    if stockout_days > 0 and reported_closing > 0 and consumed > 0:
        # Facility claims stockout but had closing stock
        stockout_days_plausible = False
    elif stockout_days > 0 and reported_closing == 0 and consumed > 0:
        # Stockout with zero closing is internally consistent
        daily_rate = consumed / 30.0
        days_stock_would_last = opening / daily_rate if daily_rate > 0 else 30
        stockout_days_plausible = stockout_days <= 30
    elif stockout_days == 0:
        stockout_days_plausible = True
    else:
        stockout_days_plausible = True

    return {
        "computed_closing": round(computed_closing, 2),
        "reported_closing": reported_closing,
        "discrepancy": discrepancy,
        "identity_holds": bool(identity_holds),
        "stockout_days_plausible": bool(stockout_days_plausible),
        "reported_stockout_days": stockout_days,
        "stock_id": f"stock#{row['id']}",
    }


def _check_h6(
    stock_record: pd.DataFrame,
    stock_history: pd.DataFrame,
) -> dict:
    """
    H6 Expiry / wastage: wastage this month vs 3-month average and vs consumption.
    High if wastage > 2× average monthly wastage AND > 10% of average consumption.
    """
    if stock_record.empty:
        return {
            "wastage_this_month": None,
            "avg_wastage_3m": None,
            "avg_consumed_3m": None,
            "high_wastage": False,
            "data_missing": True,
        }

    row = stock_record.iloc[0]
    wastage_this = _safe_float(row["wastage"])

    hist_sorted = stock_history.sort_values("month", ascending=False)
    last_3 = hist_sorted.head(3)

    if last_3.empty:
        avg_w = 0.0
        avg_c = 0.0
    else:
        avg_w = float(
            last_3["wastage"].apply(
                lambda x: pd.to_numeric(x, errors="coerce")
            ).mean()
        )
        avg_c = float(
            last_3["consumed"].apply(
                lambda x: pd.to_numeric(x, errors="coerce")
            ).mean()
        )

    # High wastage: more than 2× historical average AND >10% of avg consumption
    if avg_w > 0:
        high_wastage = wastage_this > 2 * avg_w and (
            avg_c == 0 or wastage_this > 0.1 * avg_c
        )
    elif avg_c > 0:
        high_wastage = wastage_this > 0.1 * avg_c
    else:
        high_wastage = wastage_this > 0

    return {
        "wastage_this_month": wastage_this,
        "avg_wastage_3m": round(avg_w, 2),
        "avg_consumed_3m": round(avg_c, 2),
        "high_wastage": bool(high_wastage),
        "stock_id": f"stock#{row['id']}",
    }


def _check_h7(
    month: str,
    commodity: str,
    orders_df: pd.DataFrame,
    web_notes: list,
) -> dict:
    """
    H7 National disruption: county-wide fill drop for this commodity/month
    AND a public web notice exists.
    """
    prev_1 = _prev_months(month, 1)[0]

    def county_fill(m: str) -> Optional[float]:
        mask = (orders_df["commodity"] == commodity) & (orders_df["month"] == m)
        sub = orders_df[mask].copy()
        sub = sub[
            sub["qty_requested"].apply(
                lambda x: pd.to_numeric(x, errors="coerce") > 0
            )
        ]
        if sub.empty:
            return None
        rates = (
            pd.to_numeric(sub["qty_delivered"], errors="coerce")
            / pd.to_numeric(sub["qty_requested"], errors="coerce")
        ).clip(0, 1)
        return float(rates.mean())

    fill_this = county_fill(month)
    fill_prev = county_fill(prev_1)

    if fill_this is not None and fill_prev is not None and fill_prev > 0:
        county_fill_drop = round(fill_prev - fill_this, 4)
    else:
        county_fill_drop = None

    # Check web notes: same commodity, within 2 months of the stockout
    prev_2 = _prev_months(month, 2)
    relevant_months = {month, prev_1} | set(prev_2)
    matching_notes = [
        n for n in web_notes
        if n.get("commodity", "").lower() == commodity.lower()
        and n.get("month", "") in relevant_months
    ]
    web_notice_found = len(matching_notes) > 0

    return {
        "county_fill_drop": county_fill_drop,
        "county_fill_this_month": fill_this,
        "county_fill_prev_month": fill_prev,
        "web_notice_found": bool(web_notice_found),
        "notice_details": matching_notes[0] if web_notice_found else None,
    }
