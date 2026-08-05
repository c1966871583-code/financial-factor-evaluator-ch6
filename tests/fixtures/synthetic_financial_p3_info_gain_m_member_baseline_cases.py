"""Deterministic accepted-input fixture for INFO-GAIN-02B."""

from __future__ import annotations

from backend.amr.financial_p3_info_gain_inputs import (
    prepare_financial_p3_info_gain_inputs,
)
from backend.amr.financial_p3_info_gain_m_member_baselines import (
    MMemberBaselineConfig,
)
from tests.fixtures.synthetic_financial_p3_info_gain_input_cases import (
    make_batches,
    make_configuration as make_02a_configuration,
)


def make_prepared_inputs():
    return prepare_financial_p3_info_gain_inputs(
        make_batches(),
        configuration=make_02a_configuration(),
    )


def make_configuration(**changes):
    values = {"run_id": "SYNTHETIC-FIN-P3-INFO-GAIN-02B-01"}
    values.update(changes)
    return MMemberBaselineConfig(**values)
