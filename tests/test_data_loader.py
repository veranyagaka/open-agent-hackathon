"""
tests/test_data_loader.py

Comprehensive tests for tools/data_loader.py.
These tests are entirely deterministic — no LLM calls, no network.
"""

import sys
import os
import json
import math
from pathlib import Path

import pandas as pd
import pytest

# Make project root importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.data_loader import (
    load_dataset,
    profile_stockout,
    _check_h1,
    _check_h2,
    _check_h3,
    _check_h4,
    _check_h5,
    _check_h6,
    _check_h7,
    _prev_months,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_DIR = Path(__file__).parent.parent / "data" / "sample"
CASE_NORMAL_01 = Path(__file__).parent.parent / "data" / "cases" / "normal" / "case_01"
CASE_NORMAL_06 = Path(__file__).parent.parent / "data" / "cases" / "normal" / "case_06"


@pytest.fixture(scope="module")
def sample_dataset():
    return load_dataset(str(SAMPLE_DIR))


@pytest.fixture(scope="module")
def case01_dataset():
    return load_dataset(str(CASE_NORMAL_01))


@pytest.fixture(scope="module")
def case06_dataset():
    return load_dataset(str(CASE_NORMAL_06))


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

class TestPrevMonths:
    def test_basic(self):
        result = _prev_months("2026-03", 3)
        assert result == ["2026-02", "2026-01", "2025-12"]

    def test_year_boundary(self):
        result = _prev_months("2026-01", 2)
        assert result == ["2025-12", "2025-11"]

    def test_single(self):
        result = _prev_months("2025-06", 1)
        assert result == ["2025-05"]

    def test_empty(self):
        result = _prev_months("2025-06", 0)
        assert result == []


# ---------------------------------------------------------------------------
# load_dataset
# ---------------------------------------------------------------------------

class TestLoadDataset:
    def test_loads_all_tables(self, sample_dataset):
        assert "stock" in sample_dataset
        assert "orders" in sample_dataset
        assert "payments" in sample_dataset
        assert "facilities" in sample_dataset
        assert "web_notes" in sample_dataset

    def test_stock_schema(self, sample_dataset):
        cols = set(sample_dataset["stock"].columns)
        required = {
            "id", "facility_id", "commodity", "month",
            "opening", "received", "wastage", "consumed",
            "closing", "reported_stockout_days",
        }
        assert required.issubset(cols)

    def test_orders_schema(self, sample_dataset):
        cols = set(sample_dataset["orders"].columns)
        required = {
            "id", "facility_id", "commodity", "month",
            "cutoff_date", "order_date", "qty_requested",
            "qty_delivered", "delivery_month",
        }
        assert required.issubset(cols)

    def test_payments_schema(self, sample_dataset):
        cols = set(sample_dataset["payments"].columns)
        assert {"id", "month", "county_arrears_flag", "amount_owed_kes"}.issubset(cols)

    def test_facilities_schema(self, sample_dataset):
        cols = set(sample_dataset["facilities"].columns)
        assert {"facility_id", "lat", "lon"}.issubset(cols)

    def test_numeric_types(self, sample_dataset):
        stock = sample_dataset["stock"]
        assert pd.api.types.is_numeric_dtype(stock["opening"])
        assert pd.api.types.is_numeric_dtype(stock["consumed"])
        orders = sample_dataset["orders"]
        assert pd.api.types.is_numeric_dtype(orders["qty_requested"])
        assert pd.api.types.is_numeric_dtype(orders["qty_delivered"])

    def test_date_types(self, sample_dataset):
        orders = sample_dataset["orders"]
        assert pd.api.types.is_datetime64_any_dtype(orders["order_date"])
        assert pd.api.types.is_datetime64_any_dtype(orders["cutoff_date"])

    def test_web_notes_is_list(self, sample_dataset):
        assert isinstance(sample_dataset["web_notes"], list)

    def test_missing_dir_raises(self):
        with pytest.raises(FileNotFoundError):
            load_dataset("/nonexistent/path/to/data")

    def test_nonempty(self, sample_dataset):
        assert len(sample_dataset["stock"]) > 0
        assert len(sample_dataset["orders"]) > 0
        assert len(sample_dataset["facilities"]) > 0


# ---------------------------------------------------------------------------
# profile_stockout
# ---------------------------------------------------------------------------

class TestProfileStockout:
    def test_returns_required_keys(self, case01_dataset):
        profile = profile_stockout(
            case01_dataset, "FAC-011", "ORS sachet", "2026-03"
        )
        for key in (
            "facility_id", "commodity", "month",
            "stock_record", "order_record", "all_orders",
            "payments_history", "stock_history", "facilities",
            "web_notes", "computed_evidence"
        ):
            assert key in profile, f"Missing key: {key}"

    def test_computed_evidence_has_seven_hypotheses(self, case01_dataset):
        profile = profile_stockout(
            case01_dataset, "FAC-011", "ORS sachet", "2026-03"
        )
        ce = profile["computed_evidence"]
        for h in ("h1_late_order", "h2_supplier_underfill", "h3_payment_arrears",
                  "h4_demand_surge", "h5_record_error", "h6_expiry",
                  "h7_national_disruption"):
            assert h in ce, f"Missing hypothesis check: {h}"

    def test_case01_demand_surge_detected(self, case01_dataset):
        """case_01 ground truth: demand_surge for FAC-011/ORS sachet/2026-03"""
        profile = profile_stockout(
            case01_dataset, "FAC-011", "ORS sachet", "2026-03"
        )
        h4 = profile["computed_evidence"]["h4_demand_surge"]
        # demand surge should be detected (pct_change > 25)
        assert h4["surge"] is True, (
            f"Expected demand surge for case_01 but got: {h4}"
        )
        assert h4["consumed_this_month"] is not None
        assert h4["avg_consumed_3m"] is not None
        assert h4["pct_change"] > 25

    def test_case06_late_order_detected(self, case06_dataset):
        """case_06 ground truth: late_order for FAC-022/iron-folate tab/2026-03.
        
        The late order is the February 2026 order (placed 2026-02-20, cutoff 2026-02-10),
        which was delivered in 2026-04 instead of 2026-03, leaving March without stock.
        """
        profile = profile_stockout(
            case06_dataset, "FAC-022", "iron-folate tab", "2026-03"
        )
        h1 = profile["computed_evidence"]["h1_late_order"]
        # Either the order itself is flagged late, or its delivery slipped past March
        is_late_signal = h1.get("late") is True or h1.get("delivery_slipped") is True
        assert is_late_signal, (
            f"Expected late order signal for case_06 but got: {h1}"
        )

    def test_stock_record_ids_are_cited(self, case01_dataset):
        profile = profile_stockout(
            case01_dataset, "FAC-011", "ORS sachet", "2026-03"
        )
        ce = profile["computed_evidence"]
        # h4 and h5 should cite a stock row ID
        h4_id = ce["h4_demand_surge"].get("stock_id", "")
        assert h4_id.startswith("stock#"), f"Expected stock# citation, got: {h4_id}"
        h5_id = ce["h5_record_error"].get("stock_id", "")
        assert h5_id.startswith("stock#"), f"Expected stock# citation, got: {h5_id}"

    def test_order_id_cited(self, case06_dataset):
        profile = profile_stockout(
            case06_dataset, "FAC-022", "iron-folate tab", "2026-03"
        )
        h1_id = profile["computed_evidence"]["h1_late_order"].get("order_id", "")
        assert h1_id.startswith("orders#"), f"Expected orders# citation, got: {h1_id}"


# ---------------------------------------------------------------------------
# H1: Late order
# ---------------------------------------------------------------------------

class TestH1LateOrder:
    def _make_order(self, order_date: str, cutoff_date: str, month: str = "2026-02",
                    delivery_month: str = "2026-03") -> pd.DataFrame:
        """
        Make a previous-month order that should deliver in the following month.
        month = order month (prev month), delivery_month = stockout month.
        """
        return pd.DataFrame([{
            "id": "999",
            "facility_id": "FAC-001",
            "commodity": "test",
            "month": month,
            "cutoff_date": pd.Timestamp(cutoff_date),
            "order_date": pd.Timestamp(order_date),
            "qty_requested": "100",
            "qty_delivered": "80",
            "delivery_month": delivery_month,
        }])

    def test_on_time_order(self):
        # Ordered on time (before cutoff) and delivered as expected
        order = self._make_order("2026-02-05", "2026-02-10",
                                  month="2026-02", delivery_month="2026-03")
        result = _check_h1(order, expected_delivery_month="2026-03")
        assert result["late"] is False
        assert result["days_late"] == -5

    def test_late_order_delivery_slipped(self):
        # Ordered late AND delivery slipped to 2026-04 instead of 2026-03
        order = self._make_order("2026-02-15", "2026-02-10",
                                  month="2026-02", delivery_month="2026-04")
        result = _check_h1(order, expected_delivery_month="2026-03")
        assert result["late"] is True
        assert result["days_late"] == 5
        assert result["delivery_slipped"] is True

    def test_on_cutoff_day(self):
        order = self._make_order("2026-02-10", "2026-02-10",
                                  month="2026-02", delivery_month="2026-03")
        result = _check_h1(order, expected_delivery_month="2026-03")
        assert result["late"] is False
        assert result["days_late"] == 0

    def test_empty_order(self):
        result = _check_h1(pd.DataFrame(), expected_delivery_month="2026-03")
        assert result["late"] is False
        assert result["data_missing"] is True

    def test_expected_delivery_month_stored(self):
        order = self._make_order("2026-02-05", "2026-02-10",
                                  month="2026-02", delivery_month="2026-03")
        result = _check_h1(order, expected_delivery_month="2026-03")
        assert result["expected_delivery_month"] == "2026-03"

    def test_december_delivery_month_slipped(self):
        # December order slipped to February
        order = self._make_order("2026-12-15", "2026-12-10",
                                  month="2026-12", delivery_month="2027-02")
        result = _check_h1(order, expected_delivery_month="2027-01")
        assert result["late"] is True
        assert result["delivery_slipped"] is True


# ---------------------------------------------------------------------------
# H2: Supplier underfill
# ---------------------------------------------------------------------------

class TestH2SupplierUnderfill:
    def _make_orders(self, fac_req, fac_del, other_data) -> tuple:
        """Returns (facility_order_df, all_orders_df)"""
        rows = [{"id": "1", "facility_id": "FAC-001", "commodity": "test",
                 "month": "2026-03", "qty_requested": str(fac_req),
                 "qty_delivered": str(fac_del)}]
        for i, (req, del_) in enumerate(other_data, start=2):
            rows.append({
                "id": str(i), "facility_id": f"FAC-{i:03d}",
                "commodity": "test", "month": "2026-03",
                "qty_requested": str(req), "qty_delivered": str(del_),
            })
        all_df = pd.DataFrame(rows)
        # Add required date columns
        all_df["cutoff_date"] = pd.NaT
        all_df["order_date"] = pd.NaT
        all_df["qty_requested"] = pd.to_numeric(all_df["qty_requested"], errors="coerce")
        all_df["qty_delivered"] = pd.to_numeric(all_df["qty_delivered"], errors="coerce")
        fac_df = all_df[all_df["facility_id"] == "FAC-001"].copy()
        return fac_df, all_df

    def test_underfill_detected(self):
        # facility gets 40% fill, others get ~95%
        fac, all_orders = self._make_orders(
            100, 40,  # 40% fill rate
            [(100, 95), (100, 98), (100, 94)]  # ~95% avg
        )
        result = _check_h2("FAC-001", fac, all_orders)
        assert result["underfill"] is True
        assert result["facility_fill_rate"] == pytest.approx(0.40, abs=0.01)

    def test_no_underfill(self):
        # facility gets 95%, others get similar
        fac, all_orders = self._make_orders(
            100, 95,
            [(100, 94), (100, 96), (100, 93)]
        )
        result = _check_h2("FAC-001", fac, all_orders)
        assert result["underfill"] is False

    def test_empty_facility_order(self):
        _, all_orders = self._make_orders(100, 90, [(100, 90)])
        result = _check_h2("FAC-001", pd.DataFrame(), all_orders)
        assert result["data_missing"] is True


# ---------------------------------------------------------------------------
# H3: Payment arrears
# ---------------------------------------------------------------------------

class TestH3PaymentArrears:
    def _make_payments(self, months_flagged: dict) -> pd.DataFrame:
        rows = []
        for i, m in enumerate(["2026-01", "2026-02", "2026-03"], start=1):
            flagged = months_flagged.get(m, False)
            rows.append({
                "id": str(i), "month": m,
                "county_arrears_flag": "1" if flagged else "0",
                "amount_owed_kes": str(months_flagged.get(m + "_amt", 0)),
            })
        df = pd.DataFrame(rows)
        df["county_arrears_flag"] = pd.to_numeric(df["county_arrears_flag"])
        df["amount_owed_kes"] = pd.to_numeric(df["amount_owed_kes"])
        return df

    def _make_orders(self, this_month_fill: float, prev_month_fill: float) -> pd.DataFrame:
        rows = []
        for fac in range(1, 6):
            rows.append({
                "id": str(fac), "facility_id": f"FAC-{fac:03d}",
                "commodity": "test", "month": "2026-03",
                "qty_requested": "100",
                "qty_delivered": str(int(this_month_fill * 100)),
                "cutoff_date": pd.NaT, "order_date": pd.NaT,
            })
            rows.append({
                "id": str(fac + 10), "facility_id": f"FAC-{fac:03d}",
                "commodity": "test", "month": "2026-02",
                "qty_requested": "100",
                "qty_delivered": str(int(prev_month_fill * 100)),
                "cutoff_date": pd.NaT, "order_date": pd.NaT,
            })
        df = pd.DataFrame(rows)
        df["qty_requested"] = pd.to_numeric(df["qty_requested"])
        df["qty_delivered"] = pd.to_numeric(df["qty_delivered"])
        return df

    def test_major_arrears_detected(self):
        pay = self._make_payments({"2026-03": True, "2026-03_amt": 35_000_000})
        orders = self._make_orders(0.5, 0.95)
        result = _check_h3("2026-03", pay, orders, "test")
        assert result["major_arrears"] is True
        assert result["amount_owed_kes"] == pytest.approx(35_000_000)

    def test_no_arrears(self):
        pay = self._make_payments({})
        orders = self._make_orders(0.95, 0.95)
        result = _check_h3("2026-03", pay, orders, "test")
        assert result["major_arrears"] is False
        assert result["arrears_in_month"] is False

    def test_small_arrears_not_major(self):
        pay = self._make_payments({"2026-03": True, "2026-03_amt": 5_000_000})
        orders = self._make_orders(0.95, 0.95)
        result = _check_h3("2026-03", pay, orders, "test")
        assert result["arrears_in_month"] is True
        assert result["major_arrears"] is False


# ---------------------------------------------------------------------------
# H4: Demand surge
# ---------------------------------------------------------------------------

class TestH4DemandSurge:
    def _make_stock_row(self, consumed: float, stock_id: str = "1") -> pd.DataFrame:
        return pd.DataFrame([{
            "id": stock_id, "facility_id": "FAC-001",
            "commodity": "test", "month": "2026-03",
            "opening": "500", "received": "100", "wastage": "0",
            "consumed": str(consumed), "closing": "100",
            "reported_stockout_days": "0",
        }]).astype({"opening": float, "received": float, "wastage": float,
                    "consumed": float, "closing": float,
                    "reported_stockout_days": float})

    def _make_history(self, values: list) -> pd.DataFrame:
        months = ["2026-02", "2026-01", "2025-12"]
        rows = []
        for m, v in zip(months, values):
            rows.append({
                "id": str(len(rows)+1), "facility_id": "FAC-001",
                "commodity": "test", "month": m,
                "opening": "500", "received": "100", "wastage": "0",
                "consumed": str(v), "closing": "100",
                "reported_stockout_days": "0",
            })
        df = pd.DataFrame(rows)
        for col in ["opening", "received", "wastage", "consumed", "closing",
                    "reported_stockout_days"]:
            df[col] = pd.to_numeric(df[col])
        return df

    def test_surge_detected(self):
        # avg = (100+100+100)/3 = 100, current = 160 → +60%
        result = _check_h4(
            self._make_stock_row(160),
            self._make_history([100, 100, 100])
        )
        assert result["surge"] is True
        assert result["pct_change"] == pytest.approx(60.0, abs=1)

    def test_no_surge(self):
        # avg = 100, current = 110 → +10%
        result = _check_h4(
            self._make_stock_row(110),
            self._make_history([100, 100, 100])
        )
        assert result["surge"] is False

    def test_empty_stock_record(self):
        result = _check_h4(pd.DataFrame(), self._make_history([100, 100, 100]))
        assert result["data_missing"] is True
        assert result["surge"] is False

    def test_borderline_surge(self):
        # +25% is the threshold (>25 triggers surge)
        result = _check_h4(
            self._make_stock_row(125),
            self._make_history([100, 100, 100])
        )
        assert result["surge"] is False  # exactly 25% is not > 25

    def test_just_over_threshold(self):
        result = _check_h4(
            self._make_stock_row(126),
            self._make_history([100, 100, 100])
        )
        assert result["surge"] is True


# ---------------------------------------------------------------------------
# H5: Record error
# ---------------------------------------------------------------------------

class TestH5RecordError:
    def _make_row(self, opening, received, wastage, consumed, closing,
                  stockout_days, stock_id="1") -> pd.DataFrame:
        return pd.DataFrame([{
            "id": stock_id, "facility_id": "FAC-001",
            "commodity": "test", "month": "2026-03",
            "opening": opening, "received": received, "wastage": wastage,
            "consumed": consumed, "closing": closing,
            "reported_stockout_days": stockout_days,
        }]).astype({
            "opening": float, "received": float, "wastage": float,
            "consumed": float, "closing": float,
            "reported_stockout_days": float,
        })

    def test_identity_holds(self):
        # 100 + 50 - 10 - 80 = 60
        result = _check_h5(self._make_row(100, 50, 10, 80, 60, 0))
        assert result["identity_holds"] is True
        assert result["discrepancy"] == pytest.approx(0.0, abs=0.1)

    def test_identity_broken(self):
        # 100 + 50 - 10 - 80 = 60 but reported 70
        result = _check_h5(self._make_row(100, 50, 10, 80, 70, 0))
        assert result["identity_holds"] is False
        assert result["discrepancy"] == pytest.approx(-10.0, abs=0.1)

    def test_implausible_stockout(self):
        # Claims stockout days but has non-zero closing stock
        result = _check_h5(self._make_row(100, 50, 0, 80, 70, 5))
        assert result["stockout_days_plausible"] is False

    def test_plausible_stockout_with_zero_closing(self):
        result = _check_h5(self._make_row(100, 0, 0, 100, 0, 10))
        assert result["stockout_days_plausible"] is True

    def test_empty_record(self):
        result = _check_h5(pd.DataFrame())
        assert result["data_missing"] is True
        assert result["identity_holds"] is False

    def test_stock_id_cited(self):
        result = _check_h5(self._make_row(100, 50, 10, 80, 60, 0, stock_id="1746"))
        assert result["stock_id"] == "stock#1746"


# ---------------------------------------------------------------------------
# H6: Expiry / wastage
# ---------------------------------------------------------------------------

class TestH6Expiry:
    def _make_row(self, wastage: float, consumed: float, stock_id: str = "1") -> pd.DataFrame:
        return pd.DataFrame([{
            "id": stock_id, "facility_id": "FAC-001",
            "commodity": "test", "month": "2026-03",
            "opening": "500", "received": "100", "wastage": str(wastage),
            "consumed": str(consumed), "closing": "100",
            "reported_stockout_days": "0",
        }]).astype({
            "opening": float, "received": float, "wastage": float,
            "consumed": float, "closing": float,
            "reported_stockout_days": float,
        })

    def _make_history(self, wastage_vals: list, consumed_vals: list) -> pd.DataFrame:
        months = ["2026-02", "2026-01", "2025-12"]
        rows = [
            {"id": str(i+1), "facility_id": "FAC-001", "commodity": "test",
             "month": months[i], "opening": "500", "received": "100",
             "wastage": str(wastage_vals[i]), "consumed": str(consumed_vals[i]),
             "closing": "100", "reported_stockout_days": "0"}
            for i in range(min(len(months), len(wastage_vals)))
        ]
        df = pd.DataFrame(rows)
        for col in ["opening", "received", "wastage", "consumed", "closing",
                    "reported_stockout_days"]:
            df[col] = pd.to_numeric(df[col])
        return df

    def test_high_wastage_detected(self):
        # Normal wastage = ~2/month, but this month = 50 (25×) AND >10% of consumption
        result = _check_h6(
            self._make_row(wastage=50, consumed=100),
            self._make_history([2, 2, 2], [100, 100, 100])
        )
        assert result["high_wastage"] is True

    def test_no_high_wastage(self):
        result = _check_h6(
            self._make_row(wastage=2, consumed=100),
            self._make_history([2, 2, 2], [100, 100, 100])
        )
        assert result["high_wastage"] is False

    def test_empty_record(self):
        result = _check_h6(pd.DataFrame(), self._make_history([2, 2, 2], [100, 100, 100]))
        assert result["data_missing"] is True
        assert result["high_wastage"] is False


# ---------------------------------------------------------------------------
# H7: National disruption
# ---------------------------------------------------------------------------

class TestH7NationalDisruption:
    def _make_orders(self, this_month_fill: float, prev_fill: float) -> pd.DataFrame:
        rows = []
        for fac in range(1, 6):
            rows.append({
                "id": str(fac), "facility_id": f"FAC-{fac:03d}",
                "commodity": "test", "month": "2026-03",
                "qty_requested": "100",
                "qty_delivered": str(int(this_month_fill * 100)),
            })
            rows.append({
                "id": str(fac + 10), "facility_id": f"FAC-{fac:03d}",
                "commodity": "test", "month": "2026-02",
                "qty_requested": "100",
                "qty_delivered": str(int(prev_fill * 100)),
            })
        df = pd.DataFrame(rows)
        df["qty_requested"] = pd.to_numeric(df["qty_requested"])
        df["qty_delivered"] = pd.to_numeric(df["qty_delivered"])
        return df

    def test_disruption_with_notice(self):
        orders = self._make_orders(0.30, 0.95)
        notes = [
            {"month": "2026-03", "commodity": "test",
             "source": "KEMSA", "title": "Supply disruption",
             "url": "https://example.org", "synthetic": True}
        ]
        result = _check_h7("2026-03", "test", orders, notes)
        assert result["web_notice_found"] is True
        assert result["county_fill_drop"] is not None
        assert result["county_fill_drop"] > 0

    def test_disruption_no_notice(self):
        orders = self._make_orders(0.30, 0.95)
        result = _check_h7("2026-03", "test", orders, [])
        assert result["web_notice_found"] is False

    def test_no_fill_drop(self):
        orders = self._make_orders(0.95, 0.95)
        result = _check_h7("2026-03", "test", orders, [])
        # fill_drop should be ~0
        assert result["county_fill_drop"] is not None
        assert result["county_fill_drop"] == pytest.approx(0.0, abs=0.02)


# ---------------------------------------------------------------------------
# Integration: full profile against known cases
# ---------------------------------------------------------------------------

class TestIntegrationKnownCases:
    """Run profile_stockout on known cases and check hypothesis signals.

    These do not test exact values (which may change with data regeneration)
    but assert that the detected hypotheses align with known ground truth.
    """

    @pytest.mark.parametrize("case_dir,facility_id,commodity,month,expected_true_hyp", [
        (
            "data/cases/normal/case_01",
            "FAC-011", "ORS sachet", "2026-03",
            "h4_demand_surge",
        ),
        (
            "data/cases/normal/case_06",
            "FAC-022", "iron-folate tab", "2026-03",
            "h1_late_order",
        ),
    ])
    def test_known_case(self, case_dir, facility_id, commodity, month,
                        expected_true_hyp):
        root = Path(__file__).parent.parent
        dataset = load_dataset(str(root / case_dir))
        profile = profile_stockout(dataset, facility_id, commodity, month)
        ce = profile["computed_evidence"]

        h = ce[expected_true_hyp]

        if expected_true_hyp == "h1_late_order":
            # Late order signal: either order was placed after cutoff, OR
            # delivery slipped past the expected month
            assert h.get("late") is True or h.get("delivery_slipped") is True, (
                f"Expected late order signal but got: {h}"
            )
        elif expected_true_hyp == "h5_record_error":
            # Record error: identity_holds=False means there's an error
            assert h.get("identity_holds") is False, (
                f"Expected record error but identity_holds={h.get('identity_holds')}"
            )
        else:
            flag_key = {
                "h2_supplier_underfill": "underfill",
                "h3_payment_arrears": "major_arrears",
                "h4_demand_surge": "surge",
                "h6_expiry": "high_wastage",
                "h7_national_disruption": "web_notice_found",
            }[expected_true_hyp]
            assert h.get(flag_key) is True, (
                f"Expected {expected_true_hyp} signal=True but got: {h}"
            )
