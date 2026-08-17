"""P0-3A-STEP1A: Tests for evaluation_input_contract (corrected)."""

import pandas as pd
import pytest

from backend.amr.evaluation_input_contract import (
    EvaluationInputBundle,
    EvaluationInputContractError,
    FactorRecord,
    FactorType,
    FinancialBatch,
    ForwardReturnBatch,
    MacroBatch,
    PriceVolumeBatch,
    ReadinessStage,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
    ValueScope,
)


# ===================================================================
# Enums
# ===================================================================


class TestEnums:
    def test_three_factor_types(self):
        assert FactorType.PRICE_VOLUME.value == "price_volume"
        assert FactorType.FINANCIAL.value == "financial"
        assert FactorType.MACRO.value == "macro"

    def test_invalid_fails(self):
        with pytest.raises(ValueError):
            FactorType("invalid")

    def test_value_scopes(self):
        assert ValueScope.SECURITY_LEVEL.value == "security_level"
        assert ValueScope.MARKET_LEVEL.value == "market_level"


# ===================================================================
# FactorRecord
# ===================================================================


@pytest.fixture
def alpha13():
    return FactorRecord(factor_id="WQ101:alpha13", factor_name="WorldQuant_alpha013",
                        factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL,
                        factor_family="alpha101", library="WQ101", category="\u91cf\u4ef7\u56e0\u5b50",
                        definition="Alpha13: rank(close) cov rank(volume)", frequency="day",
                        universe="csi800", version="v1", source="supabase")


class TestFactorRecord:
    def test_basic(self, alpha13):
        assert alpha13.factor_id == "WQ101:alpha13"

    def test_id_non_empty(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            FactorRecord(factor_id="  ", factor_name="x", factor_type=FactorType.MACRO,
                         value_scope=ValueScope.MARKET_LEVEL, frequency="m", version="v1", source="t")
        assert exc.value.code == "MISSING_FACTOR_ID"

    def test_id_not_auto_generated(self):
        r = FactorRecord(factor_id="upstream", factor_name="x", factor_type=FactorType.MACRO,
                         value_scope=ValueScope.MARKET_LEVEL, frequency="m", version="v1", source="t")
        assert r.factor_id == "upstream"

    def test_category_independent(self):
        r = FactorRecord(factor_id="a", factor_name="x", factor_type=FactorType.PRICE_VOLUME,
                         value_scope=ValueScope.SECURITY_LEVEL, frequency="d", version="v1", source="t",
                         category="custom")
        assert r.category == "custom"

    def test_price_volume_must_sec(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            FactorRecord(factor_id="a", factor_name="x", factor_type=FactorType.PRICE_VOLUME,
                         value_scope=ValueScope.MARKET_LEVEL, frequency="d", version="v1", source="t")
        assert exc.value.code == "SCOPE_MISMATCH"

    def test_financial_must_sec(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            FactorRecord(factor_id="a", factor_name="x", factor_type=FactorType.FINANCIAL,
                         value_scope=ValueScope.MARKET_LEVEL, frequency="q", version="v1", source="t")
        assert exc.value.code == "SCOPE_MISMATCH"

    def test_macro_both(self):
        r1 = FactorRecord(factor_id="m1", factor_name="x", factor_type=FactorType.MACRO,
                          value_scope=ValueScope.MARKET_LEVEL, frequency="m", version="v1", source="t")
        r2 = FactorRecord(factor_id="m2", factor_name="x", factor_type=FactorType.MACRO,
                          value_scope=ValueScope.SECURITY_LEVEL, frequency="m", version="v1", source="t")
        assert r1.value_scope == ValueScope.MARKET_LEVEL
        assert r2.value_scope == ValueScope.SECURITY_LEVEL

    def test_meta_defensive(self):
        md = {"k": "v"}
        r = FactorRecord(factor_id="a", factor_name="x", factor_type=FactorType.MACRO,
                         value_scope=ValueScope.MARKET_LEVEL, frequency="m", version="v1", source="t",
                         metadata=md)
        md["k"] = "mut"
        assert r.metadata["k"] == "v"

    def test_frozen(self):
        r = FactorRecord(factor_id="a", factor_name="x", factor_type=FactorType.MACRO,
                         value_scope=ValueScope.MARKET_LEVEL, frequency="m", version="v1", source="t")
        with pytest.raises(Exception):
            r.factor_id = "hacked"  # type: ignore[misc]


# ===================================================================
# PriceVolumeBatch
# ===================================================================


def _pv(**kw):
    d = {"date": ["2016-01-04", "2016-01-05"], "code": ["A", "A"], "factor_value": [-0.5, 0.3]}
    d.update(kw)
    return pd.DataFrame(d)


class TestPV:
    def test_valid(self):
        b = PriceVolumeBatch(factor_id="a", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv())
        assert b.get_frame().shape == (2, 3)

    def test_missing_col(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            PriceVolumeBatch(factor_id="a", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=pd.DataFrame({"date": ["x"], "factor_value": [0.5]}))
        assert exc.value.code == "MISSING_REQUIRED_COLUMN"

    def test_dup_key(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            PriceVolumeBatch(factor_id="a", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv(date=["2016-01-04", "2016-01-04"]))
        assert exc.value.code == "DUPLICATE_KEY"

    def test_inf(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            PriceVolumeBatch(factor_id="a", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv(factor_value=[float("inf"), 0.3]))
        assert exc.value.code == "INFINITE_VALUE"

    def test_null_key(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            PriceVolumeBatch(factor_id="a", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv(date=["2016-01-04", None]))
        assert exc.value.code == "NULL_KEY"

    def test_illegal_date(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            PriceVolumeBatch(factor_id="a", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv(date=["not-a-date", "2016-01-05"]))
        assert exc.value.code == "INVALID_DATE"

    def test_null_date(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            PriceVolumeBatch(factor_id="a", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv(date=[None, "2016-01-05"]))
        assert exc.value.code == "NULL_KEY"

    def test_non_numeric_fv(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            PriceVolumeBatch(factor_id="a", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv(factor_value=["abc", 0.3]))
        assert exc.value.code == "NON_NUMERIC_VALUE"

    def test_wrong_ft(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            PriceVolumeBatch(factor_id="a", factor_type=FactorType.MACRO, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv())
        assert exc.value.code == "FACTOR_TYPE_MISMATCH"

    # -- DataFrame defence --
    def test_get_frame_is_copy(self):
        b = PriceVolumeBatch(factor_id="a", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv())
        df = b.get_frame()
        df.iloc[0, 2] = 999.0
        assert b.get_frame().iloc[0, 2] != 999.0

    def test_orig_mutate_no_affect(self):
        df = _pv()
        b = PriceVolumeBatch(factor_id="a", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=df)
        df.iloc[0, 2] = 999.0
        assert b.get_frame().iloc[0, 2] != 999.0

    def test_no_public_frame_access(self):
        b = PriceVolumeBatch(factor_id="a", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv())
        assert not hasattr(b, "frame")


# ===================================================================
# FinancialBatch
# ===================================================================


class TestFinancial:
    def _f(self, **kw):
        d = {"code": ["A", "B"], "report_period": ["2023-03-31", "2023-03-31"],
             "publish_date": ["2023-04-28", "2023-04-28"], "effective_date": ["2023-04-29", "2023-04-29"],
             "factor_value": [0.5, -0.3]}
        d.update(kw)
        return pd.DataFrame(d)

    def test_valid(self):
        b = FinancialBatch(factor_id="a", factor_type=FactorType.FINANCIAL, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=self._f())
        assert b.get_frame().shape == (2, 5)

    def test_rp_gt_pub(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            FinancialBatch(factor_id="a", factor_type=FactorType.FINANCIAL, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=self._f(report_period=["2023-05-01", "2023-03-31"]))
        assert exc.value.code == "INVALID_DATE_ORDER"

    def test_pub_gt_eff(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            FinancialBatch(factor_id="a", factor_type=FactorType.FINANCIAL, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=self._f(publish_date=["2023-04-30", "2023-04-30"], effective_date=["2023-04-29", "2023-04-29"]))
        assert exc.value.code == "INVALID_DATE_ORDER"

    def test_same_day_publish_effective_rejected(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            FinancialBatch(factor_id="a", factor_type=FactorType.FINANCIAL, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=self._f(effective_date=["2023-04-28", "2023-04-28"]))
        assert exc.value.code == "INVALID_DATE_ORDER"

    def test_missing_publish_date_rejected(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            FinancialBatch(factor_id="a", factor_type=FactorType.FINANCIAL, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=self._f(publish_date=[None, "2023-04-28"]))
        assert exc.value.code == "NULL_KEY"

    def test_dup(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            FinancialBatch(factor_id="a", factor_type=FactorType.FINANCIAL, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=self._f(code=["A", "A"], effective_date=["2023-04-29", "2023-04-29"]))
        assert exc.value.code == "DUPLICATE_KEY"

    def test_missing_eff(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            FinancialBatch(factor_id="a", factor_type=FactorType.FINANCIAL, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=pd.DataFrame({"code": ["A"], "report_period": ["x"], "publish_date": ["x"], "factor_value": [0.5]}))
        assert exc.value.code == "MISSING_REQUIRED_COLUMN"


# ===================================================================
# MacroBatch
# ===================================================================


class TestMacro:
    def _mkt(self, **kw):
        d = {"region_or_market": ["CN"], "observation_period": ["2023-01-01"], "release_date": ["2023-01-31"], "effective_date": ["2023-02-01"], "factor_value": [50.0]}
        d.update(kw)
        return pd.DataFrame(d)

    def _sec(self, **kw):
        d = {"code": ["A", "B"], "region_or_market": ["CN", "CN"], "observation_period": ["2023-01-01", "2023-01-01"], "release_date": ["2023-01-31", "2023-01-31"], "effective_date": ["2023-02-01", "2023-02-01"], "factor_value": [50.0, 50.0]}
        d.update(kw)
        return pd.DataFrame(d)

    def test_mkt_valid(self):
        b = MacroBatch(factor_id="a", factor_type=FactorType.MACRO, value_scope=ValueScope.MARKET_LEVEL, version="v1", source="t", _frame=self._mkt())
        assert b.get_frame().shape == (1, 5)

    def test_sec_valid(self):
        b = MacroBatch(factor_id="a", factor_type=FactorType.MACRO, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=self._sec())
        assert b.get_frame().shape == (2, 6)

    def test_release_gt_eff(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            MacroBatch(factor_id="a", factor_type=FactorType.MACRO, value_scope=ValueScope.MARKET_LEVEL, version="v1", source="t", _frame=self._mkt(release_date=["2023-02-15"], effective_date=["2023-02-01"]))
        assert exc.value.code == "INVALID_DATE_ORDER"

    def test_sec_missing_code(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            MacroBatch(factor_id="a", factor_type=FactorType.MACRO, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=self._mkt())
        assert exc.value.code == "MISSING_REQUIRED_COLUMN"

    def test_mkt_with_code_fails(self):
        with pytest.raises(EvaluationInputContractError) as exc:
            MacroBatch(factor_id="a", factor_type=FactorType.MACRO, value_scope=ValueScope.MARKET_LEVEL, version="v1", source="t", _frame=self._sec())
        assert exc.value.code == "SCOPE_MISMATCH"


# ===================================================================
# ForwardReturnBatch
# ===================================================================


class TestFwdReturn:
    def test_sec_valid(self):
        df = pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "horizon": [1], "forward_return": [0.01]})
        b = ForwardReturnBatch(return_set_id="r1", value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", return_definition="d", _frame=df)
        assert b.return_set_id == "r1"

    def test_mkt_valid(self):
        df = pd.DataFrame({"date": ["2023-01-01"], "region_or_market": ["CN"], "horizon": [1], "forward_return": [0.01]})
        b = ForwardReturnBatch(return_set_id="r1", value_scope=ValueScope.MARKET_LEVEL, version="v1", source="t", return_definition="d", _frame=df)
        assert b.value_scope == ValueScope.MARKET_LEVEL

    def test_illegal_date(self):
        df = pd.DataFrame({"date": ["bad"], "code": ["A"], "horizon": [1], "forward_return": [0.01]})
        with pytest.raises(EvaluationInputContractError) as exc:
            ForwardReturnBatch(return_set_id="r1", value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", return_definition="d", _frame=df)
        assert exc.value.code == "INVALID_DATE"

    def test_null_date(self):
        df = pd.DataFrame({"date": [None], "code": ["A"], "horizon": [1], "forward_return": [0.01]})
        with pytest.raises(EvaluationInputContractError) as exc:
            ForwardReturnBatch(return_set_id="r1", value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", return_definition="d", _frame=df)
        assert exc.value.code == "NULL_KEY"

    def test_non_numeric_fr(self):
        df = pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "horizon": [1], "forward_return": ["abc"]})
        with pytest.raises(EvaluationInputContractError) as exc:
            ForwardReturnBatch(return_set_id="r1", value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", return_definition="d", _frame=df)
        assert exc.value.code == "NON_NUMERIC_VALUE"

    def test_dup(self):
        df = pd.DataFrame({"date": ["2016-01-04", "2016-01-04"], "code": ["A", "A"], "horizon": [1, 1], "forward_return": [0.01, 0.02]})
        with pytest.raises(EvaluationInputContractError) as exc:
            ForwardReturnBatch(return_set_id="r1", value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", return_definition="d", _frame=df)
        assert exc.value.code == "DUPLICATE_KEY"


# ===================================================================
# Validation
# ===================================================================


class TestValidation:
    def test_issue_code(self):
        vi = ValidationIssue(code="MISSING_COL", severity=ValidationSeverity.ERROR, message="x", field_name="code")
        assert vi.code == "MISSING_COL"

    def test_valid_no_err(self):
        assert ValidationReport(valid=True).valid

    def test_invalid_with_err(self):
        assert not ValidationReport(valid=False, errors=[ValidationIssue(code="E", severity=ValidationSeverity.ERROR, message="x")]).valid

    def test_valid_false_no_err_raises(self):
        with pytest.raises(ValueError):
            ValidationReport(valid=False)

    def test_valid_true_with_err_raises(self):
        with pytest.raises(ValueError):
            ValidationReport(valid=True, errors=[ValidationIssue(code="E", severity=ValidationSeverity.ERROR, message="x")])


# ===================================================================
# EvaluationInputBundle
# ===================================================================


class TestBundle:
    def test_valid(self, alpha13):
        fv = PriceVolumeBatch(factor_id="WQ101:alpha13", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv())
        b = EvaluationInputBundle(factor_record=alpha13, factor_values=fv)
        assert b.factor_record.factor_id == "WQ101:alpha13"

    def test_factor_id_mismatch(self, alpha13):
        fv = PriceVolumeBatch(factor_id="OTHER", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv())
        with pytest.raises(EvaluationInputContractError) as exc:
            EvaluationInputBundle(factor_record=alpha13, factor_values=fv)
        assert exc.value.code == "FACTOR_ID_MISMATCH"

    def test_version_mismatch(self, alpha13):
        fv = PriceVolumeBatch(factor_id="WQ101:alpha13", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v2", source="t", _frame=_pv())
        with pytest.raises(EvaluationInputContractError) as exc:
            EvaluationInputBundle(factor_record=alpha13, factor_values=fv)
        assert exc.value.code == "FACTOR_VERSION_MISMATCH"

    def test_sec_factor_mkt_returns(self, alpha13):
        fv = PriceVolumeBatch(factor_id="WQ101:alpha13", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv())
        fr = ForwardReturnBatch(return_set_id="r1", value_scope=ValueScope.MARKET_LEVEL, version="v1", source="t", return_definition="d", _frame=pd.DataFrame({"date": ["2016-01-04"], "region_or_market": ["CN"], "horizon": [1], "forward_return": [0.01]}))
        with pytest.raises(EvaluationInputContractError) as exc:
            EvaluationInputBundle(factor_record=alpha13, factor_values=fv, forward_returns=fr)
        assert exc.value.code == "SCOPE_MISMATCH"

    def test_mkt_factor_sec_returns(self):
        r = FactorRecord(factor_id="m1", factor_name="x", factor_type=FactorType.MACRO, value_scope=ValueScope.MARKET_LEVEL, frequency="m", version="v1", source="t")
        fv = MacroBatch(factor_id="m1", factor_type=FactorType.MACRO, value_scope=ValueScope.MARKET_LEVEL, version="v1", source="t", _frame=pd.DataFrame({"region_or_market": ["CN"], "observation_period": ["2023-01-01"], "release_date": ["2023-01-31"], "effective_date": ["2023-02-01"], "factor_value": [50.0]}))
        fr = ForwardReturnBatch(return_set_id="r1", value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", return_definition="d", _frame=pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "horizon": [1], "forward_return": [0.01]}))
        with pytest.raises(EvaluationInputContractError) as exc:
            EvaluationInputBundle(factor_record=r, factor_values=fv, forward_returns=fr)
        assert exc.value.code == "SCOPE_MISMATCH"

    def test_universe_mismatch(self, alpha13):
        r2 = FactorRecord(factor_id="WQ101:alpha13", factor_name="x", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, frequency="d", version="v1", source="t", universe="csi300")
        fv = PriceVolumeBatch(factor_id="WQ101:alpha13", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv(), universe="csi300")
        fr = ForwardReturnBatch(return_set_id="r1", value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", return_definition="d", _frame=pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "horizon": [1], "forward_return": [0.01]}), universe="csi800")
        with pytest.raises(EvaluationInputContractError) as exc:
            EvaluationInputBundle(factor_record=r2, factor_values=fv, forward_returns=fr)
        assert exc.value.code == "UNIVERSE_MISMATCH"

    # -- Readiness --
    def test_missing_fwd_no_eff_ready(self, alpha13):
        fv = PriceVolumeBatch(factor_id="WQ101:alpha13", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv())
        b = EvaluationInputBundle(factor_record=alpha13, factor_values=fv)
        assert ReadinessStage.EFFECTIVENESS_READY not in b.compute_readiness()

    def test_with_fwd_eff_ready(self, alpha13):
        fv = PriceVolumeBatch(factor_id="WQ101:alpha13", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv())
        fr = ForwardReturnBatch(return_set_id="r1", value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", return_definition="d", _frame=pd.DataFrame({"date": ["2016-01-04"], "code": ["A"], "horizon": [1], "forward_return": [0.01]}))
        b = EvaluationInputBundle(factor_record=alpha13, factor_values=fv, forward_returns=fr)
        assert ReadinessStage.EFFECTIVENESS_READY in b.compute_readiness()

    def test_incompat_ret_no_eff_ready(self, alpha13):
        fv = PriceVolumeBatch(factor_id="WQ101:alpha13", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv())
        fr = ForwardReturnBatch(return_set_id="r1", value_scope=ValueScope.MARKET_LEVEL, version="v1", source="t", return_definition="d", _frame=pd.DataFrame({"date": ["2016-01-04"], "region_or_market": ["CN"], "horizon": [1], "forward_return": [0.01]}))
        with pytest.raises(EvaluationInputContractError):
            EvaluationInputBundle(factor_record=alpha13, factor_values=fv, forward_returns=fr)

    def test_mkt_no_eff_ready(self):
        r = FactorRecord(factor_id="m1", factor_name="x", factor_type=FactorType.MACRO, value_scope=ValueScope.MARKET_LEVEL, frequency="m", version="v1", source="t")
        fv = MacroBatch(factor_id="m1", factor_type=FactorType.MACRO, value_scope=ValueScope.MARKET_LEVEL, version="v1", source="t", _frame=pd.DataFrame({"region_or_market": ["CN"], "observation_period": ["2023-01-01"], "release_date": ["2023-01-31"], "effective_date": ["2023-02-01"], "factor_value": [50.0]}))
        b = EvaluationInputBundle(factor_record=r, factor_values=fv)
        assert ReadinessStage.EFFECTIVENESS_READY not in b.compute_readiness()

    def test_no_def_no_dedup_ready(self):
        r = FactorRecord(factor_id="a", factor_name="x", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, frequency="d", version="v1", source="t")
        fv = PriceVolumeBatch(factor_id="a", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv())
        b = EvaluationInputBundle(factor_record=r, factor_values=fv)
        assert ReadinessStage.DEFINITION_DEDUP_READY not in b.compute_readiness()

    def test_with_def_dedup_ready(self, alpha13):
        fv = PriceVolumeBatch(factor_id="WQ101:alpha13", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv())
        b = EvaluationInputBundle(factor_record=alpha13, factor_values=fv)
        assert ReadinessStage.DEFINITION_DEDUP_READY in b.compute_readiness()

    def test_empty_def_no_dedup_ready(self):
        r = FactorRecord(factor_id="a", factor_name="x", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, frequency="d", version="v1", source="t", definition="   ")
        fv = PriceVolumeBatch(factor_id="a", factor_type=FactorType.PRICE_VOLUME, value_scope=ValueScope.SECURITY_LEVEL, version="v1", source="t", _frame=_pv())
        b = EvaluationInputBundle(factor_record=r, factor_values=fv)
        assert ReadinessStage.DEFINITION_DEDUP_READY not in b.compute_readiness()
