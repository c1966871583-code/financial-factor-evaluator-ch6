"""Deterministic INFO-GAIN-02 common-sample member-baseline cases."""

from __future__ import annotations

import copy
from typing import Any, Mapping

import numpy as np
import pandas as pd

from backend.amr.financial_p3_common_sample_member_baselines import (
    CommonSampleMemberBaselineBatch,
    CommonSampleMemberBaselineConfig,
)
from backend.amr.financial_p3_info_gain_contract import (
    INFO_GAIN_COMBO_ORDER,
    build_financial_p3_info_gain_contract,
)
from tests.fixtures.synthetic_financial_p3_combination_cases import (
    make_frame as make_combo_frame,
    make_manifest as make_combo_manifest,
)


EXECUTION_TIMESTAMP = "2026-08-03T13:00:00+08:00"

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

_FORMULA_VERSIONS = {
    "BP": "FIN-MVP-BP-v1.0",
    "ROE": "FIN-MVP-ROE-v1.0",
    "OCF_NP": "FIN-MVP-OCFNP-v1.0",
}


def make_configuration(**changes: Any) -> CommonSampleMemberBaselineConfig:
    values: dict[str, Any] = {
        "run_id": "SYNTHETIC-FIN-P3-INFO-GAIN-02-01",
        "execution_timestamp": EXECUTION_TIMESTAMP,
        "evaluation_config_reference": "FIN-P3-COMMON-SAMPLE:M20:v1.0",
        "info_gain_contract": build_financial_p3_info_gain_contract(),
    }
    values.update(changes)
    return CommonSampleMemberBaselineConfig(**values)


def make_batches(
    *,
    frame: pd.DataFrame | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> tuple[CommonSampleMemberBaselineBatch, ...]:
    source = make_combo_frame() if frame is None else frame.copy(deep=True)
    independent_manifest = make_combo_manifest()
    contract = build_financial_p3_info_gain_contract()
    combo_by_id = {item.combo_id: item for item in contract.combination_references}
    sample_by_id = {item.combo_id: item for item in contract.common_sample_references}
    batches = []
    for combo_id in INFO_GAIN_COMBO_ORDER:
        combo = combo_by_id[combo_id]
        sample = sample_by_id[combo_id]
        member_ids = tuple(item[0] for item in combo.member_directions)
        merged = independent_manifest.merge(
            source,
            on=["evaluation_date", "security_id"],
            how="left",
            validate="one_to_one",
        )
        required_factor_ids = tuple(
            dict.fromkeys((*member_ids, combo.primary_baseline_factor_id))
        )
        required_value_columns = [
            _MEMBER_COLUMNS[item][0] for item in required_factor_ids
        ]
        selected = merged["eligible"].fillna(False).astype(bool)
        for column in required_value_columns:
            selected &= np.isfinite(pd.to_numeric(merged[column], errors="coerce"))
        selected &= np.isfinite(pd.to_numeric(merged["forward_return"], errors="coerce"))
        selected &= np.isfinite(pd.to_numeric(merged["size_control"], errors="coerce"))
        selected &= merged["industry_code"].fillna("").astype(str).str.strip().ne("")
        common = merged.loc[selected].copy().sort_values(
            ["evaluation_date", "security_id"], kind="stable"
        )
        manifest = common.loc[:, ["evaluation_date", "security_id"]].copy()
        manifest["eligible"] = True
        records = []
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
            records.append(member)
        member_frame = pd.concat(records, ignore_index=True)
        batches.append(
            CommonSampleMemberBaselineBatch(
                dataset_id=f"synthetic-info-gain-02-{combo_id.lower()}",
                version="v1",
                combo_id=combo_id,
                combo_definition_version=combo.combo_definition_version,
                common_sample_reference=sample.common_sample_reference,
                declared_common_sample_fingerprint=sample.common_sample_fingerprint,
                _common_sample_manifest=manifest,
                _member_frame=member_frame,
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
                source_label_references=("SYNTHETIC-FORWARD-RETURN-20D-v1",),
                provenance=(
                    {
                        "synthetic_test_only": True,
                        "provider": "deterministic_fixture",
                        "sample_source": "accepted_FIN-P3-COMBOS_common_sample",
                    }
                    if provenance is None
                    else copy.deepcopy(dict(provenance))
                ),
            )
        )
    return tuple(batches)
