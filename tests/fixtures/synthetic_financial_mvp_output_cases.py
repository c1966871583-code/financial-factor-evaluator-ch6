"""Synthetic-only inputs for FIN-MVP-OUTPUT."""

from backend.amr.financial_mvp_output import FinancialMVPOutputConfig
from backend.amr.financial_mvp_robustness import (
    evaluate_financial_mvp_robustness,
)
from tests.fixtures.synthetic_financial_mvp_robustness_cases import (
    make_constant_bp_robustness_case,
    make_robustness_case,
)


def make_output_case():
    mvp, prep, returns, m_result, robust_config = (
        make_robustness_case()
    )
    robustness = evaluate_financial_mvp_robustness(
        mvp,
        prep,
        returns,
        m_result,
        configuration=robust_config,
    )
    assert robustness.robustness_audit.gate_status == "ready"
    output_config = FinancialMVPOutputConfig(
        m_evaluation_configuration=(
            robust_config.m_evaluation_configuration
        ),
        robustness_configuration=robust_config,
    )
    return (
        mvp,
        prep,
        returns,
        m_result,
        robustness,
        output_config,
    )


def make_insufficient_bp_output_case():
    mvp, prep, returns, m_result, robust_config = (
        make_constant_bp_robustness_case()
    )
    robustness = evaluate_financial_mvp_robustness(
        mvp,
        prep,
        returns,
        m_result,
        configuration=robust_config,
    )
    assert robustness.robustness_audit.gate_status == "ready"
    output_config = FinancialMVPOutputConfig(
        m_evaluation_configuration=(
            robust_config.m_evaluation_configuration
        ),
        robustness_configuration=robust_config,
    )
    return (
        mvp,
        prep,
        returns,
        m_result,
        robustness,
        output_config,
    )
