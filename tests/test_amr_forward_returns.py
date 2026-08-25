"""PV-GAP-2: Tests for forward return batch builder (final)."""

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.amr.evaluation_input_contract import (
    EvaluationInputContractError,
    ForwardReturnBatch,
)
from backend.amr.financial_timing import VersionedTradingCalendar
from backend.amr.forward_returns import (
    FinancialForwardReturnPolicy,
    build_financial_forward_return_batch,
    build_security_forward_return_batch,
)


class TestHappyPath:
    def test_single_horizon_1(self):
        panel = pd.DataFrame({"date": ["2016-01-04", "2016-01-05", "2016-01-06"], "code": ["A", "A", "A"], "close": [10.0, 11.0, 12.0]})
        b = build_security_forward_return_batch(panel, horizons=[1], return_set_id="r1", version="v1", source="t")
        df = b.get_frame()
        assert df["forward_return"].iloc[0] == pytest.approx(0.1)
        assert df["forward_return"].iloc[1] == pytest.approx(12 / 11 - 1)
        assert np.isnan(df["forward_return"].iloc[2])

    def test_horizon_5(self):
        panel = pd.DataFrame({"date": [f"2016-01-{d+4:02d}" for d in range(10)], "code": ["A"] * 10, "close": list(range(10, 20))})
        b = build_security_forward_return_batch(panel, horizons=[5], return_set_id="r1", version="v1", source="t")
        df = b.get_frame()
        assert df["forward_return"].iloc[0] == pytest.approx(15 / 10 - 1)
        assert df["forward_return"].iloc[4] == pytest.approx(19 / 14 - 1)
        assert np.isnan(df["forward_return"].iloc[5])

    def test_multi_horizon(self):
        panel = pd.DataFrame({"date": ["2016-01-04", "2016-01-05", "2016-01-06"], "code": ["A", "A", "A"], "close": [10.0, 11.0, 12.0]})
        b = build_security_forward_return_batch(panel, horizons=[1, 2], return_set_id="r1", version="v1", source="t")
        assert len(b.get_frame()) == 6

    def test_multi_code_isolation(self):
        panel = pd.DataFrame({"date": ["2016-01-04", "2016-01-04", "2016-01-05", "2016-01-05"], "code": ["A", "B", "A", "B"], "close": [10, 100, 11, 200]})
        b = build_security_forward_return_batch(panel, horizons=[1], return_set_id="r1", version="v1", source="t")
        df = b.get_frame()
        df_a = df[df["code"] == "A"]; df_b = df[df["code"] == "B"]
        assert df_a["forward_return"].iloc[0] == pytest.approx(0.1)
        assert df_b["forward_return"].iloc[0] == pytest.approx(1.0)

    def test_shuffled_input(self):
        panel = pd.DataFrame({"date": ["2016-01-05", "2016-01-04", "2016-01-06"], "code": ["A", "A", "A"], "close": [11, 10, 12]})
        b = build_security_forward_return_batch(panel, horizons=[1], return_set_id="r1", version="v1", source="t")
        assert b.get_frame()["forward_return"].iloc[0] == pytest.approx(0.1)

    def test_tail_nan(self):
        panel = pd.DataFrame({"date": ["2016-01-04", "2016-01-05", "2016-01-06"], "code": ["A", "A", "A"], "close": [10.0, 11.0, 12.0]})
        b = build_security_forward_return_batch(panel, horizons=[1], return_set_id="r1", version="v1", source="t")
        assert np.isnan(b.get_frame()[b.get_frame()["date"] == "2016-01-06"]["forward_return"].iloc[0])

    def test_missing_price_propagates(self):
        panel = pd.DataFrame({"date": ["2016-01-04", "2016-01-05", "2016-01-06"], "code": ["A", "A", "A"], "close": [10.0, np.nan, 12.0]})
        b = build_security_forward_return_batch(panel, horizons=[1], return_set_id="r1", version="v1", source="t")
        assert np.isnan(b.get_frame()["forward_return"].iloc[0])

    def test_intermediate_price_irrelevant(self):
        panel = pd.DataFrame({"date": ["2016-01-04", "2016-01-05", "2016-01-06"], "code": ["A", "A", "A"], "close": [10.0, 999.0, 12.0]})
        b = build_security_forward_return_batch(panel, horizons=[2], return_set_id="r1", version="v1", source="t")
        assert b.get_frame()["forward_return"].iloc[0] == pytest.approx(0.2)

    def test_output_columns_and_sort(self):
        panel = pd.DataFrame({"date": ["2016-01-04", "2016-01-05", "2016-01-06"], "code": ["A", "A", "A"], "close": [10.0, 11.0, 12.0]})
        b = build_security_forward_return_batch(panel, horizons=[1, 2], return_set_id="r1", version="v1", source="t")
        df = b.get_frame()
        assert list(df.columns) == ["date", "code", "horizon", "forward_return"]
        # strict sort: date asc, code asc, horizon asc
        expected = [
            ("2016-01-04", "A", 1), ("2016-01-04", "A", 2),
            ("2016-01-05", "A", 1), ("2016-01-05", "A", 2),
            ("2016-01-06", "A", 1), ("2016-01-06", "A", 2),
        ]
        actual = list(zip(df["date"], df["code"], df["horizon"]))
        assert actual == expected

    def test_input_not_mutated(self):
        panel = pd.DataFrame({"date": ["2016-01-04", "2016-01-05", "2016-01-06"], "code": ["A", "A", "A"], "close": [10.0, 11.0, 12.0]})
        orig = panel.copy()
        build_security_forward_return_batch(panel, horizons=[1], return_set_id="r1", version="v1", source="t")
        assert panel.equals(orig)

    def test_metadata_and_provenance(self):
        panel = pd.DataFrame({"date": ["2016-01-04", "2016-01-05", "2016-01-06"], "code": ["A", "A", "A"], "close": [10.0, 11.0, 12.0]})
        b = build_security_forward_return_batch(panel, horizons=[1], return_set_id="r1", version="v1", source="t")
        assert isinstance(b, ForwardReturnBatch)
        assert b.return_definition == "close_to_close_observation_horizon"
        p = b.provenance
        assert p["method_version"] == "1.0"
        assert p["price_col"] == "close"
        assert p["horizons"] == [1]
        assert "close[t+h]/close[t]" in p["horizon_semantics"]
        assert p["input_row_count"] == 3
        assert p["output_row_count"] == 3

    def test_alignment_integration(self):
        from backend.amr.evaluation_alignment import align_price_volume_bundle
        from backend.amr.evaluation_input_contract import (
            EvaluationInputBundle,
            FactorRecord,
            FactorType,
            PriceVolumeBatch,
            ValueScope,
        )
        panel = pd.DataFrame({"date": ["2016-01-04", "2016-01-05"] * 2, "code": ["A", "A", "B", "B"], "close": [10, 11, 100, 200]})
        b = build_security_forward_return_batch(panel, horizons=[1], return_set_id="r1", version="v1", source="t")
        rec = FactorRecord(factor_id="test", factor_name="x", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, frequency="day", version="v1", source="t")
        fv = PriceVolumeBatch(factor_id="test", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=pd.DataFrame({"date": ["2016-01-04", "2016-01-04"], "code": ["A", "B"], "factor_value": [0.5, -0.3], "horizon": "1"}))
        bundle = EvaluationInputBundle(factor_record=rec, factor_values=fv, forward_returns=b)
        _aligned, _, gate = align_price_volume_bundle(bundle, horizon="1")
        assert gate.overall_status.value != "blocked"

    def test_empty_panel(self):
        panel = pd.DataFrame(columns=["date", "code", "close"])
        b = build_security_forward_return_batch(panel, horizons=[1], return_set_id="r1", version="v1", source="t")
        df = b.get_frame()
        assert len(df) == 0
        assert list(df.columns) == ["date", "code", "horizon", "forward_return"]

    def test_mixed_date_formats_dedup(self):
        panel = pd.DataFrame({"date": ["2016-01-04", pd.Timestamp("2016-01-04")], "code": ["A", "A"], "close": [10.0, 11.0]})
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(panel, horizons=[1], return_set_id="r1", version="v1", source="t")
        assert e.value.code == "DUPLICATE_KEY"

    def test_future_price_isolation(self):
        # 4 dates, horizon=1: modifying t+2 price must not affect t's horizon-1 return
        panel = pd.DataFrame({"date": ["2016-01-04", "2016-01-05", "2016-01-06", "2016-01-07"], "code": ["A", "A", "A", "A"], "close": [10.0, 11.0, 12.0, 13.0]})
        b = build_security_forward_return_batch(panel, horizons=[1], return_set_id="r1", version="v1", source="t")
        df = b.get_frame()
        orig_0 = df["forward_return"].iloc[0]  # 11/10-1
        orig_2 = df["forward_return"].iloc[2]  # 13/12-1
        # Now modify t+2 price in a copy — not the original
        panel2 = panel.copy()
        panel2.loc[panel2["date"] == "2016-01-06", "close"] = 999.0
        b2 = build_security_forward_return_batch(panel2, horizons=[1], return_set_id="r2", version="v1", source="t")
        df2 = b2.get_frame()
        assert df2["forward_return"].iloc[0] == pytest.approx(orig_0)  # t=0 still uses t+1 which is unchanged
        assert df2["forward_return"].iloc[2] != pytest.approx(orig_2)  # t=2 now uses modified t+3

    def test_no_network_no_supabase_no_statsmodels(self):
        source_path = Path(__file__).resolve().parents[1] / "backend" / "amr" / "forward_returns.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])

        forbidden = {"requests", "httpx", "urllib", "socket", "supabase", "statsmodels"}
        assert imported_roots.isdisjoint(forbidden), (
            f"forbidden imports: {sorted(imported_roots & forbidden)}"
        )


class TestErrors:
    def test_missing_date(self):
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(pd.DataFrame({"code": ["A"], "close": [10]}), horizons=[1], return_set_id="r1", version="v1", source="t")
        assert e.value.code == "MISSING_REQUIRED_COLUMN"

    def test_missing_code(self):
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(pd.DataFrame({"date": ["x"], "close": [10]}), horizons=[1], return_set_id="r1", version="v1", source="t")
        assert e.value.code == "MISSING_REQUIRED_COLUMN"

    def test_missing_price_col(self):
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(pd.DataFrame({"date": ["x"], "code": ["A"]}), horizons=[1], return_set_id="r1", version="v1", source="t")
        assert e.value.code == "MISSING_REQUIRED_COLUMN"

    def test_invalid_date(self):
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(pd.DataFrame({"date": ["bad"], "code": ["A"], "close": [10.0]}), horizons=[1], return_set_id="r1", version="v1", source="t")
        assert e.value.code == "INVALID_DATE"

    def test_null_date(self):
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(pd.DataFrame({"date": [None], "code": ["A"], "close": [10.0]}), horizons=[1], return_set_id="r1", version="v1", source="t")
        assert "NULL" in e.value.code

    def test_null_code(self):
        with pytest.raises(EvaluationInputContractError):
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04"], "code": [None], "close": [10.0]}), horizons=[1], return_set_id="r1", version="v1", source="t")

    def test_empty_code(self):
        with pytest.raises(EvaluationInputContractError):
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04"], "code": [""], "close": [10.0]}), horizons=[1], return_set_id="r1", version="v1", source="t")

    def test_non_string_code(self):
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04"], "code": [123], "close": [10.0]}), horizons=[1], return_set_id="r1", version="v1", source="t")
        assert e.value.code == "INVALID_FIELD_TYPE"

    def test_duplicate_key(self):
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04", "2016-01-04"], "code": ["A", "A"], "close": [10.0, 11.0]}), horizons=[1], return_set_id="r1", version="v1", source="t")
        assert e.value.code == "DUPLICATE_KEY"

    def test_non_numeric_price(self):
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "close": ["abc"]}), horizons=[1], return_set_id="r1", version="v1", source="t")
        assert e.value.code == "NON_NUMERIC_VALUE"

    def test_infinite_price(self):
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "close": [float("inf")]}), horizons=[1], return_set_id="r1", version="v1", source="t")
        assert e.value.code == "INFINITE_VALUE"

    def test_neg_infinite_price(self):
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "close": [float("-inf")]}), horizons=[1], return_set_id="r1", version="v1", source="t")
        assert e.value.code == "INFINITE_VALUE"

    def test_zero_price(self):
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "close": [0.0]}), horizons=[1], return_set_id="r1", version="v1", source="t")
        assert e.value.code == "INVALID_PRICE"

    def test_negative_price(self):
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "close": [-1.0]}), horizons=[1], return_set_id="r1", version="v1", source="t")
        assert e.value.code == "INVALID_PRICE"

    def test_empty_horizons(self):
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "close": [10.0]}), horizons=[], return_set_id="r1", version="v1", source="t")
        assert e.value.code == "EMPTY_HORIZONS"

    def test_horizon_zero(self):
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "close": [10.0]}), horizons=[0], return_set_id="r1", version="v1", source="t")
        assert e.value.code == "INVALID_HORIZON"

    def test_horizon_negative(self):
        with pytest.raises(EvaluationInputContractError):
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "close": [10.0]}), horizons=[-1], return_set_id="r1", version="v1", source="t")

    def test_horizon_bool(self):
        with pytest.raises(EvaluationInputContractError):
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "close": [10.0]}), horizons=[True], return_set_id="r1", version="v1", source="t")

    def test_horizon_float(self):
        with pytest.raises(EvaluationInputContractError):
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "close": [10.0]}), horizons=[1.5], return_set_id="r1", version="v1", source="t")

    def test_horizon_string(self):
        with pytest.raises(EvaluationInputContractError):
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "close": [10.0]}), horizons=["1"], return_set_id="r1", version="v1", source="t")

    def test_duplicate_horizon(self):
        with pytest.raises(EvaluationInputContractError) as e:
            build_security_forward_return_batch(pd.DataFrame({"date": ["2016-01-04", "2016-01-05"], "code": ["A", "A"], "close": [10.0, 11.0]}), horizons=[1, 1], return_set_id="r1", version="v1", source="t")
        assert e.value.code == "DUPLICATE_HORIZON"


def _financial_calendar() -> VersionedTradingCalendar:
    dates = tuple(pd.bdate_range("2024-01-02", periods=30).strftime("%Y-%m-%d"))
    return VersionedTradingCalendar(
        trading_dates=dates,
        calendar_provider="RQData",
        calendar_scope="CN",
        calendar_version_or_snapshot_id="synthetic-rqdata-calendar-v1",
    )


def _financial_policy() -> FinancialForwardReturnPolicy:
    return FinancialForwardReturnPolicy(calendar=_financial_calendar())


def _financial_panel(codes=("A",)) -> pd.DataFrame:
    rows = []
    for code in codes:
        for index, date in enumerate(_financial_calendar().trading_dates):
            rows.append(
                {
                    "date": date,
                    "code": code,
                    "close": 100.0 + index,
                    "volume": 1000.0,
                    "is_tradable": True,
                    "is_suspended": False,
                }
            )
    return pd.DataFrame(rows)


def _formation(codes=("A",)) -> pd.DataFrame:
    return pd.DataFrame({"date": [_financial_calendar().trading_dates[0]] * len(codes), "code": list(codes)})


def _build_financial(panel: pd.DataFrame, formation: pd.DataFrame | None = None, delistings=None):
    return build_financial_forward_return_batch(
        panel,
        formation_universe=formation if formation is not None else _formation(),
        policy=_financial_policy(),
        return_set_id="FINANCIAL_20MKT_V1",
        version="v1",
        source="synthetic_contract_test",
        delistings=delistings,
    )


class TestFinancialForwardReturnContract:
    def test_fr_t01_normal_t_to_t_plus_20(self):
        result = _build_financial(_financial_panel())
        assert result.batch.get_frame().loc[0, "forward_return"] == pytest.approx(120.0 / 100.0 - 1.0)
        assert result.audit_frame.loc[0, "exit_date"] == _financial_calendar().trading_dates[20]

    def test_fr_t02_entry_suspended_is_nan_with_reason(self):
        panel = _financial_panel()
        panel.loc[0, "is_suspended"] = True
        result = _build_financial(panel)
        assert np.isnan(result.batch.get_frame().loc[0, "forward_return"])
        assert result.audit_frame.loc[0, "audit_reason"] == "ENTRY_SUSPENDED_OR_UNPRICED"

    def test_fr_t03_exit_suspended_is_nan_with_reason(self):
        panel = _financial_panel()
        panel.loc[20, "is_suspended"] = True
        result = _build_financial(panel)
        assert np.isnan(result.batch.get_frame().loc[0, "forward_return"])
        assert result.audit_frame.loc[0, "audit_reason"] == "EXIT_SUSPENDED_OR_UNPRICED"

    def test_fr_t04_mid_horizon_suspension_does_not_roll_or_block_valid_endpoints(self):
        panel = _financial_panel()
        panel.loc[10, "is_suspended"] = True
        panel.loc[10, "volume"] = 0.0
        result = _build_financial(panel)
        assert result.batch.get_frame().loc[0, "forward_return"] == pytest.approx(0.2)
        assert result.audit_frame.loc[0, "audit_reason"] == "OK"

    def test_fr_t05_missing_entry_price_is_nan(self):
        panel = _financial_panel()
        panel.loc[0, "close"] = np.nan
        result = _build_financial(panel)
        assert np.isnan(result.batch.get_frame().loc[0, "forward_return"])
        assert result.audit_frame.loc[0, "audit_reason"] == "ENTRY_PRICE_MISSING"

    def test_fr_t06_missing_exit_price_is_nan(self):
        panel = _financial_panel()
        panel.loc[20, "close"] = np.nan
        result = _build_financial(panel)
        assert np.isnan(result.batch.get_frame().loc[0, "forward_return"])
        assert result.audit_frame.loc[0, "audit_reason"] == "EXIT_PRICE_MISSING"

    def test_fr_t07_no_roll_forward_after_exit_suspension(self):
        panel = _financial_panel()
        panel.loc[20, ["is_suspended", "volume"]] = [True, 0.0]
        panel.loc[21, "close"] = 999.0
        result = _build_financial(panel)
        assert np.isnan(result.batch.get_frame().loc[0, "forward_return"])
        assert result.audit_frame.loc[0, "exit_date"] == _financial_calendar().trading_dates[20]

    def test_fr_t08_corporate_action_mapping_is_frozen_in_provenance(self):
        result = _build_financial(_financial_panel())
        provenance = result.batch.provenance
        assert provenance["adjustment_policy"] == "CONSISTENT_CORPORATE_ACTION_ADJUSTED_CLOSE"
        assert provenance["provider_adjustment_mode"] == "pre"
        assert "skip_suspended=True" in provenance["adapter_mapping"]

    def test_fr_t09_delisting_with_termination_value_uses_realized_value(self):
        dates = _financial_calendar().trading_dates
        delistings = pd.DataFrame({"code": ["A"], "delisting_date": [dates[10]], "termination_value": [80.0]})
        result = _build_financial(_financial_panel(), delistings=delistings)
        assert result.batch.get_frame().loc[0, "forward_return"] == pytest.approx(-0.2)
        assert result.audit_frame.loc[0, "audit_reason"] == "DELISTING_TERMINATION_VALUE_USED"
        assert result.summary["delisting_return_available_count"] == 1

    def test_fr_t10_delisting_without_termination_value_is_explicit_nan(self):
        dates = _financial_calendar().trading_dates
        delistings = pd.DataFrame({"code": ["A"], "delisting_date": [dates[10]], "termination_value": [np.nan]})
        result = _build_financial(_financial_panel(), delistings=delistings)
        assert np.isnan(result.batch.get_frame().loc[0, "forward_return"])
        assert result.audit_frame.loc[0, "audit_reason"] == "DELISTING_RETURN_UNAVAILABLE"
        assert result.summary["delisting_return_unavailable_count"] == 1

    def test_fr_t11_formation_universe_is_preserved_when_label_missing(self):
        result = _build_financial(_financial_panel(codes=("A",)), formation=_formation(codes=("A", "B")))
        frame = result.batch.get_frame()
        assert frame["code"].tolist() == ["A", "B"]
        assert np.isnan(frame.loc[frame["code"] == "B", "forward_return"].iloc[0])
        assert result.summary["formation_sample_count"] == 2
        assert result.summary["valid_return_count"] == 1

    def test_fr_t12_market_session_horizon_is_not_security_observation_rows(self):
        panel = _financial_panel().drop(index=10).reset_index(drop=True)
        result = _build_financial(panel)
        assert result.audit_frame.loc[0, "exit_date"] == _financial_calendar().trading_dates[20]
        assert result.batch.get_frame().loc[0, "forward_return"] == pytest.approx(0.2)
