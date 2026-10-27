"""Unit tests for the optional Zetaris-backed data loader."""
import json
from pathlib import Path
from unittest.mock import MagicMock
import urllib.error

import pandas as pd
import pytest

from scripts import check_zetaris
from tools import data_loader


def _responses():
    return {
        "stock": [{"id": "1", "facility_id": "FAC-001", "commodity": "oxytocin", "month": "2024-10", "opening": "10", "received": "5", "wastage": "0", "consumed": "8", "closing": "7", "reported_stockout_days": "0"}],
        "orders": [{"id": "2", "facility_id": "FAC-001", "commodity": "oxytocin", "month": "2024-09", "cutoff_date": "2024-09-10", "order_date": "2024-09-08", "qty_requested": "10", "qty_delivered": "10", "delivery_month": "2024-10"}],
        "payments": [{"id": "3", "month": "2024-10", "county_arrears_flag": "1", "amount_owed_kes": "1000"}],
        "facilities": [{"facility_id": "FAC-001", "lat": "-1.2", "lon": "36.8"}],
    }


def test_zetaris_loader_converts_types_and_preserves_web_notes(tmp_path, monkeypatch):
    monkeypatch.setenv("ZETARIS_SCHEMA", "STOCKWHY_PG")
    notes = [{"commodity": "oxytocin", "note": "test note"}]
    (tmp_path / "web_notes.json").write_text(json.dumps(notes), encoding="utf-8")
    tables = _responses()
    calls = []

    def fake_run_sql(sql):
        calls.append(sql)
        table = next(name for name in tables if f".{name} " in sql)
        columns = list(tables[table][0])
        return {"data": [[row[column] for column in columns] for row in tables[table]]}

    monkeypatch.setattr("scripts.check_zetaris.run_sql", fake_run_sql)
    dataset = data_loader.load_zetaris_dataset(str(tmp_path))
    assert set(dataset) == {"stock", "orders", "payments", "facilities", "web_notes"}
    assert pd.api.types.is_numeric_dtype(dataset["stock"]["opening"])
    assert pd.api.types.is_datetime64_any_dtype(dataset["orders"]["order_date"])
    assert pd.api.types.is_numeric_dtype(dataset["facilities"]["lat"])
    assert dataset["web_notes"] == notes
    assert len(calls) == 4
    assert all("SELECT *" not in query for query in calls)


def test_zetaris_loader_fails_if_required_columns_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("ZETARIS_SCHEMA", "STOCKWHY_PG")
    (tmp_path / "web_notes.json").write_text("[]", encoding="utf-8")
    def fake_run_sql(sql):
        table = sql.lower().split("stockwhy_pg.", 1)[1].split()[0]
        return {"data": [{"wrong_column": "x"}]}
    monkeypatch.setattr("scripts.check_zetaris.run_sql", fake_run_sql)
    with pytest.raises(RuntimeError, match="missing required columns"):
        data_loader.load_zetaris_dataset(str(tmp_path))


def test_zetaris_loader_uses_configured_schema_and_investigation_filters(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ZETARIS_SCHEMA", "team_stockwhy")
    (tmp_path / "web_notes.json").write_text("[]", encoding="utf-8")
    tables = _responses()
    calls = []

    def fake_run_sql(sql):
        calls.append(sql)
        table = next(name for name in tables if f".{name} " in sql)
        columns = list(tables[table][0])
        return {
            "data": [
                [row[column] for column in columns]
                for row in tables[table]
            ]
        }

    monkeypatch.setattr("scripts.check_zetaris.run_sql", fake_run_sql)
    dataset = data_loader.load_zetaris_dataset(
        str(tmp_path), "FAC-001", "oxytocin", "2024-10"
    )

    assert len(dataset["stock"]) == 1
    stock_query = next(query for query in calls if ".stock " in query)
    orders_query = next(query for query in calls if ".orders " in query)
    assert "FROM team_stockwhy.stock WHERE" in stock_query
    assert "facility_id = 'FAC-001'" in stock_query
    assert "commodity = 'oxytocin'" in stock_query
    assert "month IN ('2024-10', '2024-09'" in stock_query
    assert "FROM team_stockwhy.orders WHERE" in orders_query
    assert "commodity = 'oxytocin'" in orders_query
    assert "month IN ('2024-10', '2024-09')" in orders_query
    assert all("team_stockwhy." in query for query in calls)


def test_zetaris_loader_rejects_unsafe_schema_identifier(tmp_path, monkeypatch):
    monkeypatch.setenv("ZETARIS_SCHEMA", "stockwhy; DROP TABLE stock")

    with pytest.raises(ValueError, match="ZETARIS_SCHEMA"):
        data_loader.load_zetaris_dataset(str(tmp_path))


def test_zetaris_loader_requires_all_scope_parameters(tmp_path, monkeypatch):
    monkeypatch.setenv("ZETARIS_SCHEMA", "STOCKWHY_PG")

    with pytest.raises(ValueError, match="requires facility_id, commodity, and month"):
        data_loader.load_zetaris_dataset(str(tmp_path), facility_id="FAC-001")


def test_load_dataset_defaults_to_csv(tmp_path, monkeypatch):
    monkeypatch.delenv("SAMPLE_MODE", raising=False)
    monkeypatch.delenv("STOCKWHY_DATA_SOURCE", raising=False)
    monkeypatch.setattr(data_loader, "_load_csv_dataset", lambda path: {"source": "csv"})
    assert data_loader.load_dataset(str(tmp_path)) == {"source": "csv"}


def test_load_dataset_rejects_unknown_source(monkeypatch):
    monkeypatch.delenv("SAMPLE_MODE", raising=False)
    monkeypatch.setenv("STOCKWHY_DATA_SOURCE", "other")
    with pytest.raises(ValueError, match="STOCKWHY_DATA_SOURCE"):
        data_loader.load_dataset("unused")


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


def test_zetaris_rows_supports_documented_positional_data_without_headers():
    response = {"data": [["FAC-001", "-1.2", "36.8"]]}
    assert data_loader._zetaris_rows(
        response, expected_columns=["facility_id", "lat", "lon"]
    ) == [{"facility_id": "FAC-001", "lat": "-1.2", "lon": "36.8"}]


def test_zetaris_rows_supports_named_row_objects():
    from collections import namedtuple

    Row = namedtuple("Row", ["id", "month"])
    assert data_loader._zetaris_rows({"data": [Row("1", "2026-03")]}) == [
        {"id": "1", "month": "2026-03"}
    ]


def test_zetaris_rows_rejects_mismatched_header_width():
    response = {"headers": ["id", "month"], "data": [["1"]]}
    with pytest.raises(RuntimeError, match="row width does not match"):
        data_loader._zetaris_rows(response)


def test_zetaris_rows_rejects_positional_rows_without_column_names():
    with pytest.raises(RuntimeError, match="without column metadata"):
        data_loader._zetaris_rows({"data": [["1", "2026-03"]]})


def test_zetaris_rows_rejects_malformed_result():
    with pytest.raises(RuntimeError, match="row list"):
        data_loader._zetaris_rows({"data": {"unexpected": "shape"}})


def test_zetaris_client_fails_actionably_when_configuration_is_missing(monkeypatch):
    for name in ("ZETARIS_REST_URL", "ZETARIS_API_KEY", "ZETARIS_ORG_ID"):
        monkeypatch.setenv(name, "")

    with pytest.raises(RuntimeError, match="ZETARIS_REST_URL.*ZETARIS_API_KEY.*ZETARIS_ORG_ID"):
        check_zetaris.run_sql("SELECT 1")


def test_zetaris_client_success_uses_documented_request_contract(monkeypatch):
    monkeypatch.setenv("ZETARIS_REST_URL", "http://localhost:8888/api/v1.0")
    monkeypatch.setenv("ZETARIS_API_KEY", "unit-test-token")
    monkeypatch.setenv("ZETARIS_ORG_ID", "1")
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"data":[["1"]]}'
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return response

    monkeypatch.setattr(check_zetaris.urllib.request, "urlopen", fake_urlopen)
    result = check_zetaris.run_sql("SELECT 1")

    request = captured["request"]
    headers = {key.lower(): value for key, value in request.header_items()}
    assert result == {"data": [["1"]]}
    assert request.full_url.endswith("/sql-editor/sqls/run")
    assert headers["authorization"] == "Bearer unit-test-token"
    assert headers["x-org-id"] == "1"
    assert len(headers["x-request-id"]) == 36
    assert captured["timeout"] == 45


def test_zetaris_http_failure_does_not_disclose_response_body(monkeypatch):
    monkeypatch.setenv("ZETARIS_REST_URL", "http://localhost:8888/api/v1.0")
    monkeypatch.setenv("ZETARIS_API_KEY", "unit-test-token")
    monkeypatch.setenv("ZETARIS_ORG_ID", "1")
    monkeypatch.setattr(
        check_zetaris.urllib.request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(
            urllib.error.HTTPError(
                request.full_url,
                401,
                "unauthorized",
                {},
                None,
            )
        ),
    )

    with pytest.raises(RuntimeError, match="HTTP 401") as error:
        check_zetaris.run_sql("SELECT 1")
    assert "unit-test-token" not in str(error.value)
