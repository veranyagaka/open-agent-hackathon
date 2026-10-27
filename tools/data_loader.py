"""
tools/data_loader.py

Deterministic data loading and hypothesis-evidence calculations.
NO LLM calls here — pure pandas/numpy arithmetic only.

Two sources share one interface, ``load_dataset(dataset_dir, source=None)``:

- ``csv``      reads ``stock.csv``, ``orders.csv``, ``payments.csv``,
               ``facilities.csv`` and ``web_notes.json`` from *dataset_dir*.
- ``zetaris``  reads the same tables through Zetaris (datasource
               ``stockwhy_pg``) and the public notices from a second Zetaris
               datasource (``stockwhy_web``). Zetaris holds ONE registered
               dataset: ``data/sample`` (the demo county). Any other folder is
               always read from CSV, so an explicit dataset folder is honoured.

The source actually used is recorded in ``dataset["_source"]``
(``"csv:<dir>"`` or ``"zetaris:<schema>"``), together with
``dataset["_web_notes_source"]``, ``dataset["_warnings"]`` and, for Zetaris,
``dataset["_queries"]`` (SQL text, row count and milliseconds per call).
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

# The one dataset registered in Zetaris (scripts/setup_live.py loads it from
# data/sample/postgres_load.sql and data/sample/web_notes_load.sql).
ZETARIS_DATASET_DIR = REPO_ROOT / "data" / "sample"

VALID_SOURCES = ("csv", "zetaris")

# Column order matches the CSV headers, so empty slices keep the same schema.
TABLE_COLUMNS = {
    "stock": ["id", "facility_id", "commodity", "month", "opening", "received",
              "wastage", "consumed", "closing", "reported_stockout_days"],
    "orders": ["id", "facility_id", "commodity", "month", "cutoff_date",
               "order_date", "qty_requested", "qty_delivered", "delivery_month"],
    "payments": ["id", "month", "county_arrears_flag", "amount_owed_kes"],
    "facilities": ["facility_id", "lat", "lon"],
}
# Facility columns some datasets carry (real names and locations). Selected
# when the Zetaris table has them; the loader falls back to the required ones.
FACILITY_OPTIONAL_COLUMNS = ["facility_name", "facility_type", "county", "sub_county", "osm_id"]
TABLE_ORDER_BY = {"stock": "id", "orders": "id", "payments": "id",
                  "facilities": "facility_id"}
WEB_NOTE_COLUMNS = ["id", "month", "commodity", "source", "title", "url"]

# Literal allow-lists. Zetaris REST takes raw SQL text, so nothing outside
# these patterns is ever inlined into a statement.
_FACILITY_RE = re.compile(r"^FAC-\d{3}$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_COMMODITY_RE = re.compile(r"^[A-Za-z0-9 .%/()\-]{1,80}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

# Rows per Zetaris call. The live SQL Editor run read every table in pages of 100,
# so that is the default; ZETARIS_PAGE_SIZE raises it once a larger page is confirmed.
ZETARIS_PAGE_SIZE = 100


def _display_path(path: Path) -> str:
    """Path relative to the repo when possible, always with forward slashes."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _same_dir(a, b) -> bool:
    norm = lambda p: os.path.normcase(str(Path(p).resolve()))  # noqa: E731
    return norm(a) == norm(b)


def is_zetaris_dataset(dataset_dir) -> bool:
    """True if *dataset_dir* is the dataset registered in Zetaris (data/sample)."""
    return _same_dir(dataset_dir, ZETARIS_DATASET_DIR)


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
        frame = pd.read_csv(path, dtype=str)  # load as str, coerce below
        missing = set(TABLE_COLUMNS.get(name[:-4], [])) - set(frame.columns)
        if missing:
            raise ValueError(f"{path.name} is missing required columns: {sorted(missing)}")
        return frame

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
        with open(web_notes_path, "r", encoding="utf-8") as f:
            web_notes = json.load(f)
    else:
        web_notes = []

    return {
        "stock": stock,
        "orders": orders,
        "payments": payments,
        "facilities": facilities,
        "web_notes": web_notes,
        "_source": f"csv:{_display_path(d)}",
        "_web_notes_source": (
            f"csv:{_display_path(web_notes_path)}" if web_notes_path.exists() else "none"
        ),
        "_warnings": [],
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


def _lower_keys(rows: list) -> list:
    """Column names compared case-insensitively: Zetaris/Spark may upper-case them."""
    return [{str(k).lower(): v for k, v in row.items()} for row in rows]


def _zetaris_rows(response: dict, expected: Optional[list] = None) -> list:
    """
    Normalize common Zetaris SQL-editor row response shapes to a list of
    dicts with lower-case keys. *expected* is the explicit column list the
    SELECT asked for; positional rows without column metadata are zipped
    against it.
    """
    if not isinstance(response, dict):
        raise RuntimeError("Unexpected Zetaris response: expected a JSON object")
    data = response.get("data")
    if isinstance(data, list):
        if not data:
            return []
        if all(isinstance(row, dict) for row in data):
            return _lower_keys(data)
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
            return _lower_keys([dict(zip(names, row)) for row in data])
        if expected and all(isinstance(row, (list, tuple)) for row in data):
            if any(len(row) != len(expected) for row in data):
                raise RuntimeError(
                    "Zetaris returned rows without column names whose width does not match "
                    f"the {len(expected)} selected columns (row widths {[len(r) for r in data[:3]]})"
                )
            return [dict(zip([c.lower() for c in expected], row)) for row in data]
    for key in ("rows", "results"):
        rows = response.get(key)
        if isinstance(rows, list):
            if not rows or all(isinstance(row, dict) for row in rows):
                return _lower_keys(rows)
    if data is None:
        raise RuntimeError(
            "Zetaris SQL response did not contain a 'data' row list; "
            f"response keys: {list(response.keys())}"
        )
    raise RuntimeError(
        "Unsupported Zetaris row format; expected a list of row objects "
        "or rows with column metadata."
    )


# ---------------------------------------------------------------------------
# Zetaris SQL helpers (literal validation; one statement per call)
# ---------------------------------------------------------------------------

def sql_literal(value: str, kind: str) -> str:
    """
    Quote a validated value for inlining in Zetaris SQL.

    kind: "facility" (FAC-123), "month" (YYYY-MM) or "commodity".
    Raises ValueError for anything outside the allow-list.
    """
    pattern = {"facility": _FACILITY_RE, "month": _MONTH_RE,
               "commodity": _COMMODITY_RE}[kind]
    text = str(value)
    if not pattern.match(text):
        raise ValueError(f"Refusing unsafe {kind} value for SQL: {text!r}")
    return "'" + text.replace("'", "''") + "'"


def _schema_name(env_name: str, default: str) -> str:
    name = os.getenv(env_name, "").strip() or default
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"{env_name} must be a plain identifier, not {name!r}")
    return name


# Count columns: Postgres DOUBLE PRECISION comes back as "150.0", the CSV has
# "150". Dropping a zero fraction keeps the pandas dtypes (and so every number
# in the profile) identical to a CSV read.
_COUNT_COLUMNS = {"opening", "received", "wastage", "consumed", "closing",
                  "reported_stockout_days", "qty_requested", "qty_delivered",
                  "county_arrears_flag", "amount_owed_kes", "id"}
_ZERO_FRACTION_RE = re.compile(r"^(-?\d+)\.0+$")


def _as_text(value, count: bool = False):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    text = str(value)
    if count:
        match = _ZERO_FRACTION_RE.match(text)
        if match:
            return match.group(1)
    return text


def _to_frame(rows: list, columns: list, table: str = "") -> pd.DataFrame:
    """
    Build a DataFrame shaped like a CSV read: every value a string, nulls NaN,
    columns in CSV order (so an empty slice still has the full schema).
    Raises RuntimeError if returned rows lack a required column.
    """
    frame = pd.DataFrame(rows, dtype=object)
    if rows:
        missing = set(columns) - set(frame.columns)
        if missing:
            raise RuntimeError(
                f"Zetaris table {table!r} is missing required columns: {sorted(missing)}"
            )
    for col in columns:
        if col not in frame.columns:
            frame[col] = pd.Series(dtype=object)
    frame = frame[columns + [c for c in frame.columns if c not in columns]]
    for col in frame.columns:
        count = col in _COUNT_COLUMNS
        frame[col] = frame[col].map(lambda v: _as_text(v, count)).astype(object)
    return frame


class _ZetarisReader:
    """Runs one SQL statement per call and records each call for the trace."""

    def __init__(self, page_size: Optional[int] = None):
        # Reuse the proven authentication, endpoint and request headers.
        from scripts.check_zetaris import run_sql
        self._run_sql = run_sql
        self.page_size = page_size or int(os.getenv("ZETARIS_PAGE_SIZE", "0") or 0) or ZETARIS_PAGE_SIZE
        self.queries: list = []

    def rows(self, sql: str, limit: Optional[int] = None, columns: Optional[list] = None) -> list:
        start = time.monotonic()
        try:
            response = self._run_sql(sql, limit=limit or self.page_size)
            rows = _zetaris_rows(response, columns)
        except Exception as exc:
            self.queries.append({"sql": sql, "rows": 0, "error": str(exc)[:200],
                                 "ms": round((time.monotonic() - start) * 1000, 1)})
            raise
        self.queries.append({
            "sql": sql,
            "rows": len(rows),
            "ms": round((time.monotonic() - start) * 1000, 1),
        })
        return rows

    def table(self, sql_base: str, order_by: str, columns: Optional[list] = None) -> list:
        """Read every row of *sql_base*, a page of ``page_size`` rows per call."""
        rows: list = []
        offset = 0
        while True:
            sql = f"{sql_base} ORDER BY {order_by} LIMIT {self.page_size}"
            if offset:
                sql += f" OFFSET {offset}"
            page = self.rows(sql, columns=columns)
            rows.extend(page)
            if len(page) < self.page_size:
                return rows
            offset += self.page_size
            if offset > 1_000_000:
                raise RuntimeError(f"Aborting Zetaris pagination: safety limit exceeded ({sql_base})")


def _load_zetaris_web_notes(reader: _ZetarisReader, dataset_dir: Path,
                            warnings: list) -> tuple:
    """Public notices from the second Zetaris datasource, else the local JSON."""
    web_schema = _schema_name("ZETARIS_WEB_SCHEMA", "stockwhy_web")
    try:
        rows = reader.table(
            f"SELECT {', '.join(WEB_NOTE_COLUMNS)} FROM {web_schema}.web_notes", "id",
            WEB_NOTE_COLUMNS,
        )
        notes = [
            {k: (None if row.get(k) is None else str(row.get(k))) for k in WEB_NOTE_COLUMNS}
            for row in rows
        ]
        return notes, f"zetaris:{web_schema}"
    except Exception as exc:  # network, auth, missing datasource, bad shape
        path = Path(dataset_dir) / "web_notes.json"
        msg = f"Zetaris {web_schema}.web_notes unavailable ({str(exc)[:200]})"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                notes = json.load(f)
            warnings.append(f"{msg}; public notices read from {_display_path(path)}")
            return notes, f"csv:{_display_path(path)}"
        warnings.append(f"{msg}; no local web_notes.json either, so no public notices")
        return [], "none"


def load_zetaris_dataset(
    dataset_dir: Optional[str] = None,
    facility_id: Optional[str] = None,
    commodity: Optional[str] = None,
    month: Optional[str] = None,
) -> dict:
    """
    Load the StockWhy tables from Zetaris, preserving the CSV schema and types.

    Without a scope every table is read in full (one call per table for the
    demo county). With a scope the filters are pushed into SQL, reading only
    what ``profile_stockout`` uses for that case:

    - stock:      WHERE facility_id = ... AND commodity = ...  (history + month)
    - orders:     WHERE commodity = ... [AND (month IN (prev2, prev, month)
                  OR delivery_month IN (prev, month))]
                  (the county averages need every facility in the cycle)
    - payments, facilities: full (county-wide; returned in the profile)

    *dataset_dir* only locates the local ``web_notes.json`` fallback.
    """
    schema = _schema_name("ZETARIS_SCHEMA", "stockwhy_pg")
    reader = _ZetarisReader()
    warnings: list = []
    scoped = facility_id is not None or commodity is not None

    def select(table: str, columns: Optional[list] = None, where: str = "") -> list:
        columns = columns or TABLE_COLUMNS[table]
        sql = f"SELECT {', '.join(columns)} FROM {schema}.{table}"
        if where:
            sql += f" WHERE {where}"
        return reader.table(sql, TABLE_ORDER_BY[table], columns)

    def full(table: str) -> pd.DataFrame:
        return _to_frame(select(table), TABLE_COLUMNS[table], table)

    def facilities() -> pd.DataFrame:
        # Names and locations when the table has them, else the required columns.
        try:
            rows = select("facilities", TABLE_COLUMNS["facilities"] + FACILITY_OPTIONAL_COLUMNS)
        except RuntimeError:
            rows = select("facilities")
        return _to_frame(rows, TABLE_COLUMNS["facilities"], "facilities")

    def empty(table: str) -> pd.DataFrame:
        return _to_frame([], TABLE_COLUMNS[table])

    if scoped:
        if facility_id is None or commodity is None:
            raise ValueError("A Zetaris scope needs both facility_id and commodity")
        fac_lit = sql_literal(facility_id, "facility")
        com_lit = sql_literal(commodity, "commodity")
        known = {
            str(r.get("commodity"))
            for r in reader.rows(f"SELECT DISTINCT commodity FROM {schema}.stock", limit=1000,
                                 columns=["commodity"])
        }
        if commodity not in known:
            # Same outcome as the CSV path: no rows for an unknown commodity.
            warnings.append(f"Commodity {commodity!r} is not in {schema}.stock")
            stock, orders = empty("stock"), empty("orders")
        else:
            stock = _to_frame(select("stock", where=f"facility_id = {fac_lit} AND commodity = {com_lit}"),
                              TABLE_COLUMNS["stock"], "stock")
            order_filter = f"commodity = {com_lit}"
            if month is not None:
                month_lit = sql_literal(month, "month")
                prev_1, prev_2 = _prev_months(month, 2)
                prev_lit = sql_literal(prev_1, "month")
                prev2_lit = sql_literal(prev_2, "month")
                # Orders placed in the cycle, plus every order that delivered
                # into the stock-out month or the month before (county fill)
                order_filter += (
                    f" AND (month IN ({prev2_lit}, {prev_lit}, {month_lit})"
                    f" OR delivery_month IN ({prev_lit}, {month_lit}))"
                )
            orders = _to_frame(select("orders", where=order_filter), TABLE_COLUMNS["orders"], "orders")
    else:
        stock, orders = full("stock"), full("orders")

    dataset = {
        "stock": stock,
        "orders": orders,
        "payments": full("payments"),
        "facilities": facilities(),
    }
    required_rows = ("payments", "facilities") if scoped else tuple(TABLE_COLUMNS)
    for table in TABLE_COLUMNS:
        missing = set(TABLE_COLUMNS[table]) - set(dataset[table].columns)
        if missing:
            raise RuntimeError(
                f"Zetaris table {table!r} is missing required columns: {sorted(missing)}"
            )
    for table in required_rows:
        if dataset[table].empty:
            raise RuntimeError(f"Zetaris returned no rows for required table {table!r}")

    web_notes, web_source = _load_zetaris_web_notes(
        reader, Path(dataset_dir) if dataset_dir else ZETARIS_DATASET_DIR, warnings
    )
    dataset["web_notes"] = web_notes
    dataset = _coerce_dataset(dataset)
    dataset["_source"] = f"zetaris:{schema}"
    dataset["_web_notes_source"] = web_source
    dataset["_warnings"] = warnings
    dataset["_queries"] = reader.queries
    if scoped:
        dataset["_scope"] = {"facility_id": facility_id, "commodity": commodity, "month": month}
    return dataset


def resolve_source(source: Optional[str] = None) -> str:
    """
    The data source to use: *source* if given, else ``csv`` when
    SAMPLE_MODE=true (judges run offline), else STOCKWHY_DATA_SOURCE
    (default ``csv``).
    """
    if source is None:
        if os.getenv("SAMPLE_MODE", "false").strip().lower() == "true":
            return "csv"
        source = os.getenv("STOCKWHY_DATA_SOURCE", "") or "csv"
        label = "STOCKWHY_DATA_SOURCE"
    else:
        label = "source"
    source = str(source).strip().lower()
    if source not in VALID_SOURCES:
        raise ValueError(
            f"{label} must be either 'csv' or 'zetaris', not {source!r}"
        )
    return source


def load_dataset(
    dataset_dir: str,
    source: Optional[str] = None,
    facility_id: Optional[str] = None,
    commodity: Optional[str] = None,
    month: Optional[str] = None,
) -> dict:
    """
    Load a dataset from CSV or Zetaris.

    source : "csv", "zetaris" or None (None -> resolve_source(): SAMPLE_MODE=true
             forces csv, otherwise STOCKWHY_DATA_SOURCE, default csv).

    Zetaris holds one registered dataset, data/sample. For any other
    *dataset_dir* the folder is honoured: with the source taken from the
    environment it is read from CSV and a warning is recorded; with
    source="zetaris" passed explicitly a ValueError is raised.

    facility_id / commodity / month optionally scope a Zetaris read so the
    filters run in SQL (see load_zetaris_dataset). They do not change the CSV
    read, and profile_stockout gives the same result either way.

    The returned dict has stock, orders, payments, facilities, web_notes plus
    ``_source`` ("csv:<dir>" or "zetaris:<schema>"), ``_web_notes_source``
    and ``_warnings`` (and ``_queries`` for Zetaris).
    """
    explicit = source is not None
    chosen = resolve_source(source)
    if chosen == "zetaris":
        if is_zetaris_dataset(dataset_dir):
            return load_zetaris_dataset(dataset_dir, facility_id, commodity, month)
        shown = _display_path(Path(dataset_dir))
        registered = _display_path(ZETARIS_DATASET_DIR)
        if explicit:
            raise ValueError(
                f"Zetaris holds only the {registered} dataset; {shown} is not "
                "registered. Use source='csv' for other dataset folders."
            )
        dataset = _load_csv_dataset(dataset_dir)
        dataset["_warnings"].append(
            f"STOCKWHY_DATA_SOURCE=zetaris, but Zetaris holds only {registered}; "
            f"{shown} was read from CSV"
        )
        return dataset
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


def _county_fill_arriving(
    orders_df: pd.DataFrame, commodity: str, m: str
) -> Optional[float]:
    """
    County-wide fill rate of the supply that ARRIVES in month *m* for one
    commodity: orders whose delivery_month is *m* (the previous month's
    cycle). Falls back to orders placed the month before when
    delivery_month is missing.
    """
    if "delivery_month" in orders_df.columns:
        mask = orders_df["delivery_month"].astype(str) == m
    else:
        mask = orders_df["month"] == _prev_months(m, 1)[0]
    sub = orders_df[(orders_df["commodity"] == commodity) & mask].copy()
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


def _check_h3(
    month: str,
    payments_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    commodity: str,
) -> dict:
    """
    H3 Payment arrears: county owed >=30M KES in or just before *month*,
    AND the county-wide fill rate of supply arriving this month dropped
    compared to the supply that arrived the month before.
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

    # County-wide fill rate of the supply arriving this month vs the
    # supply that arrived the month before (orders deliver a month later)
    prev_1 = _prev_months(month, 1)[0]
    fill_this = _county_fill_arriving(orders_df, commodity, month)
    fill_prev = _county_fill_arriving(orders_df, commodity, prev_1)

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
    H4 Demand surge: demand this month vs 3-month rolling average.

    When the stock row reports stock-out days (0 < days < 30), issues were
    capped by the days without stock, so demand is estimated as
    consumed x 30 / (30 - reported_stockout_days) and ``demand_basis`` says
    "stockout_adjusted". The issues-only figure is kept in
    ``pct_change_issues_only``. The adjustment is only valid if the facility
    really had no stock on those days; the Evaluator re-reads the row and
    rejects it when closing stock is above zero (see agents/evaluator.py).
    """
    if stock_record.empty:
        return {
            "consumed_this_month": None,
            "avg_consumed_3m": None,
            "pct_change": None,
            "surge": False,
            "data_missing": True,
        }

    row = stock_record.iloc[0]
    consumed_this = _safe_float(row["consumed"])
    stockout_days = _safe_float(row.get("reported_stockout_days"))

    # Last 3 months from history
    hist_sorted = stock_history.sort_values("month", ascending=False)
    last_3 = hist_sorted.head(3)

    avg_3m = None
    pct_issues = None
    if not last_3.empty:
        avg_3m = float(
            last_3["consumed"].apply(
                lambda x: pd.to_numeric(x, errors="coerce")
            ).mean()
        )
        if avg_3m and avg_3m > 0:
            pct_issues = round((consumed_this - avg_3m) / avg_3m * 100, 2)

    out = {
        "consumed_this_month": consumed_this,
        "avg_consumed_3m": round(avg_3m, 2) if avg_3m is not None else None,
        "reported_stockout_days": stockout_days,
        "pct_change_issues_only": pct_issues,
        "demand_basis": "issues_only",
        "pct_change": pct_issues,
        "stock_id": f"stock#{row['id']}",
    }
    if pct_issues is not None and 0 < stockout_days < 30:
        adjusted = consumed_this * 30.0 / (30.0 - stockout_days)
        out["demand_basis"] = "stockout_adjusted"
        out["adjusted_demand"] = round(adjusted, 2)
        out["pct_change"] = round((adjusted - avg_3m) / avg_3m * 100, 2)
    out["surge"] = bool(out["pct_change"] is not None and out["pct_change"] > 25)
    return out


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
    identity_holds = abs(discrepancy) <= 1.0  # allow rounding of 1 unit

    # Plausibility: if closing > 0 AND consumption > 0, daily rate would exhaust
    # stock in (closing / (consumed / 30)) days. If reported_stockout_days is
    # non-zero but closing > 0, that's suspicious.
    if stockout_days > 0 and reported_closing > 0 and consumed > 0:
        # Facility claims stockout but had closing stock
        stockout_days_plausible = False
    elif stockout_days > 0 and reported_closing == 0 and consumed > 0:
        # Stockout with zero closing is internally consistent
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
    H7 National disruption: county-wide fill drop in the supply arriving in
    this month for this commodity AND a public web notice exists.
    """
    prev_1 = _prev_months(month, 1)[0]
    # Supply arriving in the stock-out month vs the month before
    fill_this = _county_fill_arriving(orders_df, commodity, month)
    fill_prev = _county_fill_arriving(orders_df, commodity, prev_1)

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
