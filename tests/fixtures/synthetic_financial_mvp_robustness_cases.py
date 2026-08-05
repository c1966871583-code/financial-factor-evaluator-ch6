"""Synthetic-only cases for FIN-MVP-ROBUST."""

from __future__ import annotations

import hashlib

from backend.amr.financial_mvp_m_evaluation import (
    FinancialMVPMEvaluationConfig,
    evaluate_financial_mvp_m,
)
from backend.amr.financial_mvp_robustness import (
    FinancialMVPRobustnessConfig,
)
from backend.amr.financial_preprocessing import (
    FinancialPreprocessingConfig,
    prepare_financial_formula_inputs,
)
from tests.fixtures.synthetic_financial_mvp_m_evaluation_cases import (
    EVALUATION_DATES,
    make_forward_returns,
    make_golden_case,
    make_mvp_result,
)
from tests.fixtures.synthetic_financial_preprocessing_cases import (
    make_preprocessing_record,
)


def make_m_configuration() -> FinancialMVPMEvaluationConfig:
    return FinancialMVPMEvaluationConfig(
        evaluation_dates=EVALUATION_DATES,
        evaluation_calendar_reference=(
            "synthetic-calendar://robustness-month-end-2024"
        ),
        evaluation_calendar_version="synthetic-robustness-v1",
        hac_max_lag=1,
    )


def make_robustness_configuration() -> FinancialMVPRobustnessConfig:
    return FinancialMVPRobustnessConfig(
        m_evaluation_configuration=make_m_configuration()
    )


def make_robustness_case():
    mvp, preprocessing, returns = make_golden_case()
    m_configuration = make_m_configuration()
    m_result = evaluate_financial_mvp_m(
        mvp,
        preprocessing,
        returns,
        configuration=m_configuration,
    )
    assert m_result.evaluation_audit.gate_status == "ready"
    return (
        mvp,
        preprocessing,
        returns,
        m_result,
        FinancialMVPRobustnessConfig(m_configuration),
    )


def make_outlier_robustness_case():
    preprocessing = _make_custom_preprocessing(outlier=True)
    mvp = make_mvp_result(preprocessing)
    returns = make_forward_returns()
    m_configuration = make_m_configuration()
    m_result = evaluate_financial_mvp_m(
        mvp,
        preprocessing,
        returns,
        configuration=m_configuration,
    )
    assert m_result.evaluation_audit.gate_status == "ready"
    assert any(
        item.was_winsorized
        for item in preprocessing.prepared_inputs
    )
    return (
        mvp,
        preprocessing,
        returns,
        m_result,
        FinancialMVPRobustnessConfig(m_configuration),
    )


def make_constant_bp_robustness_case():
    preprocessing = _make_custom_preprocessing(constant_bp=True)
    mvp = make_mvp_result(preprocessing)
    returns = make_forward_returns()
    m_configuration = make_m_configuration()
    m_result = evaluate_financial_mvp_m(
        mvp,
        preprocessing,
        returns,
        configuration=m_configuration,
    )
    assert m_result.evaluation_audit.gate_status == "ready"
    return (
        mvp,
        preprocessing,
        returns,
        m_result,
        FinancialMVPRobustnessConfig(m_configuration),
    )


def _make_custom_preprocessing(
    *,
    outlier: bool = False,
    constant_bp: bool = False,
):
    records = []
    for evaluation_date in EVALUATION_DATES:
        for index in range(1, 31):
            code = f"SYNME{index:04d}"
            net_profit = 10.0 + index
            parent_equity = (
                100.0
                if constant_bp
                else 100.0 + index
            )
            if outlier and index == 30:
                net_profit = 1000.0
                parent_equity = 1000.0
            record = make_preprocessing_record(
                code=code,
                evaluation_date=evaluation_date,
                parent_net_profit_ttm=net_profit,
                operating_cash_flow_ttm=net_profit * (
                    0.50 + index / 30.0
                ),
                parent_equity=parent_equity,
                prior_year_same_period_parent_equity=parent_equity,
                market_cap=200.0,
            )
            record["source_snapshot_fingerprint"] = hashlib.sha256(
                f"robustness-snapshot-{code}".encode("utf-8")
            ).hexdigest()
            records.append(record)
    result = prepare_financial_formula_inputs(
        records,
        configuration=FinancialPreprocessingConfig(
            minimum_cross_section_size=30
        ),
    )
    assert result.preprocessing_audit.gate_status == "ready"
    return result
