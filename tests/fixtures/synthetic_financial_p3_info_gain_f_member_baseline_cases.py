"""Deterministic accepted-input fixture for INFO-GAIN-02C."""

from backend.amr.financial_p3_info_gain_f_member_baselines import FMemberBaselineConfig
from backend.amr.financial_p3_info_gain_inputs import prepare_financial_p3_info_gain_inputs
from tests.fixtures.synthetic_financial_p3_info_gain_input_cases import (
    make_batches,
    make_configuration as make_02a_configuration,
)


def make_prepared_inputs():
    return prepare_financial_p3_info_gain_inputs(make_batches(), configuration=make_02a_configuration())


def make_configuration(**changes):
    values = {"run_id": "SYNTHETIC-FIN-P3-INFO-GAIN-02C-01"}
    values.update(changes)
    return FMemberBaselineConfig(**values)
