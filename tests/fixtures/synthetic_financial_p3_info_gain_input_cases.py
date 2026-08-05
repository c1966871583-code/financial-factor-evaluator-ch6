"""Explicit frozen-row fixtures for INFO-GAIN-02A."""

from __future__ import annotations

import copy
from typing import Any, Mapping

import pandas as pd

from backend.amr.financial_p3_info_gain_contract import (
    INFO_GAIN_COMBO_ORDER,
    build_financial_p3_info_gain_contract,
)
from backend.amr.financial_p3_info_gain_inputs import (
    InfoGainCommonSampleInputBatch,
    InfoGainInputPreparationConfig,
)
from tests.fixtures.synthetic_financial_p3_combination_cases import (
    evaluation_dates,
    make_frame as make_source_frame,
)


_MEMBER_COLUMNS = {
    "BP": ("bp", "bp_effective_date"),
    "EBIT_EV": ("ebit_ev", "ebit_ev_effective_date"),
    "ROE": ("roe", "roe_effective_date"),
    "OCF_NP": ("ocf_np", "ocf_np_effective_date"),
    "SALES_GROWTH": ("sales_growth", "sales_growth_effective_date"),
    "PROFIT_GROWTH": ("profit_growth", "profit_growth_effective_date"),
    "ROA": ("roa", "roa_effective_date"),
    "OCF_SALES": ("ocf_sales", "ocf_sales_effective_date"),
    "ACCRUALS": ("accruals", "accruals_effective_date"),
}

_EXCLUDED_SECURITY_INDICES = {
    "VQ": {0, 1, 2, 3, 4, 12, 13, 14},
    "QG": {3, 4, 5, 6, 7, 12, 13, 14},
    "CASHQ": {4, 8, 9, 10, 11, 12, 13, 14},
}

_FORMULA_VERSIONS = {
    "BP": "FIN-MVP-BP-v1.0",
    "ROE": "FIN-MVP-ROE-v1.0",
    "OCF_NP": "FIN-MVP-OCFNP-v1.0",
}


def make_configuration(**changes: Any) -> InfoGainInputPreparationConfig:
    values = {
        "run_id": "SYNTHETIC-FIN-P3-INFO-GAIN-02A-01",
        "contract": build_financial_p3_info_gain_contract(),
    }
    values.update(changes)
    return InfoGainInputPreparationConfig(**values)


def make_batches(
    *,
    provenance: Mapping[str, Any] | None = None,
) -> tuple[InfoGainCommonSampleInputBatch, ...]:
    source = make_source_frame()
    contract = build_financial_p3_info_gain_contract()
    combo_by_id = {item.combo_id: item for item in contract.combination_references}
    sample_by_id = {item.combo_id: item for item in contract.common_sample_references}
    batches = []
    for combo_id in INFO_GAIN_COMBO_ORDER:
        combo = combo_by_id[combo_id]
        sample = sample_by_id[combo_id]
        accepted_ids = tuple(
            f"S{index:03d}"
            for index in range(58)
            if index not in _EXCLUDED_SECURITY_INDICES[combo_id]
        )
        accepted_keys = pd.MultiIndex.from_product(
            [evaluation_dates(), accepted_ids],
            names=["evaluation_date", "security_id"],
        )
        common = (
            source.set_index(["evaluation_date", "security_id"])
            .loc[accepted_keys]
            .reset_index()
        )
        manifest = common.loc[:, ["evaluation_date", "security_id"]].copy()
        manifest["eligible"] = True
        member_frames = []
        member_ids = tuple(item[0] for item in combo.member_directions)
        for member_id in member_ids:
            value_column, effective_column = _MEMBER_COLUMNS[member_id]
            member = common.loc[
                :,
                [
                    "evaluation_date",
                    "security_id",
                    effective_column,
                    value_column,
                    "control_effective_date",
                    "return_start_date",
                    "forward_return",
                    "size_control",
                    "industry_code",
                ],
            ].copy()
            member.insert(2, "member_factor_id", member_id)
            member = member.rename(
                columns={
                    effective_column: "factor_effective_date",
                    value_column: "factor_value",
                }
            )
            member_frames.append(member)
        batches.append(
            InfoGainCommonSampleInputBatch(
                dataset_id=f"synthetic-info-gain-02a-{combo_id.lower()}",
                version="v1",
                combo_id=combo_id,
                combo_definition_version=combo.combo_definition_version,
                common_sample_reference=sample.common_sample_reference,
                declared_common_sample_fingerprint=(
                    sample.common_sample_fingerprint
                ),
                _common_sample_manifest=manifest,
                _member_observations=pd.concat(
                    member_frames, ignore_index=True
                ),
                member_formula_versions={
                    member_id: _FORMULA_VERSIONS.get(
                        member_id, f"FIN-24-{member_id}-MEMBER-v1.0"
                    )
                    for member_id in member_ids
                },
                source_factor_run_references={
                    member_id: f"SYNTHETIC:{combo_id}:{member_id}"
                    for member_id in member_ids
                },
                track_input_references={
                    "M": {
                        "preparation_status": "ready",
                        "evaluation_contexts": ["M:20D"],
                        "label_references": [
                            "SYNTHETIC-FORWARD-RETURN-20D-v1"
                        ],
                        "evaluation_config_reference": (
                            "FIN-P3-COMMON-SAMPLE:M20:v1.0"
                        ),
                        "reason_code": None,
                    },
                    "F": {
                        "preparation_status": "not_run",
                        "evaluation_contexts": [],
                        "label_references": [],
                        "evaluation_config_reference": None,
                        "reason_code": "CONTEXT_NOT_FROZEN",
                    },
                    "R": {
                        "preparation_status": "not_run",
                        "evaluation_contexts": [],
                        "label_references": [],
                        "evaluation_config_reference": None,
                        "reason_code": "CONTEXT_NOT_FROZEN",
                    },
                },
                provenance=(
                    {
                        "synthetic_test_only": True,
                        "provider": "deterministic_fixture",
                        "sample_source": (
                            "accepted_FIN-P3-COMBOS_common_sample_keys"
                        ),
                        "sample_reconstructed": False,
                    }
                    if provenance is None
                    else copy.deepcopy(dict(provenance))
                ),
            )
        )
    return tuple(batches)
