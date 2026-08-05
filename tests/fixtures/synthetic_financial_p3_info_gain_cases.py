"""Deterministic FIN-25 information-gain evaluation cases."""

from __future__ import annotations

from backend.amr.financial_p3_combinations import (
    evaluate_financial_p3_combinations,
)
from backend.amr.financial_p3_common_sample_member_baselines import (
    evaluate_common_sample_member_baselines,
)
from backend.amr.financial_p3_info_gain import FinancialP3InfoGainRunConfig
from backend.amr.financial_p3_info_gain_contract import (
    build_financial_p3_info_gain_contract,
)
from tests.fixtures.synthetic_financial_p3_combination_cases import (
    make_batch as make_combination_batch,
    make_configuration as make_combination_configuration,
)
from tests.fixtures.synthetic_financial_p3_common_sample_member_baseline_cases import (
    make_batches as make_member_batches,
    make_configuration as make_member_configuration,
)


def make_inputs():
    combinations = evaluate_financial_p3_combinations(
        make_combination_batch(), configuration=make_combination_configuration()
    )
    member_baselines = evaluate_common_sample_member_baselines(
        make_member_batches(), configuration=make_member_configuration()
    )
    return combinations, member_baselines


def make_configuration(**changes):
    values = {
        "run_id": "SYNTHETIC-FIN-P3-INFO-GAIN-01",
        "contract": build_financial_p3_info_gain_contract(),
    }
    values.update(changes)
    return FinancialP3InfoGainRunConfig(**values)
