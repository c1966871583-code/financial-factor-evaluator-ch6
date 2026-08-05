"""Configuration-only fixtures for FIN-P3-INFO-GAIN-01.

The fixture contains no factor observations, labels, metric values, member
baselines, or empirical information-gain results.
"""

from __future__ import annotations

from backend.amr.financial_p3_combinations import (
    get_fin24_combination_definitions,
)
from backend.amr.financial_p3_info_gain_contract import (
    CommonSampleContractReference,
    InfoGainEvaluationConfig,
    build_financial_p3_info_gain_contract,
    get_frozen_common_sample_references,
)


def accepted_definitions_reversed():
    return tuple(reversed(get_fin24_combination_definitions()))


def accepted_samples_reversed(
) -> tuple[CommonSampleContractReference, ...]:
    return tuple(reversed(get_frozen_common_sample_references()))


def make_contract(
    *,
    reverse_definitions: bool = False,
    reverse_samples: bool = False,
) -> InfoGainEvaluationConfig:
    definitions = (
        accepted_definitions_reversed()
        if reverse_definitions
        else get_fin24_combination_definitions()
    )
    samples = (
        accepted_samples_reversed()
        if reverse_samples
        else get_frozen_common_sample_references()
    )
    return build_financial_p3_info_gain_contract(
        combination_definitions=definitions,
        common_sample_references=samples,
    )
