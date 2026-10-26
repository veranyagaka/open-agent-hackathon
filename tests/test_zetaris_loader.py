"""Unit tests for the Zetaris-backed data loader. No network: Zetaris is mocked.

The fake Zetaris is an in-memory SQLite database loaded from data/sample (the
dataset registered in Zetaris), attached as stockwhy_pg and stockwhy_web, and it
answers in the shape a real install returns: {"headers": [...], "data": [[...]]}
with every value as a string.
"""
import csv
import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from tools import data_loader
from tools.data_loader import load_dataset, profile_stockout

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = ROOT / "data" / "sample"
CASE_NORMAL_01 = ROOT / "data" / "cases" / "normal" / "case_01"
CASE_NORMAL_06 = ROOT / "data" / "cases" / "normal" / "case_06"

_SQL_TYPES = {
    "stock": {"id": "INTEGER", "opening": "REAL", "received": "REAL", "wastage": "REAL",
              "consumed": "REAL", "closing": "REAL", "reported_stockout_days": "INTEGER"},
    "orders": {"id": "INTEGER", "qty_requested": "REAL", "qty_delivered": "REAL"},
    "payments": {"id": "INTEGER", "county_arrears_flag": "INTEGER", "amount_owed_kes": "REAL"},
    "facilities": {"lat": "REAL", "lon": "REAL"},
}


class FakeZetaris:
    """Answers SQL like the Zetaris SQL Editor REST endpoint, and records it."""

    def __init__(self, with_web=True):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("ATTACH DATABASE ':memory:' AS stockwhy_pg")
        self.conn.execute("ATTACH DATABASE ':memory:' AS stockwhy_web")
        for table, cols in data_loader.TABLE_COLUMNS.items():
            types = _SQL_TYPES[table]
            defs = ", ".join(f"{c} {types.get(c, 'TEXT')}" for c in cols)
            self.conn.execute(f"CREATE TABLE stockwhy_pg.{table} ({defs})")
            with (SAMPLE_DIR / f"{table}.csv").open(newline="", encoding="utf-8") as f:
                rows = [tuple(r[c] for c in cols) for r in csv.DictReader(f)]
            marks = ", ".join("?" for _ in cols)
            self.conn.executemany(f"INSERT INTO stockwhy_pg.{table} VALUES ({marks})", rows)
        if with_web:
            self.conn.execute(
                "CREATE TABLE stockwhy_web.web_notes "
                "(id INTEGER, month TEXT, commodity TEXT, source TEXT, title TEXT, url TEXT)"
            )
            notes = json.loads((SAMPLE_DIR / "web_notes.json").read_text(encoding="utf-8"))
            self.conn.executemany(
                "INSERT INTO stockwhy_web.web_notes VALUES (?, ?, ?, ?, ?, ?)",
                [(i, n["month"], n["commodity"], n["source"], n["title"], n["url"])
                 for i, n in enumerate(notes, 1)],
            )
        self.calls = []

    def run_sql(self, sql, limit=100):
        self.calls.append(sql)
        try:
            cur = self.conn.execute(sql)
        except sqlite3.Error as exc:
            raise RuntimeError(f"Zetaris returned HTTP 400: {exc}") from None
        headers = [d[0] for d in cur.description]
        data = [[None if v is None else str(v) for v in row] for row in cur.fetchmany(limit)]
        return {"headers": headers, "data": data}


@pytest.fixture
def fake_zetaris(monkeypatch):
    fake = FakeZetaris()
    monkeypatch.setattr("scripts.check_zetaris.run_sql", fake.run_sql)
    return fake


@pytest.fixture
def no_network(monkeypatch):
    def refuse(sql, limit=100):
        raise AssertionError(f"Zetaris must not be called here: {sql}")
    monkeypatch.setattr("scripts.check_zetaris.run_sql", refuse)


def _canonical(profile):
    return json.dumps(profile, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# Zetaris reads
# ---------------------------------------------------------------------------

def test_full_read_converts_types_and_records_source(fake_zetaris):
    dataset = data_loader.load_zetaris_dataset(str(SAMPLE_DIR))
    assert dataset["_source"] == "zetaris:stockwhy_pg"
    assert dataset["_web_notes_source"] == "zetaris:stockwhy_web"
    assert dataset["_warnings"] == []
    assert len(dataset["stock"]) == 4320
    assert len(dataset["orders"]) == 4320
    assert pd.api.types.is_numeric_dtype(dataset["stock"]["opening"])
    assert pd.api.types.is_datetime64_any_dtype(dataset["orders"]["order_date"])
    assert pd.api.types.is_numeric_dtype(dataset["facilities"]["lat"])
    assert dataset["stock"]["id"].iloc[0] == "1"
    # One call per table (no 100-row paging), plus the second datasource.
    assert len(fake_zetaris.calls) == 5
    assert any("stockwhy_web.web_notes" in sql for sql in fake_zetaris.calls)
    assert [q["sql"] for q in dataset["_queries"]] == fake_zetaris.calls


def test_web_notes_come_from_second_datasource(fake_zetaris):
    dataset = data_loader.load_zetaris_dataset(str(SAMPLE_DIR))
    assert [n["commodity"] for n in dataset["web_notes"]] == ["ORS sachet", "zinc 20mg tab"]
    assert dataset["web_notes"][0]["id"] == "1"


def test_web_notes_fall_back_to_local_json_with_warning(monkeypatch):
    fake = FakeZetaris(with_web=False)
    monkeypatch.setattr("scripts.check_zetaris.run_sql", fake.run_sql)
    dataset = data_loader.load_zetaris_dataset(str(SAMPLE_DIR))
    assert dataset["_web_notes_source"] == "csv:data/sample/web_notes.json"
    assert dataset["web_notes"] == json.loads(
        (SAMPLE_DIR / "web_notes.json").read_text(encoding="utf-8")
    )
    assert len(dataset["_warnings"]) == 1
    assert "stockwhy_web.web_notes unavailable" in dataset["_warnings"][0]


def test_scoped_read_pushes_filters_into_sql(fake_zetaris):
    dataset = data_loader.load_zetaris_dataset(
        str(SAMPLE_DIR), "FAC-009", "magnesium sulphate inj", "2026-03"
    )
    stock_sql = next(s for s in fake_zetaris.calls if "stockwhy_pg.stock WHERE" in s)
    orders_sql = next(s for s in fake_zetaris.calls if "stockwhy_pg.orders WHERE" in s)
    assert "facility_id = 'FAC-009'" in stock_sql
    assert "commodity = 'magnesium sulphate inj'" in stock_sql
    assert "month IN ('2026-01', '2026-02', '2026-03')" in orders_sql
    assert "delivery_month IN ('2026-02', '2026-03')" in orders_sql
    assert set(dataset["stock"]["facility_id"]) == {"FAC-009"}
    assert set(dataset["orders"]["month"]) == {"2026-01", "2026-02", "2026-03"}
    assert len(dataset["orders"]) == 90  # 30 facilities x 3 order cycles
    assert dataset["_scope"]["facility_id"] == "FAC-009"


def test_csv_and_zetaris_give_identical_profile(fake_zetaris):
    args = ("FAC-009", "magnesium sulphate inj", "2026-03")
    csv_profile = profile_stockout(load_dataset(str(SAMPLE_DIR), source="csv"), *args)
    full = load_dataset(str(SAMPLE_DIR), source="zetaris")
    scoped = load_dataset(str(SAMPLE_DIR), source="zetaris", facility_id=args[0],
                          commodity=args[1], month=args[2])
    assert full["_source"] == scoped["_source"] == "zetaris:stockwhy_pg"
    assert _canonical(profile_stockout(full, *args)) == _canonical(csv_profile)
    assert _canonical(profile_stockout(scoped, *args)) == _canonical(csv_profile)
    assert csv_profile["computed_evidence"]["h1_late_order"]["late"] is True


@pytest.mark.parametrize("bad", [
    "FAC-001' OR '1'='1", "FAC-1", "FAC-001; DROP TABLE stock", "fac-001",
])
def test_unsafe_facility_rejected_before_any_sql(no_network, bad):
    with pytest.raises(ValueError, match="unsafe facility"):
        data_loader.load_zetaris_dataset(str(SAMPLE_DIR), bad, "ORS sachet", "2026-03")


@pytest.mark.parametrize("value,kind", [
    ("ORS sachet'; DELETE FROM stock --", "commodity"),
    ("2026-13", "month"),
    ("2026-03' OR 1=1", "month"),
])
def test_sql_literal_rejects_injection(value, kind):
    with pytest.raises(ValueError, match="unsafe"):
        data_loader.sql_literal(value, kind)


def test_unknown_commodity_returns_empty_slices(fake_zetaris):
    dataset = data_loader.load_zetaris_dataset(str(SAMPLE_DIR), "FAC-009", "aspirin", "2026-03")
    assert dataset["stock"].empty and dataset["orders"].empty
    assert "facility_id" in dataset["stock"].columns
    assert not any("aspirin" in sql for sql in fake_zetaris.calls)
    profile = profile_stockout(dataset, "FAC-009", "aspirin", "2026-03")
    assert profile["computed_evidence"]["h5_record_error"]["data_missing"] is True


def test_zetaris_loader_fails_if_required_columns_missing(monkeypatch):
    def fake_run_sql(sql, limit=100):
        return {"data": [{"wrong_column": "x"}]}
    monkeypatch.setattr("scripts.check_zetaris.run_sql", fake_run_sql)
    with pytest.raises(RuntimeError, match="missing required columns"):
        data_loader.load_zetaris_dataset(str(SAMPLE_DIR))


def test_zetaris_loader_fails_on_empty_table(monkeypatch):
    def fake_run_sql(sql, limit=100):
        return {"headers": ["id"], "data": []}
    monkeypatch.setattr("scripts.check_zetaris.run_sql", fake_run_sql)
    with pytest.raises(RuntimeError, match="no rows"):
        data_loader.load_zetaris_dataset(str(SAMPLE_DIR))


def test_pagination_continues_on_full_pages(monkeypatch, fake_zetaris):
    monkeypatch.setattr(data_loader, "ZETARIS_PAGE_SIZE", 1000)
    dataset = data_loader.load_zetaris_dataset(str(SAMPLE_DIR))
    assert len(dataset["stock"]) == 4320
    stock_calls = [s for s in fake_zetaris.calls if "FROM stockwhy_pg.stock" in s]
    assert len(stock_calls) == 5
    assert stock_calls[-1].endswith("LIMIT 1000 OFFSET 4000")


# ---------------------------------------------------------------------------
# Source selection
# ---------------------------------------------------------------------------

def test_load_dataset_defaults_to_csv(monkeypatch, no_network):
    monkeypatch.delenv("STOCKWHY_DATA_SOURCE", raising=False)
    dataset = load_dataset(str(SAMPLE_DIR))
    assert dataset["_source"] == "csv:data/sample"
    assert dataset["_web_notes_source"] == "csv:data/sample/web_notes.json"


def test_load_dataset_rejects_unknown_source(monkeypatch):
    monkeypatch.setenv("STOCKWHY_DATA_SOURCE", "other")
    with pytest.raises(ValueError, match="STOCKWHY_DATA_SOURCE"):
        load_dataset("unused")
    with pytest.raises(ValueError, match="source must be"):
        load_dataset("unused", source="parquet")


def test_sample_mode_forces_csv(monkeypatch, no_network):
    monkeypatch.setenv("STOCKWHY_DATA_SOURCE", "zetaris")
    monkeypatch.setenv("SAMPLE_MODE", "true")
    assert load_dataset(str(SAMPLE_DIR))["_source"] == "csv:data/sample"


def test_env_zetaris_uses_zetaris_for_registered_dataset(monkeypatch, fake_zetaris):
    monkeypatch.setenv("STOCKWHY_DATA_SOURCE", "zetaris")
    assert load_dataset(str(SAMPLE_DIR))["_source"] == "zetaris:stockwhy_pg"


def test_explicit_zetaris_for_unregistered_folder_raises(no_network):
    with pytest.raises(ValueError, match="holds only the data/sample dataset"):
        load_dataset(str(CASE_NORMAL_01), source="zetaris")


# The tests that failed with STOCKWHY_DATA_SOURCE=zetaris in a .env: the explicit
# case folder was ignored and noisy case_01 rows came back from Zetaris.
@pytest.mark.parametrize("case_dir,facility,commodity,check", [
    (CASE_NORMAL_01, "FAC-011", "ORS sachet",
     lambda ce: ce["h4_demand_surge"]["surge"] is True),
    (CASE_NORMAL_06, "FAC-022", "iron-folate tab",
     lambda ce: ce["h1_late_order"]["late"] or ce["h1_late_order"]["delivery_slipped"]),
])
def test_case_folders_honoured_when_env_says_zetaris(monkeypatch, no_network,
                                                     case_dir, facility, commodity, check):
    monkeypatch.setenv("STOCKWHY_DATA_SOURCE", "zetaris")
    dataset = load_dataset(str(case_dir))
    assert dataset["_source"] == "csv:" + case_dir.relative_to(ROOT).as_posix()
    assert "Zetaris holds only data/sample" in dataset["_warnings"][0]
    csv_rows = pd.read_csv(case_dir / "stock.csv", dtype=str)
    assert list(dataset["stock"]["id"]) == list(csv_rows["id"])
    profile = profile_stockout(dataset, facility, commodity, "2026-03")
    assert check(profile["computed_evidence"])
    assert profile["stock_record"][0]["id"] == csv_rows[
        (csv_rows.facility_id == facility) & (csv_rows.commodity == commodity)
        & (csv_rows.month == "2026-03")
    ]["id"].iloc[0]


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def test_zetaris_rows_supports_headers_with_positional_data():
    response = {
        "headers": [
            {"name": "facility_id"}, {"name": "lat"}, {"name": "lon"}
        ],
        "data": [["FAC-001", "-1.2", "36.8"]],
    }
    assert data_loader._zetaris_rows(response) == [
        {"facility_id": "FAC-001", "lat": "-1.2", "lon": "36.8"}
    ]


def test_zetaris_rows_rejects_mismatched_header_width():
    response = {"headers": ["id", "month"], "data": [["1"]]}
    with pytest.raises(RuntimeError, match="row width does not match"):
        data_loader._zetaris_rows(response)
